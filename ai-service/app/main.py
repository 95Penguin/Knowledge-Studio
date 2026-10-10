import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent.backend import BackendToolError, JavaBackendClient
from app.agent.models import (
    AgentTurnRequest,
    AgentTurnResponse,
    ConversationHistory,
    ConversationSummary,
)
from app.agent.runtime import get_agent_service
from app.agent.service import ControlledAgentService
from app.config import get_settings
from app.generation.models import AnswerRequest, AnswerResponse, KnowledgeToolEvent
from app.generation.runtime import (
    get_knowledge_base_store,
    get_knowledge_conversation_store,
)
from app.knowledge_agent import KnowledgeAgentService, get_knowledge_agent_service
from app.knowledge_bases import KnowledgeBaseStore
from app.knowledge_history import KnowledgeConversationStore

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness only; dependency readiness will be added with the first datastore."""
    return {"status": "ok", "service": "ai-service", "environment": settings.app_env}


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/auth/login", tags=["auth"])
def login(request: LoginRequest) -> dict[str, object]:
    """Same-origin login proxy; the browser never needs a hard-coded Java host."""
    backend = JavaBackendClient(settings.backend_base_url, settings.backend_timeout_seconds)
    try:
        return backend.login(request.email, request.password)
    except BackendToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@app.post("/api/knowledge/answer", response_model=AnswerResponse, tags=["knowledge"])
def answer_knowledge(
    request: AnswerRequest,
    service: Annotated[KnowledgeAgentService, Depends(get_knowledge_agent_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> AnswerResponse:
    owner_id = _authorize_knowledge_request(request, authorization)
    return service.answer(request.question, request.history, request.knowledge_base_ids, owner_id)


def _authorize_knowledge_request(request: AnswerRequest, authorization: str | None) -> str | None:
    if not request.knowledge_base_ids:
        return None
    owner_id = _current_user_id(authorization)
    try:
        get_knowledge_base_store().assert_owned(request.knowledge_base_ids, owner_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return owner_id


@app.post("/api/knowledge/stream", tags=["knowledge"])
async def stream_knowledge_answer(
    request: AnswerRequest,
    service: Annotated[KnowledgeAgentService, Depends(get_knowledge_agent_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Stream typed RAG events after grounding and citation validation."""
    owner_id = _authorize_knowledge_request(request, authorization)
    conversation_store = None
    conversation_owner = None
    history = request.history
    if request.conversation_id:
        conversation_store = get_knowledge_conversation_store()
        conversation_owner = owner_id or _current_user_id(authorization)
        try:
            conversation = conversation_store.recent(request.conversation_id, conversation_owner)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        if conversation["knowledge_base_ids"] != request.knowledge_base_ids:
            raise HTTPException(status_code=409, detail="conversation knowledge base cannot change")
        history = [
            line
            for turn in conversation["turns"]
            for line in (
                f"User: {turn['question']}",
                f"Assistant: {turn['answer']['answer'][:400]}",
            )
        ]

    async def events() -> AsyncIterator[str]:
        yield _sse("status", {"phase": "planning", "message": "正在改写问题并选择检索范围"})
        queue: asyncio.Queue[KnowledgeToolEvent | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_tool_event(event: KnowledgeToolEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def run_answer() -> AnswerResponse:
            try:
                return await asyncio.to_thread(
                    service.answer,
                    request.question,
                    history,
                    request.knowledge_base_ids,
                    owner_id,
                    on_tool_event,
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_answer())
        try:
            while (tool_event := await queue.get()) is not None:
                yield _sse("tool", tool_event.model_dump(mode="json"))
            response = await task
        except ValueError as error:
            yield _sse("error", {"message": str(error)})
            return
        except Exception:  # noqa: BLE001 - close the event stream with a stable error shape
            yield _sse("error", {"message": "知识库回答服务暂时不可用"})
            return
        finally:
            if not task.done():
                task.cancel()
        if request.conversation_id and conversation_owner and conversation_store:
            conversation_store.append(
                request.conversation_id,
                conversation_owner,
                request.question,
                response,
                request.knowledge_base_ids,
            )
        if response.trace:
            yield _sse("trace", response.trace.model_dump(mode="json"))
        yield _sse("answer_start", {"status": response.status})
        for offset in range(0, len(response.answer), 12):
            yield _sse("answer_delta", {"text": response.answer[offset : offset + 12]})
            await asyncio.sleep(0)
        for citation in response.citations:
            yield _sse("citation", citation.model_dump(mode="json"))
        for question in response.suggested_questions:
            yield _sse("follow_up", {"question": question})
        yield _sse("complete", response.model_dump(mode="json"))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _current_user_id(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="knowledge base access requires login")
    backend = JavaBackendClient(settings.backend_base_url, settings.backend_timeout_seconds)
    try:
        return str(backend.current_user(authorization.removeprefix("Bearer ").strip())["userId"])
    except BackendToolError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class CreateKnowledgeConversationRequest(BaseModel):
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=5)


@app.get("/api/knowledge/conversations", tags=["knowledge"])
def list_knowledge_conversations(
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeConversationStore, Depends(get_knowledge_conversation_store)] = None,
) -> list[dict[str, object]]:
    return store.list(_current_user_id(authorization))


