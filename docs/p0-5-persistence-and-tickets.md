# P0-5：工单闭环、会话持久化与 Compose

## 工单详情

`GET /api/tickets/{id}` 只允许工单所属用户访问，返回：

- 工单标题、描述、优先级、当前状态和设备名称；
- 按时间正序排列的状态历史；
- 由后端状态机计算的 `allowedTransitions`。

状态机为：

```text
OPEN -> IN_PROGRESS -> RESOLVED -> CLOSED
                         |
                         +-> IN_PROGRESS
```

前端不自行猜测下一状态，只渲染 `allowedTransitions`。后端仍会再次校验，
所以跳级、重复关闭或访问他人工单都会被拒绝。

## Agent 会话持久化

AI 服务使用 SQLite 保存每次状态变化，包括：

- 会话 ID、当前状态和步数；
- 登录 token 的 SHA-256 指纹（不保存原 token）；
- 原始问题、已授权设备、工单草稿；
- 工具事件和最近敏感调用签名。

进程重启后，客户端提交原 `conversation_id` 便可继续。身份指纹不匹配时仍会拒绝恢复。

## Compose 数据边界

- PostgreSQL 卷：用户、设备、工单、历史、审计和转人工记录。
- Agent SQLite 卷：AI 状态流会话。
- Hugging Face 卷：E5 和 reranker 模型缓存。

Compose 不包含 Qdrant，因为当前向量索引仍是可复现的本地 JSON 快照，引入未使用的中间件只会增加运维面。
