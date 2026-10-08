# Knowledge Studio

基于 Spring Boot、FastAPI 与 React 的多知识库 RAG 问答系统。项目从 SupportPilot
技术支持 Demo 演进而来，当前主流程已经调整为通用知识库：

```text
创建知识库 -> 上传文档 -> 解析与结构分块 -> 建立关键词/向量/结构图索引
-> 问题改写与拆分 -> 多路召回 -> RRF 融合 -> Cross Encoder 精排
-> 受证据约束的回答 -> SSE 事件流 -> 引用与推荐追问
```

Redis 7.4 官方文档保留为内置示例库。用户还可以分别创建“项目文档”“课程资料”等多个
知识库，上传 Markdown、TXT 或 PDF 后独立检索，数据按用户与知识库隔离。

## 已实现能力

- 多知识库管理：创建、列出、修改名称和描述、文档上传与列表、按知识库限定检索。
- 对话历史：按用户持久化知识库问答、引用与耗时；左侧可打开历史会话继续追问。
- 文档处理：Markdown 标题层级切分、超长段落递归切分、重叠窗口、来源元数据保留；
  PDF 通过 `pypdf` 提取文本。
- 多路召回：关键词、E5 向量和标题层级图并行检索，通过稳定 `chunk_id` 去重并执行
  加权 RRF 融合。
- 精排与回答：BGE Cross Encoder 精排；模型只能引用程序提供的证据 ID，引用在服务端
  二次校验，低相关度或非法引用会拒答。
- 复杂问题：结合最近对话进行保守改写，对复合问题拆成多个子查询，再对各子查询结果
  二次融合。
- 多轮与流式事件：`status`、`trace`、`answer_delta`、`citation`、`follow_up`、
  `complete`、`error` 等 SSE 事件分别返回。
- 可观测与评测：请求级 Trace 记录检索、重排、生成耗时和 Token；仓库包含 50 条检索
  评测集、MRR/NDCG/Recall 对比脚本与失败样本分析。
- MCP 工具：Spring Boot 暴露 `/mcp` JSON-RPC 端点，支持 `initialize`、`tools/list`、
  `tools/call`；Python Agent 会发现 Schema、校验参数并调用 Java 工具。原技术支持工单
  流程作为 MCP 与 Human in the Loop 的扩展示例保留，不是通用知识库首页的依赖。

## 技术结构

```text
frontend/       React + Vite：知识库、上传、SSE 问答、引用、Trace
ai-service/     FastAPI：解析分块、检索、RAG、Agent、MCP Client、评测
backend/        Spring Boot：登录鉴权、MCP Server、业务工具权限与审计
data/           内置示例语料、索引、评测集与实验结果
docs/           需求、实验结论、架构与面试说明
```

Spring Boot 与 FastAPI 的职责边界：Java 负责用户身份和需要强权限、事务、审计的业务工具；
Python 负责模型、文档处理、检索和 Agent 编排。React 在本地开发时分别请求两个服务，
生产构建由 FastAPI 同源托管。

## 两种检索运行模式

`RETRIEVAL_MODE=local` 是默认可复现模式：关键词索引、E5 向量和标题图均保存到本地文件，
适合面试演示和离线评测。

`RETRIEVAL_MODE=external` 使用 Elasticsearch 关键词检索与 Milvus 向量检索，并继续使用
标题图召回、RRF 和 BGE 精排。配置 `ELASTICSEARCH_*` 与 `MILVUS_*` 后运行：

```dotenv
RETRIEVAL_MODE=external
ELASTICSEARCH_URL=http://127.0.0.1:9200
ELASTICSEARCH_INDEX=knowledge_studio_chunks
ELASTICSEARCH_API_KEY=
MILVUS_URL=http://127.0.0.1:19530
MILVUS_COLLECTION=knowledge_studio_chunks
MILVUS_TOKEN=root:Milvus
```

