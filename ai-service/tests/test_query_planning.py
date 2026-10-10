import json

from app.retrieval.models import SearchResult
from app.retrieval.planning import ModelQueryPlanner, PlannedRetriever, QueryPlan, QueryPlanner


class QueryAwareRetriever:
    retriever_name = "query-aware"

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        chunk_id = "shared" if "RRF" in query else query
        return [SearchResult(
            rank=1, score=0.8, chunk_id=chunk_id, title=query, section_path=[query],
            source_path="kb/chunk.md", source_url="/chunk", content=query,
        )]


def test_planner_rewrites_context_dependent_question_and_splits_compound_query() -> None:
    plan = QueryPlanner().plan("这个如何配置；同时怎么评测", ["RRF 融合有什么作用"])
    assert plan.rewritten.startswith("RRF 融合有什么作用")
    assert len(plan.subqueries) == 3


def test_planned_retriever_deduplicates_chunks_across_subqueries() -> None:
    retriever = PlannedRetriever(QueryAwareRetriever(), candidate_k=3)
    results = retriever.search("RRF是什么；同时RRF怎么调参", top_k=5)
    assert [result.chunk_id for result in results] == ["shared"]
    assert len(results[0].retrieval_details["matched_queries"]) >= 2


def test_model_planner_uses_dialogue_to_plan_complementary_overview_searches() -> None:
    class PlannerLLM:
        def generate(self, system_prompt: str, user_prompt: str) -> str:
            assert "Do not answer" in system_prompt
            assert "User: 论文里的 attention 指什么" in user_prompt
            return json.dumps({
                "standalone_question": "Transformer 模型的整体结构是什么？",
                "intent": "overview",
                "search_queries": ["Transformer encoder stack", "Transformer decoder stack"],
            })

    plan = ModelQueryPlanner(PlannerLLM()).plan(
        "整体结构是什么样的", ["User: 论文里的 attention 指什么"], ["my-kb"]
    )
    assert plan.intent == "overview"
    assert plan.rewritten == "Transformer 模型的整体结构是什么？"
    assert "Transformer decoder stack" in plan.subqueries
    assert plan.knowledge_base_ids == ("my-kb",)


def test_model_planner_invalid_response_falls_back_to_previous_user_question() -> None:
    class BrokenLLM:
        def generate(self, system_prompt: str, user_prompt: str) -> str:
            return "not-json"

    plan = ModelQueryPlanner(BrokenLLM()).plan(
        "整体结构是什么样的", ["User: 论文里的 attention 指什么", "Assistant: 注意力是..."],
    )
    assert plan.intent == "overview"
    assert plan.rewritten.startswith("论文里的 attention 指什么")


def test_overview_retrieval_covers_different_query_sections() -> None:
    class SectionRetriever:
        def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
            section = "decoder" if "decoder" in query else "encoder"
            return [SearchResult(
                rank=1, score=0.8, chunk_id=section, title="Transformer",
                section_path=[section], source_path=f"kb/{section}.md",
                source_url=f"/{section}", content=section,
            )]

    retriever = PlannedRetriever(SectionRetriever())
    plan = QueryPlan("整体结构", "Transformer structure", (
        "Transformer encoder", "Transformer decoder",
    ), intent="overview")
    results = retriever.search_plan(plan, top_k=2)
    assert {result.chunk_id for result in results} == {"encoder", "decoder"}
