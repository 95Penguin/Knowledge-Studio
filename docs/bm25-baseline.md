# BM25 检索基线 v1

实验日期：2026-08-15  
语料：`redis-ops-7.4-v1`，420 chunks  
评测：`data/eval/questions.v1.jsonl`，19 道可回答题 + 1 道拒答题

## 实现

项目使用自实现的 Okapi BM25 和倒排索引，未依赖检索框架。索引文本由以下字段组成：

```text
title * 3 + section_path * 2 + content
```

初始参数：

```text
k1 = 1.5
b = 0.75
top_k = 5
```

BM25 单个查询词对文档的贡献为：

```text
IDF(q) * TF(q, d) * (k1 + 1)
-----------------------------------------------
TF(q, d) + k1 * (1 - b + b * doc_len / avg_len)
```

`k1` 控制词频饱和速度，`b` 控制文档长度归一化强度。当前参数是基线假设，还没有针对评测集调参。

## 结果

```text
Recall@5 = 11 / 19 = 57.89%
平均延迟 = 0.029 ms
P50 = 0.034 ms
P95 = 0.058 ms
```

分类 Recall@5：

| 分类 | Recall@5 |
|---|---:|
| latency | 50.0% |
| memory | 33.3% |
| persistence | 100.0% |
| replication | 0.0% |
| sentinel | 100.0% |
| cluster | 50.0% |
| security | 100.0% |

拒答题不计入 Recall。BM25 只返回证据，不负责判断最终是否拒答；拒答将在生成/证据阈值阶段单独评测。

## 失败分析

8 道题未命中：

1. `redis-002`、`redis-004`、`redis-006`：中文问题除被停用的 `Redis` 外没有英文词项，BM25 无候选；
2. `redis-007`：`hash` 被 Cluster 的 hash slot/hash tag 语义干扰，正确的内存优化章节排到第 5 名以外；
3. `redis-011`：中文“主从、同步、异步”无法与英文 replication 文本做词面匹配；
4. `redis-012`：只有 `replica/master` 等宽泛词，`REPLICAOF` 章节排在第 5 名以外；
5. `redis-013`：`master` 过于宽泛，结果被 failover、ROLE 和 Sentinel 内容占据；
6. `redis-017`：只有 `Cluster` 是有效英文查询词，无法定位 consistency guarantees。

使用英文查询 `replication asynchronous master replica synchronization` 时，标准章节
`Important facts about Redis replication` 排名第 1，说明索引能够在同语言精确词项下正常工作。

## 结论

BM25 对 Redis 命令、配置名和英文术语表现好，速度极快且容易解释；它无法独立解决中英文跨语言检索，也容易受 `hash`、`master` 等多义或宽泛词影响。

后续向量检索必须在完全相同的20题上运行。只有 Recall@5 和失败案例确实改善，才能证明它带来价值。混合检索还应保留 BM25 对命令名、配置名和错误码的精确匹配能力。

## 复现命令

```bash
./scripts/build_bm25.sh
./scripts/search_bm25.sh "LATENCY DOCTOR" 5
./scripts/evaluate_bm25.sh
```

完整逐题结果位于 `data/eval/results/bm25-v1.json`。
