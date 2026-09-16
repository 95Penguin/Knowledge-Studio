# 带引用回答与证据不足拒答

## 链路

```text
question
  -> BM25 + E5-base
  -> RRF
  -> BGE rerank 10 -> top 5
  -> evidence score gate
  -> grounded prompt
  -> LLM JSON output
  -> schema and citation validation
  -> answer + program-owned citations / refusal
```

## 两层拒答

第一层由程序控制。若无候选或最高 reranker 分数低于 `EVIDENCE_SCORE_THRESHOLD`，不调用
LLM，直接拒答。首版阈值为0.10：当前19道领域题最低 top1 为0.4847，唯一 PostgreSQL
负样本为0.0008。该样本量不足以证明阈值稳定，扩充评测集时必须加入更多无答案和领域边界题。

第二层由模型判断证据内容是否真的足以回答。即使检索分数过门槛，模型也可以返回
`should_refuse=true`。模型拒答仍需通过结构校验。

## 引用安全

程序给 Top 5 分配临时ID `E1` 到 `E5`，Prompt只允许模型返回这些ID。模型不能提交URL；
生成后由程序把ID映射为检索结果中已有的 `chunk_id`、标题、章节和 Redis 官网URL。

以下情况全部安全拒答：

- 输出不是合法JSON；
- 输出字段不符合Schema；
- 答案为空或没有引用；
- 引用了不存在的 `E99`；
- 模型主动判断证据不足。

引用存在只能证明“来源真实”，不能自动证明句子被来源支持。后续答案评测还要检查 citation
correctness / entailment。

## 模型输出协议

```json
{
  "answer": "...",
  "citation_ids": ["E1", "E3"],
  "should_refuse": false,
  "refusal_reason": null
}
```

服务输出协议：

```json
{
  "status": "answered",
  "answer": "...",
  "citations": [
    {
      "evidence_id": "E1",
      "chunk_id": "...",
      "title": "...",
      "section_path": ["..."],
      "source_path": "content/...md",
      "source_url": "https://redis.io/docs/latest/..."
    }
  ],
  "top_evidence_score": 0.99,
  "refusal_reason": null
}
```

## 配置

复制 `.env.example` 为 `ai-service/.env`，填写一个支持 OpenAI-compatible
`/chat/completions` 的服务：

```dotenv
LLM_API_KEY=...
LLM_BASE_URL=https://provider.example/v1
LLM_MODEL=provider-model-name
LLM_TIMEOUT_SECONDS=60
EVIDENCE_SCORE_THRESHOLD=0.10
ANSWER_TOP_K=5
```

不得提交真实 API key。

## 运行

命令行：

```bash
cd ai-service
uv run --extra embeddings support-pilot-answer "appendfsync everysec有什么风险？"
```

HTTP：

```bash
cd ai-service
uv run --extra embeddings uvicorn app.main:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/api/knowledge/answer \
  -H 'Content-Type: application/json' \
  -d '{"question":"appendfsync everysec有什么风险？"}'
```

首次进程加载 E5-base 与 BGE reranker 较慢，后续请求复用缓存实例。

## 批量回答评测

回答评测集位于 `data/eval/answer-questions.v1.jsonl`，包含16个可回答的 Redis 7.4
问题和8个应拒答问题。负样本同时覆盖完全无关问题和语料边界问题，避免只用一个
PostgreSQL 问题把拒答效果估计得过于乐观。

运行会真实调用配置的 LLM，每个通过检索阈值的样本通常产生一次 API 请求：

```bash
cd ai-service
uv run --extra embeddings support-pilot-answer-eval
```

默认报告写入 `data/eval/results/answers-deepseek-chat-v1.json`。也可以指定输入输出：

```bash
uv run --extra embeddings support-pilot-answer-eval \
  --questions ../data/eval/answer-questions.v1.jsonl \
  --output ../data/eval/results/answers-local-run.json
```

自动指标包括：

- `answerability_accuracy`：该回答的问题是否回答、该拒绝的问题是否拒绝；
- `positive_answer_rate`：正样本回答率；
- `negative_refusal_accuracy`：负样本拒答准确率；
- `citation_source_recall`：回答引用是否命中人工标注的文档和章节；
- `request_success_rate`、平均/P50/P95 端到端延迟和分类型准确率。

每条明细保留 `required_answer_points`，并将 `answer_point_review` 标为 `pending`。
要点覆盖和事实忠实度是语义判断，当前版本要求人工复核，不使用字符串包含或让同一个
生成模型给自己打分。报告不保存 Prompt、API Key 或文档全文。
