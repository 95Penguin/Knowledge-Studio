---
title: "Cache-Aside 与缓存一致性实践"
source_type: engineering_practice
document_type: practice
source_url: "https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside"
reviewed_at: "2026-08-18"
---

# Cache-Aside 读路径

Cache-Aside 由应用负责缓存与主数据源之间的协调。读取时先查缓存；命中则直接返回；未命中则查询主数据源，
将结果写入缓存并设置合理 TTL，然后返回。缓存不应被当作唯一的持久化数据源。

# 写路径与失效

常见做法是先成功更新主数据源，再删除或使对应缓存失效。
如果先删缓存、后更新数据库，中间窗口中的并发读请求可能把旧数据重新写回缓存。

Cache-Aside 通常只提供最终一致性，不自动保证强一致。对 read-after-write 有严格要求的路径，
需要评估是否绕过缓存、使用 write-through，或通过版本号和事件机制进行协调。

# TTL 和预热

TTL 过短会导致频繁回源，TTL 过长则增加返回过期数据的时间。应根据数据变更频率、可容忍的过期时间、回源成本和访问热度分类设置。
大批数据不应使用完全相同的过期时刻；可以增加随机抖动。确定会在启动后被集中访问的核心数据可以提前预热。

# 监控与容量

应同时监控命中率、回源次数、回源延迟、Key 过期和驱逐数量、热点 Key、Redis 内存以及下游数据库的负载。
命中率下降只是信号，还要结合请求量与回源成本判断影响。

# 来源与适用范围

本文为 SupportPilot 对 Microsoft Azure Architecture Center Cache-Aside Pattern 与 Redis Cache-Aside 用例的工程化摘要。
实际系统还需结合业务一致性要求、并发规模和故障模式做压测与演练。
