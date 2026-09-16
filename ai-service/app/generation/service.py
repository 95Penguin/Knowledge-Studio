import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from app.generation.llm import LLMClient
from app.generation.models import AnswerResponse, Citation, ModelAnswer
from app.generation.prompt import GENERAL_KNOWLEDGE_PROMPT, SYSTEM_PROMPT, build_user_prompt
from app.observability.trace import TraceCollector, bind_trace
from app.retrieval.models import SearchResult

logger = logging.getLogger(__name__)


class GroundedAnswerService:
    def __init__(
        self,
        retriever: Any,
        llm: LLMClient,
        top_k: int = 5,
        evidence_score_threshold: float = 0.10,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.retriever = retriever
        self.llm = llm
        self.top_k = top_k
        self.evidence_score_threshold = evidence_score_threshold

    def answer(self, question: str) -> AnswerResponse:
        trace = TraceCollector()
        with bind_trace(trace):
            response = self._answer(question)
        snapshot = trace.snapshot()
        logger.info("rag_trace %s", snapshot.model_dump_json())
        return response.model_copy(update={"trace": snapshot})

    def _answer(self, question: str) -> AnswerResponse:
        question = question.strip()
        if not question:
            raise ValueError("question must not be blank")
        evidence = self.retriever.search(question, top_k=self.top_k)
        top_score = evidence[0].score if evidence else None
        if not evidence or top_score is None or top_score < self.evidence_score_threshold:
            return self._refusal(
                top_score,
                "没有检索到达到相关性阈值的 Redis 官方文档证据。",
            )

        raw = self.llm.generate(SYSTEM_PROMPT, build_user_prompt(question, evidence))
        try:
            generated = ModelAnswer.model_validate_json(_extract_json(raw))
        except (ValidationError, json.JSONDecodeError, ValueError) as error:
            return self._refusal(top_score, f"模型输出无法通过结构校验：{type(error).__name__}")

        if generated.should_refuse:
            return self._refusal(
                top_score,
                generated.refusal_reason or "模型判断现有证据不足。",
            )
        if not generated.answer.strip() or not generated.citation_ids:
            return self._refusal(top_score, "模型未提供有效答案或证据引用。")

        evidence_by_id = {f"E{index}": result for index, result in enumerate(evidence, start=1)}
        invalid_ids = [item for item in generated.citation_ids if item not in evidence_by_id]
        if invalid_ids:
            return self._refusal(top_score, "模型引用了不存在的证据，已安全拒绝回答。")

        citation_ids = list(dict.fromkeys(generated.citation_ids))
        citations = [
            _citation(evidence_id, evidence_by_id[evidence_id]) for evidence_id in citation_ids
        ]
        return AnswerResponse(
            status="answered",
            answer=generated.answer.strip(),
            citations=citations,
            top_evidence_score=top_score,
        )

    def general_answer(self, question: str) -> str:
        question = question.strip()
        if not question:
            raise ValueError("question must not be blank")
        raw = self.llm.generate(GENERAL_KNOWLEDGE_PROMPT, f"Question:\n{question}")
        generated = ModelAnswer.model_validate_json(_extract_json(raw))
        if generated.should_refuse or not generated.answer.strip():
            raise ValueError(generated.refusal_reason or "general answer refused")
        if generated.citation_ids:
            raise ValueError("general answer must not contain evidence citations")
        return generated.answer.strip()

    @staticmethod
    def _refusal(top_score: float | None, reason: str) -> AnswerResponse:
        return AnswerResponse(
            status="refused",
            answer="当前知识库证据不足，无法可靠回答这个问题。",
            citations=[],
            top_evidence_score=top_score,
            refusal_reason=reason,
        )


def _citation(evidence_id: str, result: SearchResult) -> Citation:
    return Citation(
        evidence_id=evidence_id,
        chunk_id=result.chunk_id,
        title=result.title,
        section_path=result.section_path,
        source_path=result.source_path,
        source_url=result.source_url,
        source_type=result.source_type,
    )


def _extract_json(text: str) -> str:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    return fenced.group(1) if fenced else stripped
