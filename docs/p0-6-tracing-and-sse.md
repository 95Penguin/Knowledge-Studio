# P0-6：请求 Trace、阶段耗时与 SSE

## 目标

每次知识问答生成一个 `request_id`，把一次请求从检索到生成的主要阶段串起来。回答页直接显示延迟和 Token 用量，便于区分“模型慢”与“检索慢”，后续也能据此计算 P50/P95。

## Trace 字段

`trace` 随回答返回并持久化到会话历史：

- `request_id`：本次 RAG 请求的唯一标识；
- `total_ms`：检索、重排、生成和回答校验的端到端耗时；
- `stages_ms.bm25`：关键词召回；
- `stages_ms.query_embedding`：问题向量化；
- `stages_ms.dense_search`：向量相似度召回；
- `stages_ms.rrf_fusion`：BM25 与向量结果融合；
- `stages_ms.reranker`：候选结果精排；
- `stages_ms.llm_generation`：模型请求到完整结构化响应返回；
- `prompt_tokens`、`completion_tokens`：上游模型返回的 Token 用量。

阶段耗时使用单调时钟统计，同一阶段被调用多次时累加。日志中的 `rag_trace` 可用 `request_id` 与前端显示对应。

## SSE 事件

`POST /api/agent/stream` 当前只处理 `ask`，按顺序返回：

1. `status`：请求已经进入检索与证据验证；
2. `trace`：完整请求的阶段耗时；
3. `answer_start`：开始呈现回答；
4. `answer_delta`：Markdown 文本片段；
5. `complete`：完整的 `AgentTurnResponse`，包括引用、工具事件、状态与 Trace；
6. `error`：权限、参数或内部错误的安全消息。

## 为什么不是直接转发模型 Token

当前生成接口要求模型先返回结构化 JSON，服务端还要检查证据 ID 是否来自本次检索白名单，并将引用映射回真实文档。若直接把供应商 Token 发到浏览器，未经验证的内容可能已经展示，之后无法撤回。

因此 P0-6 采用“安全缓冲流”：服务端先取得完整结构化回答并通过引用验证，再通过 SSE 增量显示已经验证的 Markdown。它改善了回答呈现，但不会降低模型首包之前的等待时间。若后续要实现真正的模型 Token 流，需要设计可流式校验的答案协议，或将正文与引用声明分成两个可验证阶段。

## 验证

```bash
cd ai-service
uv run --extra dev ruff check app tests
uv run --extra dev pytest
node --check ../web/app.js
```

浏览器开发者工具的 Network 页面可查看 `/api/agent/stream` 持续接收的 SSE 帧；回答完成后，页面底部会显示 Trace 摘要，刷新并恢复历史对话后仍然存在。
