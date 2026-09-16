# 多语言向量检索模型对比 v1

实验日期：2026-08-15  
语料：`redis-ops-7.4-v1`，420 chunks  
评测：与 BM25 完全相同的19道可回答题，另有1道拒答题不计入 Recall

## 模型与实现

- 候选1：`intfloat/multilingual-e5-small`，固定 revision
  `d1d99a1efae6779390caba937d92c54b5bc70e51`，384维；
- 候选2：`intfloat/multilingual-e5-base`，固定 revision
  `b1a0e29a27225d956284aec11899fc85b0fe3ad8`，768维；
- 运行设备：CPU；
- 文档输入：`passage: title + section_path + content`；
- 查询输入：`query: 用户问题`；
- 向量：L2 归一化；
- 相似度：归一化向量点积，等价于余弦相似度；
- 索引：420条数据直接精确扫描，不使用近似近邻索引。

当前语料很小，精确扫描更加透明，并且不会引入 ANN 召回误差。语料达到更大规模后再比较 FAISS 或向量数据库。

## 结果

| 方案 | Recall@5 | 命中数 | P50 | P95 |
|---|---:|---:|---:|---:|
| BM25 | 57.89% | 11/19 | 0.034 ms | 0.058 ms |
| multilingual-e5-small | 68.42% | 13/19 | 9.509 ms | 11.417 ms |
| multilingual-e5-base | 78.95% | 15/19 | 21.256 ms | 24.658 ms |

向量检索相对 BM25 提升 10.53 个百分点，代价是更高的查询编码延迟。

分类对比：

| 分类 | BM25 | E5-small | E5-base |
|---|---:|---:|---:|
| latency | 50.0% | 75.0% | 100.0% |
| memory | 33.3% | 0.0% | 33.3% |
| persistence | 100.0% | 100.0% | 100.0% |
| replication | 0.0% | 66.7% | 33.3% |
| sentinel | 100.0% | 100.0% | 100.0% |
| cluster | 50.0% | 50.0% | 100.0% |
| security | 100.0% | 100.0% | 100.0% |

## 互补性

向量检索新增命中：

- 中文延迟排查清单；
- 中文主从异步复制问题；
- 关闭持久化的 master 自动重启风险。

E5-base 相比 small 又找回了 `LATENCY DOCTOR`、`MEMORY DOCTOR` 和 Cluster consistency
等标准证据，但在 replication 分类低于 small。综合 Recall@5 与本机延迟，项目默认使用 E5-base，
同时保留 small 结果作为选型对照。这也说明向量检索不能替代关键词检索：前者擅长跨语言语义，
后者擅长命令和配置名。

## 失败与标注风险

向量检索未命中6题。其中部分 Top 5 是主题相关但不等于 v1 标准章节，例如：

- `MEMORY USAGE > Examples` 接近标准命令章节；
- Cluster `Write safety` 可能包含与一致性问题有关的证据；
- 多个 memory optimization 章节与 hash 节省内存有关。

当前不根据模型输出反向修改 v1 标签，以避免为了提高分数而移动评测标准。扩充到80～100题时，应独立审核“必要证据”和“可替代证据”，并明确 any-of 与 all-of 关系。

## 复现

首次构建会下载依赖和固定模型：

```bash
./scripts/build_dense.sh
./scripts/search_dense.sh "Redis 延迟突然升高应该怎样排查" 5
./scripts/evaluate_dense.sh
```

完整结果分别位于：

- `data/eval/results/dense-multilingual-e5-small-v1.json`；
- `data/eval/results/dense-multilingual-e5-base-v1.json`。
