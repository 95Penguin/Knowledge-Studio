"""Small, inspectable query planner for multi-turn knowledge questions."""

import json
import logging
import re
from dataclasses import dataclass

from app.generation.llm import LLMClient
from app.observability.trace import trace_stage
from app.retrieval.hybrid import Retriever
from app.retrieval.models import SearchResult

logger = logging.getLogger(__name__)

OVERVIEW_PATTERN = re.compile(
    r"整体|总体|架构|结构|概述|总结|全貌|overview|architecture", re.IGNORECASE
)
PLANNER_PROMPT = """You plan evidence retrieval for a knowledge-base question-answering system.
Use the current question and recent dialogue to resolve references and identify the user's
actual information need. Dialogue is context, not evidence. Do not answer the question.
Return one JSON object only with:
- standalone_question: a self-contained version of the current question;
- intent: fact, overview, comparison, or multi_hop;
- search_queries: 1 to 4 focused, complementary retrieval queries. For an overview, cover
  different components or sections rather than repeating the same query. Include English
  technical terms when they help search an English document.
Never invent facts about the documents; these strings are search requests, not answers.
"""


@dataclass(frozen=True)
class QueryPlan:
    original: str
    rewritten: str
    subqueries: tuple[str, ...]
    knowledge_base_ids: tuple[str, ...] = ()
    intent: str = "fact"


class QueryPlanner:
    def plan(
        self,
        question: str,
        history: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
    ) -> QueryPlan:
        question = question.strip()
        if not question:
            raise ValueError("question must not be blank")
        history = [item.strip() for item in (history or []) if item.strip()]
        rewritten = question
        # Keep the current question untouched unless it explicitly depends on prior context.
        if history and re.search(
            r"^(它|这个|那|上述|刚才|这种|其|那么|整体|总体|结构|还有|为什么|怎么|what about|and )",
            question,
            re.IGNORECASE,
        ):
            previous_user = next(
                (item[5:].strip() for item in reversed(history) if item.startswith("User: ")),
                history[-1],
            )
            rewritten = f"{previous_user[:240]}；{question}"
        parts = [part.strip(" ，,。;；") for part in re.split(r"[；;]|(?:并且|同时|以及)", rewritten)]
        parts = [part for part in parts if part]
        # Preserve a broad query for recall and add at most two focused queries.
        subqueries = tuple(dict.fromkeys([rewritten, *parts[:2]]))
        intent = "overview" if OVERVIEW_PATTERN.search(question) else "fact"
        return QueryPlan(question, rewritten, subqueries, tuple(knowledge_base_ids or ()), intent)


class ModelQueryPlanner(QueryPlanner):
    """Model-assisted question understanding, with a deterministic safe fallback."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def plan(
        self,
        question: str,
        history: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
    ) -> QueryPlan:
        fallback = super().plan(question, history, knowledge_base_ids)
        context = [item[:400] for item in (history or [])[-6:]]
        request = json.dumps(
            {"question": fallback.original, "recent_dialogue": context}, ensure_ascii=False
        )
        try:
            with trace_stage("question_understanding"):
                payload = json.loads(self.llm.generate(PLANNER_PROMPT, request))
            rewritten = payload.get("standalone_question", "")
            queries = payload.get("search_queries", [])
            intent = payload.get("intent", "fact")
            if not isinstance(rewritten, str) or not rewritten.strip() or len(rewritten) > 400:
                raise ValueError("invalid standalone question")
            if not isinstance(queries, list) or not 1 <= len(queries) <= 4:
                raise ValueError("invalid retrieval query count")
            if any(not isinstance(item, str) or not item.strip() or len(item) > 240 for item in queries):
                raise ValueError("invalid retrieval query")
            if intent not in {"fact", "overview", "comparison", "multi_hop"}:
                raise ValueError("invalid question intent")
            subqueries = tuple(dict.fromkeys([rewritten.strip(), *(item.strip() for item in queries)]))
            return QueryPlan(
                fallback.original, rewritten.strip(), subqueries[:5],
                fallback.knowledge_base_ids, intent,
            )
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError, KeyError) as error:
            logger.warning("question planner fell back: %s", type(error).__name__)
            return fallback
        except Exception:  # Planner failure must not disable evidence-backed search.
            logger.exception("question planner provider failed; using deterministic fallback")
            return fallback


class PlannedRetriever:
    """Run broad and focused queries, then fuse duplicate chunks across queries."""

    retriever_name = "planned-multi-query"

    def __init__(self, retriever: Retriever, planner: QueryPlanner | None = None, candidate_k: int = 10):
        if candidate_k < 1:
            raise ValueError("candidate_k must be positive")
        self.retriever = retriever
        self.planner = planner or QueryPlanner()
        self.candidate_k = candidate_k

    @property
    def retriever_parameters(self) -> dict[str, object]:
        return {"candidate_retriever": getattr(self.retriever, "retriever_name", "unknown")}

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.search_plan(self.planner.plan(query), top_k)

    def search_plan(self, plan: QueryPlan, top_k: int = 5) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        with trace_stage("query_planning"):
            queries = plan.subqueries
        fused: dict[str, tuple[SearchResult, float, list[str]]] = {}
        per_query: list[list[SearchResult]] = []
        for query in queries:
            if hasattr(self.retriever, "search_scoped"):
                candidates = self.retriever.search_scoped(
                    query, self.candidate_k, plan.knowledge_base_ids
                )
            else:
                candidates = self.retriever.search(query, self.candidate_k)
            per_query.append(candidates)
            for rank, result in enumerate(candidates, 1):
                if plan.knowledge_base_ids and not any(
                    result.source_path.startswith(f"{kb}/") for kb in plan.knowledge_base_ids
                ):
                    continue
                previous = fused.get(result.chunk_id)
                score = 1 / (60 + rank)
                if previous:
                    fused[result.chunk_id] = (previous[0], previous[1] + score, previous[2] + [query])
                else:
                    fused[result.chunk_id] = (result, score, [query])
        ranked_all = sorted(fused.values(), key=lambda item: (-item[1], item[0].chunk_id))
        if plan.intent == "overview" and len(queries) > 1:
            selected: list[tuple[SearchResult, float, list[str]]] = []
            selected_ids: set[str] = set()
            sections: set[tuple[str, ...]] = set()
            for candidates in per_query:
                if len(selected) >= top_k:
                    break
                for candidate in candidates:
                    section = tuple(candidate.section_path)
                    if candidate.chunk_id in selected_ids or section in sections:
                        continue
                    item = fused.get(candidate.chunk_id)
                    if item is not None:
                        selected.append(item)
                        selected_ids.add(candidate.chunk_id)
                        sections.add(section)
                        break
            ranked = selected + [
                item for item in ranked_all if item[0].chunk_id not in selected_ids
            ][: max(0, top_k - len(selected))]
        else:
            ranked = ranked_all[:top_k]
        return [
            SearchResult(
                rank=index, score=result.score, chunk_id=result.chunk_id, title=result.title,
                section_path=result.section_path, source_path=result.source_path,
                source_url=result.source_url, content=result.content, source_type=result.source_type,
                retrieval_details={**(result.retrieval_details or {}), "matched_queries": queries},
            )
            for index, (result, _, queries) in enumerate(ranked, 1)
        ]