@app.post("/api/knowledge/conversations", tags=["knowledge"])
def create_knowledge_conversation(
    request: CreateKnowledgeConversationRequest,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeConversationStore, Depends(get_knowledge_conversation_store)] = None,
) -> dict[str, object]:
    owner_id = _current_user_id(authorization)
    if request.knowledge_base_ids:
        try:
            get_knowledge_base_store().assert_owned(request.knowledge_base_ids, owner_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    return store.create(owner_id, request.knowledge_base_ids)


@app.get("/api/knowledge/conversations/{conversation_id}", tags=["knowledge"])
def get_knowledge_conversation(
    conversation_id: str,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeConversationStore, Depends(get_knowledge_conversation_store)] = None,
) -> dict[str, object]:
    try:
        return store.get(conversation_id, _current_user_id(authorization))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/knowledge-bases", tags=["knowledge"])
def list_knowledge_bases(
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeBaseStore, Depends(get_knowledge_base_store)] = None,
) -> list[dict[str, object]]:
    return store.list(_current_user_id(authorization))


@app.post("/api/knowledge-bases", tags=["knowledge"])
def create_knowledge_base(
    request: CreateKnowledgeBaseRequest,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeBaseStore, Depends(get_knowledge_base_store)] = None,
) -> dict[str, object]:
    try:
        return store.create(request.name, _current_user_id(authorization), request.description)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.patch("/api/knowledge-bases/{kb_id}", tags=["knowledge"])
def update_knowledge_base(
    kb_id: str,
    request: CreateKnowledgeBaseRequest,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeBaseStore, Depends(get_knowledge_base_store)] = None,
) -> dict[str, object]:
    try:
        return store.update(
            kb_id, _current_user_id(authorization), request.name, request.description
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/knowledge-bases/{kb_id}/documents", tags=["knowledge"])
def list_knowledge_documents(
    kb_id: str,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeBaseStore, Depends(get_knowledge_base_store)] = None,
) -> list[dict[str, object]]:
    try:
        return store.list_documents(kb_id, _current_user_id(authorization))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/knowledge-bases/{kb_id}/documents", tags=["knowledge"])
