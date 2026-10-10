import time
import uuid
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from app.generation.models import RequestTrace


@dataclass
class TraceCollector:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: float = field(default_factory=time.perf_counter)
    stages: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def snapshot(self) -> RequestTrace:
        return RequestTrace(
            request_id=self.request_id,
            total_ms=round((time.perf_counter() - self.started_at) * 1000, 3),
            stages_ms={name: round(value, 3) for name, value in self.stages.items()},
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )


_current_trace: ContextVar[TraceCollector | None] = ContextVar("request_trace", default=None)


@contextmanager
def bind_trace(trace: TraceCollector) -> Iterator[None]:
    token = _current_trace.set(trace)
    try:
        yield
    finally:
        _current_trace.reset(token)


@contextmanager
def trace_stage(name: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        trace = _current_trace.get()
        if trace is not None:
            trace.stages[name] += (time.perf_counter() - started) * 1000


def record_usage(prompt_tokens: int | None, completion_tokens: int | None) -> None:
    trace = _current_trace.get()
    if trace is not None:
        if prompt_tokens is not None:
            trace.prompt_tokens = (trace.prompt_tokens or 0) + prompt_tokens
        if completion_tokens is not None:
            trace.completion_tokens = (trace.completion_tokens or 0) + completion_tokens
