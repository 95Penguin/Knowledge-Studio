# P0-4 受控 Agent

## 设计原则

Agent 不采用“模型想调什么就调什么”的循环。模型只用于基于证据生成知识回答；
设备和工单流程由显式状态机控制，并且由 Java 服务执行最终权限与业务校验。

```text
NEW
 -> WAITING_FEEDBACK
 -> WAITING_DEVICE_AUTHORIZATION
 -> WAITING_DEVICE_FEEDBACK
 -> WAITING_TICKET_CONFIRMATION
 -> TICKET_CREATED

任意无法继续的已登录状态 -> TRANSFERRED
```

## 安全约束

- Agent 会话绑定 Java Bearer Token 的 SHA-256 指纹，不保存指纹以外的派生身份。
- 不允许换用户继续同一会话。
- 设备工具只在用户点击授权后执行。
- 工单工具只在用户看到草稿并点击确认后执行。
- 敏感工具重复调用会被拒绝；工单同时使用稳定幂等键。
- 最大 12 步，超限后停止自动处理并转人工。
- Java HTTP 超时默认 5 秒，传输失败最多尝试 2 次。
- Pydantic `Literal` 限定 action 白名单，未知工具和错误格式在入口处失败。

## 接口

```text
POST /api/agent/turn
```

action 只能为 `ask`、`resolved`、`unresolved`、`authorize_device`、
`confirm_ticket` 或 `transfer`。响应会返回当前状态、下一个必要操作、引用、
脱敏设备、工单草稿和可观测工具事件。
