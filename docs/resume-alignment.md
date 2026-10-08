# 简历条目与代码对应

## 项目描述

可以表述为：基于 Spring Boot、FastAPI 与 React 构建多知识库问答系统，完成从文档
上传、解析切分、索引构建、检索增强生成到引用溯源、推荐追问和多轮对话的完整链路。

## 知识库构建与 RAG 问答

- `app/knowledge_bases.py`：知识库隔离、Markdown/TXT/PDF 上传、结构分块与索引重建。
- `app/ingestion/chunking.py`：标题路径、Token 上限、段落切分与重叠窗口。
- `app/generation/service.py`：证据阈值、结构化输出、引用 ID 校验与拒答。
- `app/main.py`：普通回答 API 与类型化 SSE 事件。

面试表达：标题路径会拼入向量文本以补足 Chunk 语义，同时标题、正文和来源字段继续独立
保存，便于关键词检索、展示与引用。

## 多路检索与效果优化

- `app/retrieval/hybrid.py`：任意数量召回路的加权 RRF，以 `chunk_id` 融合。
- `app/retrieval/graph.py`：文档标题与章节层级形成轻量结构图召回。
- `app/retrieval/reranker.py`：BGE Cross Encoder 精排。
- `app/retrieval/external.py`：Elasticsearch 与 Milvus 的检索和数据同步适配器。
- `app/retrieval/planning.py`：问题改写、拆分、指定知识库路由及多查询融合。

面试时要区分：本地演示默认使用本地 BM25、E5 向量与标题图；生产式外部模式提供
Elasticsearch 与 Milvus 适配。不要说本地默认模式已经启动了 ES/Milvus 集群。

## Agent 与工具调用

- `backend/.../mcp/McpController.java`：MCP 初始化、工具发现和工具调用。
- `app/agent/mcp.py`：工具发现缓存、Schema 参数校验、JSON-RPC 调用与错误映射。
- `app/agent/service.py`：有最大步数、授权确认、幂等保护和失败转移的受控编排示例。

完整过程可以回答为：模型或编排层决定需要某个工具，先从 MCP Server 获得工具名称、
说明与输入 Schema；Python 组装结构化参数并做一次客户端校验，再通过 `tools/call` 传给
Java。Java 根据 Token 确认身份，执行归属校验、事务和审计，最后把结构化结果返回给
Python并加入后续上下文。

## SSE 与可观测

通用知识库端点为 `/api/knowledge/stream`。当前先完成整个受证据约束的回答并校验引用，
再增量输出文本，同时独立发送 citation、follow_up 和 trace 事件。这种实现优先保证引用
安全；若面试官追问“是否是模型原生 Token 流”，应回答当前版本是校验后的增量渲染，
不是生成阶段首 Token 到达即转发。

## 评测

仓库已有固定检索评测集、Recall@K、MRR、NDCG、逐题结果和多组检索器对比。评测集由
人工根据固定文档构造并复核相关 Chunk，不依赖模型临时生成；模型可以辅助扩充候选问题，
但进入基准集前要人工确认答案与相关文档。
