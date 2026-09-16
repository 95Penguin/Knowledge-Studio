# Weighted RRF 权重实验

## 实验控制

- 固定同一份 50 题评测集，其中 45 条计入检索指标。
- 固定 BM25、E5-base 索引、`candidate_k=20`、`rrf_k=60`、Top-5。
- BM25 权重固定为 1，只改变 Dense 权重：2、4、8。
- Dense-only 作为对照组。

## 结果

| 方案 | Recall@1 | Recall@3 | Recall@5 | MRR | 命中题数 | P95(ms) |
|---|---:|---:|---:|---:|---:|---:|
| Dense-only | 0.3778 | 0.5556 | **0.6222** | **0.4689** | **28/45** | 25.101 |
| Dense:BM25 = 2:1 | 0.1333 | 0.3556 | 0.4889 | 0.2644 | 22/45 | 25.771 |
| Dense:BM25 = 4:1 | 0.2222 | 0.4444 | 0.4889 | 0.3274 | 22/45 | 22.885 |
| Dense:BM25 = 8:1 | 0.2889 | 0.4889 | 0.5556 | 0.3837 | 25/45 | 23.115 |

完整逐题结果见
[`data/eval/results/rrf-weight-experiment-v1`](../data/eval/results/rrf-weight-experiment-v1)。

## 结论

提高 Dense 权重能持续改善等权 RRF，但三个权重均未达到预注册的替换条件：Recall@5
不得低于 Dense-only，且 MRR 应有稳定提升。当前最好的 8:1 仍比 Dense-only 少命中 3 题，
Recall@5 低 6.66 个百分点，MRR 低 8.52 个百分点。

原因不是简单的“Dense 权重还不够大”。RRF 只使用名次，不使用原始置信度；一个同时出现在
低质量 BM25 列表与 Dense 列表中的错误候选，会得到双路累加并挤压 Dense-only 的正确候选。
继续无限增大 Dense 权重最终只会退化为 Dense-only，不能证明词法召回提供了额外价值。

因此本轮不修改线上配置。下一候选方案是 **Dense-only 候选召回 + Cross-Encoder Reranker**，
并对比 `rerank_k=10/20`，避免让当前低质量 BM25 参与候选融合。