本地 Elasticsearch 未开启安全认证时 `ELASTICSEARCH_API_KEY` 留空；若开启认证，填写
API Key 的实际值，不要添加 `ApiKey ` 前缀。`root:Milvus` 是常见本地 Standalone
初始化凭据，如部署时修改过账号密码，就填写实际的 `用户名:密码`。

```bash
cd ai-service
uv run --extra embeddings support-pilot-sync-external
```

这两种模式共用相同的 `Retriever` 接口和下游链路。上述 `127.0.0.1` 地址用于在宿主机
直接运行 Python；Docker Compose 会自动改用服务名 `elasticsearch` 和 `milvus`。
当前 ES/Milvus 外部索引用于内置示例语料；用户上传的独立知识库仍使用本地索引。

## 本地启动

复制环境变量并配置 OpenAI Compatible 模型：

```bash
cp .env.example .env
```

启动 Java：

```bash
cd backend
mvn spring-boot:run
```

启动 Python：

```bash
cd ai-service
uv sync --extra dev --extra embeddings
uv run uvicorn app.main:app --reload --port 8001
```

开发 React 页面：

```bash
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。也可以先运行 `npm run build`，再访问
`http://127.0.0.1:8001`，FastAPI 会优先托管 `frontend/dist`。
本地初始化账号为 `demo@supportpilot.dev`，密码为 `demo1234`。

Docker Compose：

```bash
cd frontend && npm run build && cd ..
docker compose up --build
```

这条命令保持默认的本地检索模式。若要用 Docker 启动 Elasticsearch 和 Milvus，先确认
`data/processed/chunks.jsonl` 已生成、`.env` 中填好可用的 `LLM_API_KEY` 等模型配置，
再运行：

```bash
cd frontend && npm run build && cd ..
docker compose -f compose.yaml -f compose.external.yaml up --build
```

首次启动会拉取 ES、Milvus、etcd、MinIO 镜像，下载 E5 向量模型，并由一次性
`external-indexer` 容器把内置语料写入 ES/Milvus；随后启动 AI 服务。Docker Desktop
建议分配至少 8 GB 内存。可用 `docker compose -f compose.yaml -f compose.external.yaml ps`
查看健康状态；停止时用相同的 `-f` 参数加 `down`，数据卷会保留，不要随意加 `-v`。
ES 的 9200 和 Milvus 的 19530 仅绑定到本机回环地址；它们在容器内的地址分别是
`http://elasticsearch:9200` 和 `http://milvus:19530`，不需要手动填到 `.env`。

## 验证

```bash
cd ai-service
uv run --extra dev pytest
uv run --extra dev ruff check app tests

cd ../backend
mvn test

cd ../frontend
npm run build
```

原始 Redis 语料与生成索引受 `.gitignore` 管理。若未准备 `data/processed/chunks.jsonl`，
依赖完整语料的评测集一致性测试会跳过或需要先运行语料构建脚本；其余单元和 API 测试不
依赖网络模型。

## 面试时可按这条链路介绍

用户先创建知识库并上传文档。FastAPI 根据文档类型提取文本，按标题结构与 Token 上限
切成 Chunk，保留知识库 ID、标题路径、来源和文档 ID等元数据。索引阶段同时写入关键词、
向量和结构图索引。

用户提问后，系统利用最近对话改写指代不清的问题，并对复合问题拆分。多个子查询分别走
关键词、向量和结构图召回，结果按 `chunk_id` 去重并用加权 RRF 融合，再交给 BGE
Cross Encoder 精排。超过阈值的证据连同稳定证据 ID 注入 Prompt，大模型生成结构化回答。
服务端检查每个引用 ID确实来自本次召回，再通过 SSE 分事件返回回答、引用、推荐追问和
Trace；证据不足时拒答。

更具体的简历条目对应关系与可以诚实表达的实现边界见
[docs/resume-alignment.md](docs/resume-alignment.md)。
