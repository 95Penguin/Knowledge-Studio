FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app/ai-service
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY ai-service/pyproject.toml ai-service/uv.lock ./
RUN uv sync --frozen --no-dev --extra embeddings
COPY ai-service/app ./app
COPY web /app/web
COPY data/indexes /app/data/indexes
EXPOSE 8001
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
