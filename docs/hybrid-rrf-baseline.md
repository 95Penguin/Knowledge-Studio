# BM25 + E5-base RRF 混合检索 v1

实验日期：2026-08-15  
语料与评测：与 BM25、E5-small、E5-base 基线完全相同

## 方法

每次查询分别获取：

```text
BM25 Top 20
E5-base Top 20
```

不直接相加 BM25 与余弦分数，因为两种分数的量纲和分布不同。使用 Reciprocal Rank Fusion：

```text
RRF(d) = Σ 1 / (k + rank_r(d))
```

初始参数：

```text
candidate_k_per_retriever = 20
rrf_k = 60
final_top_k = 5
```

同一 chunk 若同时被两路召回，会累加两次贡献；只出现在一路的候选仍会保留。输出的
`retrieval_details.components` 记录两路原始排名、原始分数和各自的 RRF 贡献。

## 结果

| 方案 | Recall@5 | 命中数 | 热态 P95 |
|---|---:|---:|---:|
| BM25 | 57.89% | 11/19 | 0.058 ms |
| E5-small | 68.42% | 13/19 | 11.417 ms |
| E5-base | 78.95% | 15/19 | 24.658 ms |
| BM25 + E5-base RRF | **84.21%** | **16/19** | 40.182 ms |

分类 Recall@5：

| 分类 | RRF |
|---|---:|
| latency | 100.0% |
| memory | 33.3% |
| persistence | 100.0% |
| replication | 66.7% |
| sentinel | 100.0% |
| cluster | 100.0% |
| security | 100.0% |

RRF 相比 E5-base 新增命中 `REPLICAOF` 提升 master 的问题，使总 Recall@5 提升5.26个百分点。主要耗时仍是查询向量编码；本次完整报告记录的热态P95为40.182ms。

## 失败分析

### `redis-005`：融合退化

BM25 单路可以命中 `MEMORY USAGE`，但 BM25 和向量检索共同偏向若干宽泛 memory/INFO
片段。RRF奖励“两路共同出现”，把标准命令章节挤出 Top 5。融合不是单调改进，需要逐题验证。

### `redis-007`：标注可能过窄

Top 5 中多个 `Using hashes to abstract a very memory-efficient...` 片段可以支持 hash
节省内存的回答，但 v1 只把 `Use hashes when possible` 标为标准章节。当前不在看到结果后修改标签，扩充评测时再独立审查替代证据。

### `redis-011`：两路均缺少正确候选

BM25 无法跨越中文“主从/同步/异步”与英文文档，E5-base 又把多个无关片段排在复制事实章节之前。RRF只能融合已有排名，不能创造两路都没召回的候选。

## 结论

RRF证明关键词与向量候选具有互补性，但“两个检索器都同意”不等于“真正回答问题”。下一步对融合 Top 20 使用更精细的问题—证据相关性模型重排，并与无重排结果严格对比。

## 复现

```bash
./scripts/search_hybrid.sh "如何把 Redis replica 提升为 master" 5
./scripts/evaluate_hybrid.sh
```

完整结果：`data/eval/results/hybrid-rrf-v1.json`。
