# P0-3 Java 业务闭环

## 边界

Java 服务是用户、设备、工单、权限和审计的唯一执行入口。AI 只能提出
`query_device` 或 `create_ticket` 意图，不能指定另一个用户或绕过确认。

## 本地数据与登录

默认使用 H2 文件库（PostgreSQL 兼容模式），位于 `backend/data/`。启动时会创建
本地演示用户和一台归属设备：

```text
email: demo@supportpilot.dev
password: demo1234
```

密码使用 BCrypt 哈希存储。登录返回 12 小时 Bearer Token；P0 为单实例内存会话，
服务重启后需重新登录。

## API

```text
POST  /api/auth/login
GET   /api/devices
GET   /api/devices/{id}
POST  /api/tickets
GET   /api/tickets
GET   /api/tickets/{id}
PATCH /api/tickets/{id}/status
```

除登录和健康检查外，请求携带 `Authorization: Bearer <token>`。敏感工具请求可携带
`X-Request-Id`，未携带时由服务端生成。

## 业务保证

- 设备查询使用登录用户与 `user_device` 联合查询，越权时不泄露设备是否存在。
- 序列号只显示末四位，内网 IP 只显示第一段和最后一段。
- 创建工单必须 `confirmed=true`，并重新校验设备归属。
- `user_id + idempotency_key` 唯一，重放返回原工单。
- 状态机：`OPEN -> IN_PROGRESS -> RESOLVED -> CLOSED`，`RESOLVED` 允许重新打开到 `IN_PROGRESS`。
- 设备查询和工单创建的成功、拒绝和幂等重放都记录到 `tool_audit_log`。

## 验证

```bash
cd backend
mvn test
mvn spring-boot:run
```

集成测试覆盖登录失败、缺少身份、设备越权、脱敏、未确认创建、幂等重放、
非法状态流转、正常流转、历史与审计记录。
