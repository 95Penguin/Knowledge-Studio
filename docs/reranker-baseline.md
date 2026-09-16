# RRF + BGE Reranker 重排实验 v1

实验日期：2026-08-16  
候选：BM25 Top 20 + E5-base Top 20，经 RRF 融合  
Reranker：`BAAI/bge-reranker-base`  
固定 revision：`a2ea80a31f4bb01c0b2db0a472a1512b6e5a4400`

## 原理

BM25、embedding 和 RRF 都主要用于快速候选召回。Cross-encoder 将中文问题与每个英文候选
拼成一对共同编码，直接输出相关性分数：

```text
(query, passage_1) -> score_1
(query, passage_2) -> score_2
...
```

它比双塔向量检索更精细，但不能预计算查询—文档对，因此推理成本随候选数量增长。

输入 passage 保留：

```text
title + section_path + content
```

最大输入长度为512 tokens。BGE分数用于相对排序，不解释为正确概率。

## 总体对比

| 方案 | Recall@5 | 命中数 | P50 | P95 |
|---|---:|---:|---:|---:|
| BM25 | 57.89% | 11/19 | 0.034 ms | 0.058 ms |
| E5-base | 78.95% | 15/19 | 21.256 ms | 24.658 ms |
| RRF | 84.21% | 16/19 | 22.788 ms | 40.182 ms |
| RRF + rerank 20 | 94.74% | 18/19 | 1419.510 ms | 1660.730 ms |
| RRF + rerank 10 | **94.74%** | **18/19** | **762.314 ms** | **799.134 ms** |

`rerank_k=10` 保持与20相同的 Recall@5，同时P95下降约52%，因此选为默认值。

## 重排带来的修复

相对 RRF，reranker 找回：

- `MEMORY USAGE` 标准章节；
- 主从复制异步性与同步期间行为的标准章节。

它能够把“主题相关”与“直接回答问题”区分得更细，修复了 RRF 对共同错误候选的奖励。

## 唯一严格失败

`redis-007` 询问用 hash 节省小对象内存。重排后的前四名全部来自
`Using hashes to abstract a very memory-efficient plain key-value store on top of Redis`，实际能支持回答；
但 v1 标准只接受 `Use hashes when possible`，所以严格 Recall 仍记为0。

不根据模型结果回改 v1 标签。扩充评测集时，应把“替代证据 any-of”和“必须同时出现的证据 all-of”
分开表达。就当前业务可用性而言，这一题已召回正确主题和可用证据；就冻结标签指标而言仍是18/19。

## 工程取舍

重排把 Recall@5 从84.21%提高到94.74%，但单次查询热态延迟增加到约0.8秒。后续可比较：

- 更小的跨语言 reranker；
- ONNX/Core ML 推理；
- 仅在问题复杂或候选分数接近时触发重排；
- 缓存重复查询结果。

P0 默认保留 `rerank_k=10`，优先保证可解释的效果基线，性能优化作为后续实验。

## 复现

```bash
./scripts/search_rerank.sh "如何查看某个Redis key占用多少内存" 5
./scripts/evaluate_rerank.sh
```

完整报告：`data/eval/results/rrf-bge-reranker-base-k10-v1.json`。
