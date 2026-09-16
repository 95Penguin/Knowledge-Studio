from typing import Literal

from pydantic import BaseModel, Field


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ModelAnswer(BaseModel):
    answer: str = ""
    citation_ids: list[str] = Field(default_factory=list)
    should_refuse: bool = False
    refusal_reason: str | None = None


class Citation(BaseModel):
    evidence_id: str
    chunk_id: str
    title: str
    section_path: list[str]
    source_path: str
    source_url: str
    source_type: Literal["official", "engineering_practice"] = "official"


class RequestTrace(BaseModel):
    request_id: str
    total_ms: float
    stages_ms: dict[str, float] = Field(default_factory=dict)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AnswerResponse(BaseModel):
    status: Literal["answered", "refused"]
    answer: str
    citations: list[Citation]
    top_evidence_score: float | None = None
    refusal_reason: str | None = None
    trace: RequestTrace | None = None
