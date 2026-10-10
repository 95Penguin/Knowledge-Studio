"""Bounded, read-only agent for questions requiring multiple pieces of knowledge."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from fastapi import Depends

from app.config import get_settings
from app.generation.llm import limit_generation_timeout
from app.generation.models import AnswerResponse, KnowledgeToolEvent
from app.generation.runtime import get_answer_service, get_knowledge_base_store
from app.generation.service import GroundedAnswerService
from app.knowledge_bases import KnowledgeBaseStore
from app.observability.trace import TraceCollector, bind_trace, trace_stage
from app.retrieval.models import SearchResult
from app.retrieval.planning import QueryPlanner

logger = logging.getLogger(__name__)

COMPLEX_QUESTION = re.compile(
    r"整体|总体|结构|架构|概述|总结|对比|比较|区别|联系|多跳|为什么|如何实现|"
    r"overview|architecture|compare|how does|why does",
    re.IGNORECASE,
)
AGENT_PROMPT = """You are a read-only knowledge-base research agent.
Choose the NEXT action after examining the question, conversation context and tool observations.
Return one JSON object only: {"tool": "...", "arguments": {...}}.
Allowed tools:
- get_outline: {}. List documents and section headings in the selected knowledge bases.
- search_chunks: {"query": "specific search question"}. Search and rerank evidence.
- read_section: {"kb_id": "selected KB ID", "document_id": "ID from outline",
  "section": "heading from outline"}. Read up to four indexed chunks of a section.
- read_neighbors: {"kb_id": "selected KB ID", "chunk_id": "ID from search"}.
  Read adjacent chunks of the same document.
