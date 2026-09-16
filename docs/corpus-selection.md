# Redis 7.4 运维与工程实践语料选择规则

## 定位

该语料服务于 Redis 运维故障诊断，不是 Redis 官网的完整镜像。采用“主题路径白名单 + 产品路径排除 + 后续内容级版本检查”三层筛选。

语料中的 `source_type` 必须二选一：

- `official`：Redis Open Source 7.4 官方文档快照；
- `engineering_practice`：基于 Redis 官方工程文章或权威架构文档编写的内部审核摘要。

工程实践文档位于 `knowledge/engineering-practices/`，必须保留原始来源 URL、
审核日期和适用范围。它们不能被生成层宣称为 Redis 官方命令规范。

## 为什么使用白名单

`redis/docs` 同时包含 Redis Open Source、Redis Cloud、Redis Software、Kubernetes、客户端和营销内容。直接索引整个仓库会导致产品混淆、版本冲突和无关召回。

白名单位于 `config/corpus/redis-ops-7.4-v1.paths`，使用精确文件列表选择配置、安全、持久化、复制、Sentinel、Cluster、内存和诊断主题。命令只保留 `INFO`、`CONFIG`、ACL、Slow Log、Latency、Memory、Replication 和 Cluster 等诊断相关条目，不纳入完整命令目录。

## 为什么路径筛选仍不够

官方文档的 `main` 分支持续更新，页面可能同时讨论多个版本。因此路径白名单只决定候选文件，后续解析阶段仍需：

- 读取 front matter 和正文中的版本信息；
- 标记无法确认兼容 7.4 的页面；
- 排除明确仅适用于 Redis 8 的页面或段落；
- 将拒绝原因写入 `rejected-files.jsonl`；
- 对版本敏感的默认值，用 Redis 7.4 配置/命令参考交叉确认。

## 可复现与失败原子性

获取脚本先在 `.staging` 中生成快照并完成校验，成功后才替换当前语料。若网络、许可证、白名单或文件复制失败，旧快照保持不变。

第一次联网获取后，将生成的 `resolved_commit` 写入项目决策记录，并在日常复现时设置 `REDIS_DOCS_COMMIT`。未记录具体 commit 前，不能声称语料已经冻结。

## 人工审核点

首次获取后必须审核：

1. 每个白名单路径是否真实存在；
2. 被选文件是否混入 Cloud、Software、Kubernetes 或 Redis 8 专属内容；
3. `content/commands` 是否过大，是否需要缩小到明确命令集合；
4. 许可证文件与仓库来源是否记录完整；
5. 抽样页面能否定位到 redis.io 的公开页面。

## 解析、清洗与切块

运行：

```bash
./scripts/build_corpus.sh
```

处理器读取快照 Manifest 校验输入文件数，解析 Markdown front matter，删除 Redis
Software/Cloud 兼容性附录和推广段落、明确标注为 Redis 8 新增的内容块，以及人工审核确认与
运维诊断无关的 CRC16 源码附录，随后按标题层级、段落和代码块切分。
代码块不会从中间截断；超长普通段落会按句子二次切分。

当前的 `approx_tokens` 是与模型无关的稳定近似值，用于 P0-1 控制切块规模。P0-2 选定 embedding
模型后，应使用该模型 tokenizer 复核，并把 chunk size 作为评测参数，而不是把 450 当作永远正确的常量。

产物：

- `data/processed/chunks.jsonl`：用于建立索引的 chunk 和完整 metadata；
- `data/processed/corpus-stats.json`：输入、输出和清洗统计；
- `data/processed/rejected-files.jsonl`：清洗后为空的拒绝文档；
- `data/processed/review-sample.jsonl`：固定抽取的 20 个待人工审核 chunk。
