# SupportPilot

面向技术支持场景的企业知识库与智能工单 Agent。

当前仓库已完成 **P0-6：可观测的流式 Agent 闭环**。已打通：

```text
Redis 文档 -> 混合检索/重排 -> 带引用回答 -> 设备授权 -> 工单/转人工
```

受控 Agent 会话可持久化恢复，工单支持详情、历史和受控状态流转；知识回答通过 SSE 增量展示，并附带请求级 Trace、RAG 分阶段耗时和 Token 用量。完整范围见 [docs/P0.md](docs/P0.md)。

第一版语料已决定使用 **Redis Open Source 7.4 官方英文文档**。环境安装见 [docs/environment-macos.md](docs/environment-macos.md)。

获取语料（需要访问 GitHub）：

```bash
./scripts/fetch_redis_docs.sh
```

首次成功后使用生成的 commit 固定复现：

```bash
REDIS_DOCS_COMMIT=<manifest中的resolved_commit> ./scripts/fetch_redis_docs.sh
```

## 目录

```text
support-pilot/
├── ai-service/       Python FastAPI：文档、检索、RAG、Agent、评测
├── backend/          Java Spring Boot：用户、设备、工单、权限、审计
├── data/             本地原始文档、处理结果和评测集（大文件不提交）
├── deploy/           本地依赖服务
├── docs/             需求、范围、工具契约和决策记录
└── web/              Web 前端：流式问答、Trace、设备与工单
```

## 本地启动（当前骨架）

AI 服务使用 `uv` 管理 Python 3.12、虚拟环境和依赖：

```bash
cd ai-service
uv sync --extra dev
uv run pytest
uv run uvicorn app.main:app --reload --port 8001
```

访问 `http://localhost:8001/health`检查服务，或打开
`http://localhost:8001/` 使用 Redis 知识问答页。页面与 API 由 FastAPI 同源托管，
当前无需单独安装 Node.js。

Java 服务需要 JDK 17 和 Maven：

```bash
cd backend
mvn spring-boot:run
```

访问 `http://localhost:8080/api/health`。

## Docker Compose 一键启动

先把 `.env.example` 复制为 `.env`，填入 `LLM_API_KEY`，然后在仓库根目录执行：

```bash
docker compose up --build
```

打开 `http://localhost:8001`。Compose 会启动 PostgreSQL、Spring Boot 与
FastAPI/前端；业务数据、Agent 会话和 Hugging Face 模型缓存均使用独立卷。
首次启动需下载 E5 和 reranker 模型，会比后续启动慢。

停止服务：

```bash
docker compose down
```

除非确定要删除所有本地数据，不要使用 `docker compose down -v`。

## 检索方案对比

本地模型已经缓存后，可一次运行 BM25、E5-base、RRF 与 RRF + Reranker：

```bash
./scripts/compare_retrievers.sh
```

命令会在 `data/eval/results/comparison-v1/` 中生成四份逐题 JSON、汇总 JSON 和
Markdown 对比表。当前 50 题首轮结果及失败分析见
[docs/retrieval-comparison-v1.md](docs/retrieval-comparison-v1.md)。

运行预注册的 Dense:BM25 权重实验：

```bash
./scripts/experiment_rrf_weights.sh
```

实验结论见 [docs/rrf-weight-experiment-v1.md](docs/rrf-weight-experiment-v1.md)。

## 开发纪律

每个功能遵循：需求 -> 自己初步设计 -> AI 审查 -> 小步实现 -> 阅读 diff -> 测试/故障注入 -> 独立修改与复述。
