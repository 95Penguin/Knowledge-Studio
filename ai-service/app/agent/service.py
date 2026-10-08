import hashlib
import time
import uuid
from typing import Any

from app.agent.backend import BackendToolError, JavaBackendClient, request_id
from app.agent.conversation import Conversation
from app.agent.intent import QuestionIntent, classify_question
from app.agent.models import (
    AgentState,
    AgentTurnRequest,
    AgentTurnResponse,
    ConversationHistory,
    ConversationSummary,
    ConversationTurn,
    ToolEvent,
)
from app.agent.store import ConversationStore
from app.generation.service import GroundedAnswerService
from app.knowledge_bases import KnowledgeBaseStore


class ControlledAgentService:
    def __init__(
        self,
        answers: GroundedAnswerService,
        backend: JavaBackendClient,
        max_steps: int = 12,
        store: ConversationStore | None = None,
        knowledge_bases: KnowledgeBaseStore | None = None,
    ) -> None:
        self.answers = answers
        self.backend = backend
        self.max_steps = max_steps
        self.store = store
        self.knowledge_bases = knowledge_bases
        self.conversations: dict[str, Conversation] = {}

    def turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        conversation = self._conversation(request.conversation_id)
        self._bind_identity(conversation, request.backend_token)
        conversation.step_count += 1
        if conversation.step_count > self.max_steps:
            if request.backend_token:
                response = self._transfer(
                    conversation,
                    request.model_copy(update={"message": "达到最大处理步数，自动转人工"}),
                )
                self._record_turn(conversation, request, response)
                self._save(conversation)
                return response
            conversation.state = AgentState.TRANSFERRED
            response = self._response(
                conversation,
                "已达到最大处理步数，为避免循环已停止自动处理；登录后可转交人工支持。",
                tool_event=ToolEvent(
                    tool="transfer_to_human", status="skipped", summary="未登录，未创建人工记录"
                ),
            )
            self._record_turn(conversation, request, response)
            self._save(conversation)
            return response

        handlers = {
            "ask": self._ask,
            "resolved": self._resolved,
            "unresolved": self._unresolved,
            "authorize_device": self._authorize_device,
            "confirm_ticket": self._confirm_ticket,
            "transfer": self._transfer,
            "general_answer": self._general_answer,
        }
        try:
            response = handlers[request.action](conversation, request)
            self._record_turn(conversation, request, response)
            return response
        finally:
            self._save(conversation)

    def list_conversations(self, token: str) -> list[ConversationSummary]:
        if not token or not self.store:
            return []
        return self.store.list_for_identity(self._identity_fingerprint(token))

    def conversation_history(self, conversation_id: str, token: str) -> ConversationHistory:
        if not token:
            raise PermissionError("查看历史对话前必须登录")
        conversation = self._conversation(conversation_id)
        self._bind_identity(conversation, token)
        return ConversationHistory(
            id=conversation.id,
            title=(conversation.original_question or "新对话")[:60],
            state=conversation.state,
            turns=conversation.history,
        )

    def _conversation(self, conversation_id: str | None) -> Conversation:
        if conversation_id is None:
            conversation = Conversation(str(uuid.uuid4()))
            self.conversations[conversation.id] = conversation
            return conversation
        if conversation_id not in self.conversations:
            persisted = self.store.get(conversation_id) if self.store else None
            if persisted is None:
                raise ValueError("conversation_id 不存在或已经失效")
            self.conversations[conversation_id] = persisted
        return self.conversations[conversation_id]

    def _save(self, conversation: Conversation) -> None:
        if self.store:
            self.store.save(conversation)

    def _bind_identity(self, conversation: Conversation, token: str | None) -> None:
        if not token:
            return
        fingerprint = self._identity_fingerprint(token)
        if conversation.token_fingerprint and conversation.token_fingerprint != fingerprint:
            raise PermissionError("该会话已绑定其他登录身份")
        conversation.token_fingerprint = fingerprint

    def _identity_fingerprint(self, token: str) -> str:
        try:
            user = self.backend.current_user(token)
        except BackendToolError as error:
            raise PermissionError(str(error)) from error
        user_id = str(user.get("userId") or "")
        if not user_id:
            raise PermissionError("登录身份校验结果缺少 userId")
        return hashlib.sha256(user_id.encode()).hexdigest()

    def _record_turn(
        self,
        conversation: Conversation,
        request: AgentTurnRequest,
        response: AgentTurnResponse,
    ) -> None:
        labels = {
            "resolved": "已解决",
            "unresolved": "仍未解决",
            "authorize_device": "授权查询设备",
            "confirm_ticket": "确认创建工单",
            "transfer": "转人工",
            "general_answer": "查看通识回答",
        }
        user_message = (request.message or "").strip() if request.action == "ask" else labels[request.action]
        conversation.history.append(
            ConversationTurn(user_message=user_message, response=response.model_copy(deep=True))
        )

    def _ask(self, conversation: Conversation, request: AgentTurnRequest) -> AgentTurnResponse:
        self._require_state(conversation, AgentState.NEW, AgentState.WAITING_FEEDBACK)
        if not request.backend_token:
            raise ValueError("使用受控 Agent 前必须登录")
        question = (request.message or "").strip()
        if not question:
            raise ValueError("ask action 必须提供 message")
        started = time.perf_counter()
        try:
            history = [turn.user_message for turn in conversation.history if turn.user_message]
            if request.knowledge_base_ids:
                if not self.knowledge_bases:
                    raise ValueError("knowledge base store unavailable")
                owner_id = str(self.backend.current_user(request.backend_token)["userId"])
                self.knowledge_bases.assert_owned(request.knowledge_base_ids, owner_id)
            if history or request.knowledge_base_ids:
                result = self.answers.answer(
                    question, history=history[-3:],
                    knowledge_base_ids=request.knowledge_base_ids,
                )
            else:
                result = self.answers.answer(question)
        except (ValueError, PermissionError):
            raise
        except Exception:  # noqa: BLE001 - provider/runtime failures must enter the safe fallback
            conversation.original_question = question
            return self._transfer(
                conversation,
                request.model_copy(update={"message": "知识模型不可用，自动转人工"}),
            )
        event = ToolEvent(
            tool="search_knowledge",
            status="succeeded" if result.status == "answered" else "failed",
            summary="检索并生成带引用回答" if result.status == "answered" else "知识库证据不足",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            request_id=result.trace.request_id if result.trace else None,
        )
        conversation.original_question = question
        conversation.question_intent = classify_question(question)
        if result.status == "refused" and conversation.question_intent == QuestionIntent.CONCEPTUAL:
            conversation.state = AgentState.WAITING_GENERAL_ANSWER_CONFIRMATION
            return self._response(
                conversation,
                result.answer + "\n\n这是概念类问题，可以查看明确标注为无证据的模型通识回答。",
                required_action="general_answer_or_stop", tool_event=event, trace=result.trace,
            )
        conversation.state = AgentState.WAITING_FEEDBACK
        message = result.answer + "\n\n这个回答是否解决了问题？"
        return self._response(
            conversation, message, required_action="resolved_or_unresolved",
            citations=result.citations, tool_event=event, trace=result.trace,
        )

    def _resolved(self, conversation: Conversation, request: AgentTurnRequest) -> AgentTurnResponse:
        self._require_state(
            conversation,
            AgentState.WAITING_FEEDBACK,
            AgentState.WAITING_DEVICE_FEEDBACK,
            AgentState.WAITING_GENERAL_ANSWER_CONFIRMATION,
        )
        conversation.state = AgentState.COMPLETED
        return self._response(conversation, "很好，本次排查已结束。")

    def _unresolved(self, conversation: Conversation, request: AgentTurnRequest) -> AgentTurnResponse:
        if conversation.state == AgentState.WAITING_FEEDBACK:
            if conversation.question_intent == QuestionIntent.CONCEPTUAL:
                conversation.state = AgentState.WAITING_GENERAL_ANSWER_CONFIRMATION
                return self._response(
                    conversation,
                    "这是概念类问题，不会查询你的设备。你可以查看无证据的通识回答，或结束本次对话。",
                    required_action="general_answer_or_stop",
                )
            conversation.state = AgentState.WAITING_DEVICE_AUTHORIZATION
            return self._response(
                conversation,
                "我可以查询你名下设备的脱敏运行状态。只有在你明确授权并选择设备后才会执行。",
                required_action="authorize_device",
            )
        if conversation.state == AgentState.WAITING_DEVICE_FEEDBACK:
            conversation.ticket_draft = {
                "title": f"Redis 支持请求：{(conversation.original_question or '')[:80]}",
                "description": conversation.original_question or "Redis support request",
                "deviceId": conversation.device_id,
                "priority": "MEDIUM",
            }
            conversation.state = AgentState.WAITING_TICKET_CONFIRMATION
            return self._response(
                conversation,
                "问题仍未解决。我已生成工单草稿；请检查后明确确认，系统才会创建工单。",
                required_action="confirm_ticket",
            )
        raise ValueError(f"当前状态 {conversation.state} 不接受 unresolved")

    def _general_answer(
        self, conversation: Conversation, request: AgentTurnRequest
    ) -> AgentTurnResponse:
        self._require_state(conversation, AgentState.WAITING_GENERAL_ANSWER_CONFIRMATION)
        started = time.perf_counter()
        try:
            answer = self.answers.general_answer(conversation.original_question or "")
            event = ToolEvent(
                tool="general_knowledge", status="succeeded", summary="无知识库证据的模型通识回答",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            message = "【通识回答｜无知识库证据】\n" + answer
        except Exception:  # noqa: BLE001 - optional fallback must fail closed
            event = ToolEvent(
                tool="general_knowledge", status="failed", summary="通识模型不可用",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            message = "通识回答暂时不可用，且没有可引用的知识库证据。"
        conversation.state = AgentState.COMPLETED
        return self._response(conversation, message, tool_event=event)

    def _authorize_device(
        self, conversation: Conversation, request: AgentTurnRequest
    ) -> AgentTurnResponse:
        self._require_state(conversation, AgentState.WAITING_DEVICE_AUTHORIZATION)
        if not request.backend_token or not request.device_id:
            raise ValueError("设备授权需要 backend_token 和 device_id")
        signature = f"query_device:{request.device_id}"
        self._reject_duplicate(conversation, signature)
        event, device = self._call_backend(
            "query_device",
            lambda rid: self.backend.query_device(request.backend_token or "", request.device_id or "", rid),
        )
        if device is None:
            return self._tool_failure(conversation, event)
        conversation.device_id = request.device_id
        conversation.device = device
        conversation.state = AgentState.WAITING_DEVICE_FEEDBACK
        return self._response(
            conversation,
            f"已获得授权并查询设备：{device.get('name', 'Redis device')}，状态为 {device.get('status', 'UNKNOWN')}。"
            "请结合此前文档建议继续检查。问题是否已经解决？",
            required_action="resolved_or_unresolved", tool_event=event,
        )

    def _confirm_ticket(
        self, conversation: Conversation, request: AgentTurnRequest
    ) -> AgentTurnResponse:
        self._require_state(conversation, AgentState.WAITING_TICKET_CONFIRMATION)
        if not request.backend_token or not conversation.ticket_draft:
            raise ValueError("创建工单需要登录身份和有效草稿")
        key = f"agent-{conversation.id}"
        self._reject_duplicate(conversation, f"create_ticket:{key}")
        payload = {**conversation.ticket_draft, "idempotencyKey": key, "confirmed": True}
        event, ticket = self._call_backend(
            "create_ticket",
            lambda rid: self.backend.create_ticket(request.backend_token or "", rid, payload),
        )
        if ticket is None:
            return self._tool_failure(conversation, event)
        conversation.state = AgentState.TICKET_CREATED
        return self._response(
            conversation,
            f"工单已创建，编号 {ticket.get('id')}，当前状态 {ticket.get('status')}。",
            tool_event=event, ticket=ticket,
        )

    def _transfer(self, conversation: Conversation, request: AgentTurnRequest) -> AgentTurnResponse:
        if not request.backend_token:
            raise ValueError("转人工前必须登录，以便持久化处理记录")
        signature = f"transfer_to_human:{conversation.id}"
        self._reject_duplicate(conversation, signature)
        event, transfer = self._call_backend(
            "transfer_to_human",
            lambda rid: self.backend.transfer_to_human(
                request.backend_token or "", rid,
                {"conversationId": conversation.id, "reason": request.message or "用户请求转人工",
                 "summary": conversation.original_question or "Redis support conversation"},
            ),
        )
        if transfer is None:
            return self._tool_failure(conversation, event)
        conversation.state = AgentState.TRANSFERRED
        return self._response(
            conversation,
            f"已创建人工转接记录 {transfer.get('id')}，等待人工支持继续处理。",
            tool_event=event,
        )

    def _call_backend(self, tool: str, call: Any) -> tuple[ToolEvent, dict[str, Any] | None]:
        rid = request_id()
        started = time.perf_counter()
        try:
            result = call(rid)
            return ToolEvent(
                tool=tool, status="succeeded", summary="Java 业务校验通过",
                duration_ms=round((time.perf_counter() - started) * 1000, 3), request_id=rid,
            ), result
        except BackendToolError as error:
            status = "denied" if error.status_code in {400, 401, 403, 404} else "failed"
            return ToolEvent(
                tool=tool, status=status, summary=str(error),
                duration_ms=round((time.perf_counter() - started) * 1000, 3), request_id=rid,
            ), None

    def _tool_failure(self, conversation: Conversation, event: ToolEvent) -> AgentTurnResponse:
        conversation.state = AgentState.TRANSFERRED
        return self._response(
            conversation, f"工具执行未成功：{event.summary} 已安全停止并转交人工支持。",
            tool_event=event,
        )

    def _reject_duplicate(self, conversation: Conversation, signature: str) -> None:
        if conversation.last_sensitive_signature == signature:
            raise ValueError("检测到重复敏感工具调用，已拒绝执行")
        conversation.last_sensitive_signature = signature

    def _require_state(self, conversation: Conversation, *allowed: AgentState) -> None:
        if conversation.state not in allowed:
            raise ValueError(f"当前状态 {conversation.state} 不允许执行此操作")

    def _response(
        self, conversation: Conversation, message: str, required_action: str | None = None,
        citations: list[Any] | None = None, tool_event: ToolEvent | None = None,
        ticket: dict[str, Any] | None = None,
        trace: Any | None = None,
    ) -> AgentTurnResponse:
        events = [tool_event] if tool_event else []
        conversation.events.extend(events)
        return AgentTurnResponse(
            conversation_id=conversation.id, state=conversation.state, message=message,
            required_action=required_action, citations=citations or [], tool_events=events,
            device=conversation.device, ticket=ticket, ticket_draft=conversation.ticket_draft,
            trace=trace,
        )
