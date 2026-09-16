# ADR-0002：使用 Redis Open Source 7.4 官方英文文档

## 状态

已接受。语料文件尚未下载，下载后必须补充源码仓库 commit。

## 决策

第一版知识库只使用 **Redis Open Source 7.4 官方英文文档**，不混入 Redis 8、Redis Cloud 或 Redis Software（企业版）文档。

文档范围优先覆盖：

- 安装、启动和配置；
- 网络访问、protected mode、TLS 和 ACL；
- 数据持久化；
- 内存管理与淘汰；
- replication、Sentinel 和 Cluster；
- 常见运维和故障排查；
- 与上述主题直接相关的命令说明。

## 原因

- 7.4 有明确的官方命令参考和配置文件版本，适合固定评测口径；
- 内容足以构造网络、权限、持久化、高可用等技术支持问题；
- 相比不断变化的 `latest` 页面，固定版本更容易保证引用和评测可复现；
- 首期单领域、单版本可以减少版本冲突和检索噪声。

## 数据冻结规则

1. 后续从 Redis 官方文档源码仓库获取对应语料；
2. 在 `data/raw/CORPUS_MANIFEST.md` 记录仓库地址、commit、许可证、获取日期和文件清单；
3. 评测期间不得静默更新文档；如更新，创建新的 corpus version 并重新运行全部评测；
4. 页面中的“Redis Software”“Redis Cloud”和 Redis 8 内容不得混入首版语料；
5. 引用必须包含文档路径、标题层级和语料版本。

## 已确认的官方入口

- Redis Open Source 文档：https://redis.io/docs/latest/get-started/
- Redis 7.4 命令参考：https://redis.io/docs/latest/commands/redis-7-4-commands/
- Redis 配置文档（包含 7.4 配置入口）：https://redis.io/docs/latest/operate/oss_and_stack/management/config/

