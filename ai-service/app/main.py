import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent.models import (
    AgentTurnRequest,
    AgentTurnResponse,
    ConversationHistory,
    ConversationSummary,
)
from app.agent.runtime import get_agent_service
from app.agent.service import ControlledAgentService
from app.config import get_settings
from app.generation.models import AnswerRequest, AnswerResponse
from app.generation.runtime import get_answer_service
from app.generation.service import GroundedAnswerService

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness only; dependency readiness will be added with the first datastore."""
    return {"status": "ok", "service": "ai-service", "environment": settings.app_env}


@app.post("/api/knowledge/answer", response_model=AnswerResponse, tags=["knowledge"])
def answer_knowledge(
    request: AnswerRequest,
    service: Annotated[GroundedAnswerService, Depends(get_answer_service)],
) -> AnswerResponse:
    return service.answer(request.question)


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


web_dir = settings.project_root / "web"
if web_dir.is_dir():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