async def upload_knowledge_document(
    kb_id: str,
    file: Annotated[UploadFile, File()],
    source_url: Annotated[str | None, Form()] = None,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeBaseStore, Depends(get_knowledge_base_store)] = None,
) -> dict[str, object]:
    owner_id = _current_user_id(authorization)
    try:
        content = await file.read(10 * 1024 * 1024 + 1)
        return await asyncio.to_thread(
            store.upload, kb_id, file.filename or "", content, owner_id, source_url
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.put("/api/knowledge-bases/{kb_id}/documents/{document_id}", tags=["knowledge"])
async def replace_knowledge_document(
    kb_id: str,
    document_id: str,
    file: Annotated[UploadFile, File()],
    source_url: Annotated[str | None, Form()] = None,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeBaseStore, Depends(get_knowledge_base_store)] = None,
) -> dict[str, object]:
    owner_id = _current_user_id(authorization)
    try:
        content = await file.read(10 * 1024 * 1024 + 1)
        return await asyncio.to_thread(
            store.replace, kb_id, document_id, file.filename or "", content, owner_id, source_url
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/knowledge-bases/{kb_id}/documents/{document_id}", tags=["knowledge"])
async def delete_knowledge_document(
    kb_id: str,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeBaseStore, Depends(get_knowledge_base_store)] = None,
) -> dict[str, str]:
    try:
        await asyncio.to_thread(store.delete, kb_id, document_id, _current_user_id(authorization))
        return {"status": "deleted"}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/knowledge-bases/{kb_id}/documents/{document_id}/content", tags=["knowledge"])
def knowledge_document_content(
    kb_id: str,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
    store: Annotated[KnowledgeBaseStore, Depends(get_knowledge_base_store)] = None,
) -> PlainTextResponse:
    try:
        return PlainTextResponse(
            store.document_text(kb_id, document_id, _current_user_id(authorization))
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/agent/turn", response_model=AgentTurnResponse, tags=["agent"])
def agent_turn(
    request: AgentTurnRequest,
    service: Annotated[ControlledAgentService, Depends(get_agent_service)],
) -> AgentTurnResponse:
    try:
        return service.turn(request)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/agent/stream", tags=["agent"])
async def stream_agent_turn(
    request: AgentTurnRequest,
    service: Annotated[ControlledAgentService, Depends(get_agent_service)],
) -> StreamingResponse:
    if request.action != "ask":
        raise HTTPException(status_code=400, detail="SSE 接口当前只接受 ask action")

    async def events() -> AsyncIterator[str]:
        yield _sse("status", {"phase": "retrieval", "message": "正在检索并验证文档证据"})
        try:
            response = await asyncio.to_thread(service.turn, request)
        except (PermissionError, ValueError) as error:
            yield _sse("error", {"message": str(error)})
            return
        except Exception:  # noqa: BLE001 - streaming responses must close with a safe event
            yield _sse("error", {"message": "回答服务暂时不可用"})
            return

        if response.trace:
            yield _sse("trace", response.trace.model_dump(mode="json"))
        for citation in response.citations:
            yield _sse("citation", citation.model_dump(mode="json"))
        if response.required_action:
            yield _sse("follow_up", {"action": response.required_action})
        yield _sse(
            "answer_start",
            {"conversation_id": response.conversation_id, "state": response.state},
        )
        for offset in range(0, len(response.message), 12):
            yield _sse("answer_delta", {"text": response.message[offset : offset + 12]})
            await asyncio.sleep(0)
        yield _sse("complete", response.model_dump(mode="json"))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="查看历史对话前必须登录")
    return authorization.removeprefix("Bearer ").strip()


@app.get("/api/agent/conversations", response_model=list[ConversationSummary], tags=["agent"])
def list_agent_conversations(
    token: Annotated[str, Depends(bearer_token)],
    service: Annotated[ControlledAgentService, Depends(get_agent_service)],
) -> list[ConversationSummary]:
    try:
        return service.list_conversations(token)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get(
    "/api/agent/conversations/{conversation_id}",
    response_model=ConversationHistory,
    tags=["agent"],
)
def get_agent_conversation(
    conversation_id: str,
    token: Annotated[str, Depends(bearer_token)],
    service: Annotated[ControlledAgentService, Depends(get_agent_service)],
) -> ConversationHistory:
    try:
        return service.conversation_history(conversation_id, token)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


frontend_dist = settings.project_root / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="web")