- finish: {}. Stop gathering evidence; a separate grounded model will write the final answer.
Do not answer in this action. Do not invent document IDs, chunk IDs, section names, or facts.
You may only use the selected knowledge bases. Dialogue is context, never factual evidence.
For an overview or comparison, gather evidence from all essential parts before finishing.
If a result covers only one part, inspect another section or run a more targeted search.
"""


@dataclass(frozen=True)
class ToolOutcome:
    observation: dict[str, Any]
    evidence: list[SearchResult]


class KnowledgeTools:
    """Small allowlisted tool surface; all document reads use the active owned index."""

    def __init__(self, retriever: Any, store_factory: Callable[[], KnowledgeBaseStore]) -> None:
        self.retriever = retriever
        self.store_factory = store_factory

    def execute(
        self, tool: str, arguments: dict[str, Any], kb_ids: list[str], owner_id: str
    ) -> ToolOutcome:
        store = self.store_factory()
        store.assert_owned(kb_ids, owner_id)
        if tool == "get_outline":
            outlines = [
                {"kb_id": kb_id, "documents": store.outline(kb_id, owner_id)[:10]}
                for kb_id in kb_ids
            ]
            for outline in outlines:
                for document in outline["documents"]:
                    document["sections"] = document["sections"][:40]
            return ToolOutcome({"outlines": outlines}, [])
        if tool == "search_chunks":
            query = arguments.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 400:
                raise ValueError("search query must be 1-400 characters")
            retriever = getattr(self.retriever, "retriever", self.retriever)
            with trace_stage("agent_search"):
                if hasattr(retriever, "search_scoped"):
                    results = retriever.search_scoped(query.strip(), 5, tuple(kb_ids))
                else:
                    results = retriever.search(query.strip(), 5)
                    results = [
                        item
                        for item in results
                        if any(item.source_path.startswith(f"{kb_id}/") for kb_id in kb_ids)
                    ]
            return ToolOutcome(self._evidence_observation(results), results)
        kb_id = arguments.get("kb_id")
        if not isinstance(kb_id, str) or kb_id not in kb_ids:
            raise PermissionError("tool may only read a selected knowledge base")
        if tool == "read_section":
            document_id, section = arguments.get("document_id"), arguments.get("section")
            if not isinstance(document_id, str) or not isinstance(section, str):
                raise ValueError("document_id and section are required")
            results = store.read_section(
                kb_id, owner_id, document_id, section.split(" > ")[-1], limit=4
            )
            return ToolOutcome(self._evidence_observation(results), results)
        if tool == "read_neighbors":
            chunk_id = arguments.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                raise ValueError("chunk_id is required")
            results = store.read_neighbors(kb_id, owner_id, chunk_id, radius=1)
            return ToolOutcome(self._evidence_observation(results), results)
        raise ValueError("unknown knowledge tool")

    @staticmethod
    def _evidence_observation(results: list[SearchResult]) -> dict[str, Any]:
        return {
            "matches": [
                {
                    "chunk_id": item.chunk_id,
                    "title": item.title,
                    "section": " > ".join(item.section_path),
                    "score": round(item.score, 3),
                    "excerpt": item.content[:700],
                }
                for item in results
            ]
        }


class KnowledgeAgentService:
    """Fast RAG for facts; bounded observe-and-retrieve loop for complex questions."""

    def __init__(
        self,
        answers: GroundedAnswerService,
        store_factory: Callable[[], KnowledgeBaseStore],
        max_steps: int = 5,
        deadline_seconds: float = 90.0,
    ) -> None:
        if not 1 <= max_steps <= 10:
            raise ValueError("max_steps must be between 1 and 10")
        if deadline_seconds < 10:
            raise ValueError("deadline_seconds must be at least 10")
        self.answers = answers
        self.tools = KnowledgeTools(answers.retriever, store_factory)
        self.max_steps = max_steps
        self.deadline_seconds = deadline_seconds

    def answer(
        self,
        question: str,
        history: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        owner_id: str | None = None,
        on_tool_event: Callable[[KnowledgeToolEvent], None] | None = None,
    ) -> AnswerResponse:
        kb_ids = knowledge_base_ids or []
        if not kb_ids or not COMPLEX_QUESTION.search(question):
            return self.answers.answer(question, history, kb_ids)
        if not owner_id:
            raise PermissionError("knowledge agent requires an authenticated owner")
        self.tools.store_factory().assert_owned(kb_ids, owner_id)
        trace = TraceCollector()
        with bind_trace(trace):
            response, events = self._research(
                question, history or [], kb_ids, owner_id, on_tool_event
            )
        snapshot = trace.snapshot()
        logger.info("knowledge_agent_trace %s", snapshot.model_dump_json())
        return response.model_copy(update={"trace": snapshot, "tool_events": events})

    def _research(
        self,
        question: str,
        history: list[str],
        kb_ids: list[str],
        owner_id: str,
        on_tool_event: Callable[[KnowledgeToolEvent], None] | None,
    ) -> tuple[AnswerResponse, list[KnowledgeToolEvent]]:
        deadline = time.perf_counter() + self.deadline_seconds
        final_reserve_seconds = min(30.0, self.deadline_seconds / 3)
        evidence: dict[str, SearchResult] = {}
        observations: list[dict[str, Any]] = []
        events: list[KnowledgeToolEvent] = []
        for step in range(self.max_steps):
            decision_budget = min(15.0, deadline - time.perf_counter() - final_reserve_seconds)
            if decision_budget <= 0:
                break
            action, arguments = self._choose_action(
                question, history, kb_ids, observations, evidence, decision_budget
            )
            if action == "finish":
                sections = {tuple(item.section_path) for item in evidence.values()}
                if evidence and (len(sections) >= 2 or step == self.max_steps - 1):
                    break
                observations.append(
                    {"warning": "Need evidence from another section before finishing."}
                )
                continue
            started = time.perf_counter()
            try:
                outcome = self.tools.execute(action, arguments, kb_ids, owner_id)
                for item in outcome.evidence:
                    evidence.setdefault(item.chunk_id, item)
                observations.append({"tool": action, "result": outcome.observation})
                status = "succeeded"
                count = len(outcome.evidence)
            except (ValueError, FileNotFoundError, PermissionError) as error:
                observations.append({"tool": action, "error": str(error)[:180]})
                status, count = "failed", 0
            event = KnowledgeToolEvent(
                tool=action,
                status=status,
                evidence_count=count,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            events.append(event)
            if on_tool_event:
                on_tool_event(event)
            if len(evidence) >= 10:
                break
        if not evidence:
            started = time.perf_counter()
            outcome = self.tools.execute("search_chunks", {"query": question}, kb_ids, owner_id)
            evidence.update((item.chunk_id, item) for item in outcome.evidence)
            event = KnowledgeToolEvent(
                tool="search_chunks",
                status="succeeded",
                evidence_count=len(outcome.evidence),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            events.append(event)
            if on_tool_event:
                on_tool_event(event)
        standalone_question = QueryPlanner().plan(question, history, kb_ids).rewritten
        remaining = deadline - time.perf_counter()
        if remaining <= 0 and evidence:
            response = AnswerResponse(
                status="refused",
                answer="本次检索超时，请缩小问题范围后重试。",
                citations=[],
                refusal_reason="knowledge agent deadline exceeded",
            )
        else:
            with limit_generation_timeout(max(0.1, remaining)):
                response = self.answers.answer_from_evidence(
                    standalone_question, list(evidence.values())[:10]
                )
        return response, events

    def _choose_action(
        self,
        question: str,
        history: list[str],
        kb_ids: list[str],
        observations: list[dict[str, Any]],
        evidence: dict[str, SearchResult],
        decision_timeout: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        payload = {
            "question": question,
            "recent_dialogue": [item[:400] for item in history[-6:]],
            "selected_knowledge_base_ids": kb_ids,
            "observations": observations[-5:],
            "collected_sections": list(
                dict.fromkeys(" > ".join(item.section_path) for item in evidence.values())
            ),
        }
        try:
            with trace_stage("agent_decision"), limit_generation_timeout(decision_timeout):
                decision = json.loads(
                    self.answers.llm.generate(AGENT_PROMPT, json.dumps(payload, ensure_ascii=False))
                )
            tool, arguments = decision.get("tool"), decision.get("arguments")
            if tool in {
                "get_outline",
                "search_chunks",
                "read_section",
                "read_neighbors",
                "finish",
            } and isinstance(arguments, dict):
                return tool, arguments
        except (ValueError, TypeError, AttributeError, TimeoutError):
            logger.warning("knowledge agent decision was invalid; using search fallback")
        except httpx.HTTPError:
            logger.exception("knowledge agent decision provider failed; using search fallback")
        return "search_chunks", {"query": question}


def get_knowledge_agent_service(
    answers: Annotated[GroundedAnswerService, Depends(get_answer_service)],
) -> KnowledgeAgentService:
    settings = get_settings()
    return KnowledgeAgentService(
        answers,
        get_knowledge_base_store,
        max_steps=settings.knowledge_agent_max_steps,
        deadline_seconds=settings.knowledge_agent_deadline_seconds,
    )
