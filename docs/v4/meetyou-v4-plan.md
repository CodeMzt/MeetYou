# MeetYou V4 重构计划

> 本计划用于指导 Codex / 本地开发者一口气完成 V4 大重构。项目处于开发期，V4 不做 V3 协议兼容。所有阶段完成后必须进行本地基础测试、真实本地测试、推送 main 后 GitHub Actions CI + Deploy 测试、远程 Core + 本地 Desktop 真实测试，最后再做 Feishu 和 WeChatBot 人类反馈测试。

---

## V4 不可违反原则

1. Core owns Thread / Message / Run / Scheduler / Heartbeat / Memory / Operation / Delivery。
2. Client is only Endpoint Provider。
3. Core is not Client；`core.local` 是 in-process `ExecutionTarget`，不是 Client。
4. Scheduler 是唯一系统级调度时钟。
5. `system.heartbeat` 是 Scheduler 内不可删除、可启停、可修改间隔的系统预设 Job。
6. `endpoint.heartbeat` 只是连接保活，不触发 `system.heartbeat`。
7. `short_reply` 不再作为 directed tool；替换为 `assistant.progress_notice` RunEvent / Runtime Action。
8. Delivery 负责投递 `message` / `run_event` / `notice` / `operation_update`，不负责生成回复。
9. Final assistant reply 必须是 MessageService 持久化的 assistant message。
10. Streaming 必须走 RunEventLog + Delivery fan-out。
11. Tool 调度必须走 ToolRouter + ExecutionTarget。
12. 权限挂在 Actor / Workspace / RunPolicy；执行能力挂在 EndpointCapability。
13. 不保留 `/client/ws`、`source_client_id`、`target_client_id`、`ClientToolDispatchService` 兼容路径。

---

## 0. 总要求

### 0.1 不可违反的 V4 原则

1. Core owns Thread / Message / Run / Scheduler / Heartbeat / Memory / Operation / Delivery。
2. Client 不再是调度主体，只是 Endpoint Provider。
3. Endpoint 是可寻址输入、输出、执行目标；Core 也可以注册 in-process endpoint，如 `core.local`，但 Core 不是 Client。
4. Scheduler 是唯一调度时钟；system heartbeat 是 Scheduler 中不可删除、可启停、可改间隔的系统 Job。
5. `endpoint.heartbeat` 只表示连接保活，不等于 system heartbeat。
6. `short_reply` 不再作为 directed tool；替换为 `assistant.progress_notice` RunEvent / Runtime Action。
7. Delivery 负责投递 message / run_event / notice / operation_update，不负责生成回复。
8. Final assistant reply 必须是 MessageService 持久化的 assistant message。
9. Streaming 必须走 RunEventLog + Delivery fan-out。
10. Tool 调度必须先解析 ExecutionTarget，再由 Core / Endpoint / External executor 执行。
11. 权限挂在 Actor / Workspace / RunPolicy；执行能力挂在 EndpointCapabilities。
12. 不保留 `/client/ws`、`source_client_id`、`target_client_id`、`ClientToolDispatchService` 兼容路径。

### 0.2 必须更新 AGENT.md / AGENTS.md

在真正改代码前，必须先搜索并更新：

```bash
find . -maxdepth 3 \( -name 'AGENT.md' -o -name 'AGENTS.md' \) -print
```

要求：

- 如果已有 `AGENT.md`，在其中新增 V4 Architecture Rules。
- 如果已有 `AGENTS.md`，也同步新增同样规则，避免 Codex 读取不到。
- 如果都没有，创建根目录 `AGENT.md`，并建议同时创建简短 `AGENTS.md` 指向它。
- 更新内容必须包括：V4 核心原则、禁止兼容、测试阶梯、真实测试要求、Feishu / WeChatBot 最后测试且必须通过人类提问工具确认。

### 0.3 不能停的要求

Codex / 开发者不能在以下节点停止：

```text
单元测试通过
本地集成测试通过
本地 Core 能启动
本地 Desktop 能连接
代码已经 push
CI 通过但 Deploy 未通过
Deploy 通过但未做真实 Desktop 远程连接
Feishu / WeChatBot 凭证缺失但未向人类提问
外部消息无法自行确认但未使用人类提问工具
```

必须持续推进到：

```text
本地基础测试通过
真实本地 Core + Desktop 测试通过
提交、推送、合并 main
GitHub Actions CI 通过
GitHub Actions Deploy 通过
确认远程 Core 已更新
拉起本地 Desktop 连接远程 Core 做真实测试
最后做 Feishu / WeChatBot 真实投递测试
通过提问工具向人类确认收到消息
记录测试结果
```

如果遇到凭证、远程服务、外部消息确认等需要人类输入的问题，必须使用环境中的人类提问工具提问，收到反馈后继续执行。

---

## 1. Feature / Phase 总览

| Phase | Feature | 目标 | 必须产物 | 基础测试 | 真实测试 |
|---|---|---|---|---|---|
| 0 | AGENT / Docs / Ground Rules | 先对齐开发规则 | AGENT.md、docs/v4 | grep + 文档检查 | N/A |
| 1 | Domain Schema | Actor / Endpoint / Run / RunEvent / Scheduler 数据模型 | Alembic migration、ORM、service skeleton | migration test | 本地 DB 迁移启动 |
| 2 | Endpoint Protocol | 替换 `/client/ws` 为 `/endpoint/ws` | gateway、protocol schemas、connection service | ws unit/integration | Desktop / Edge 真实连接 |
| 3 | Run / Message / Delivery / Streaming | Core-owned conversation 和流式事件 | RunService、MessageService、RunEventService、DeliveryService | streaming tests | UI 真实流式显示 |
| 4 | ToolRouter / ExecutionTarget | 替换 ClientToolDispatchService | ToolRouter、ExecutionTargetResolver、executors | tool routing tests | file/shell/core tool 真实执行 |
| 5 | Scheduler / Heartbeat | Scheduler 统一 heartbeat 和用户定时任务 | scheduled_jobs、JobRun、HeartbeatWorkflow | scheduler tests | 修改间隔、启停、触发真实 run |
| 6 | Desktop / Edge / UI | Client 改为 Endpoint Provider | desktop_client、edge_client、meetyou-ui 更新 | client tests | 本地 Desktop 连接本地/远程 Core |
| 7 | External Delivery | Feishu / WeChatBot / inbox | external endpoints、delivery adapters | adapter dry-run | 最后真实投递 + 人类确认 |
| 8 | Cleanup / Docs / CI | 删除旧概念，完善文档和 CI | 删除 V3 残留、README、tests | full test suite | GitHub Actions CI + Deploy |
| 9 | End-to-End Reality | 远程 Core + 本地 Desktop 全面真实测试 | 测试报告 | N/A | 必须通过 |

---

## 2. Phase 0：AGENT / Docs / Ground Rules

### 2.1 实现任务

1. 搜索 `AGENT.md`、`AGENTS.md`。
2. 写入 V4 Architecture Rules。
3. 创建 `docs/v4/`：
   - `docs/v4/design.md`
   - `docs/v4/plan.md`
   - `docs/v4/plans/*.md`
4. 更新 README 中的架构摘要。
5. 删除或标注 V3 docs 为 legacy，不允许继续作为实现真源。

### 2.2 测试要求

```bash
grep -R "Core owns Thread" AGENT.md AGENTS.md docs/v4 README.md || true
grep -R "/client/ws\|source_client_id\|target_client_id\|ClientToolDispatchService" docs/v4 AGENT.md AGENTS.md README.md || true
```

第二条不是要求完全无输出，因为文档可能在“删除清单”里提到旧名；但不能把旧名作为新实现方案使用。

---

## 3. Phase 1：Domain Schema

### 3.1 新增 / 重构对象

```text
Actor
Endpoint
EndpointConnection
EndpointCapability
Thread
Message
Run
RunEvent
ScheduledJob
ScheduledJobRun
Operation
OperationCall
EndpointOutbox
DeliveryAttempt
```

### 3.2 Alembic 迁移要求

1. 创建新表。
2. 保留已有 workspace / thread / message 数据，除非人类明确同意清库。
3. 迁移已有 Client 为 Endpoint Provider：
   - desktop client -> `desktop.<client_id>.ui`、`desktop.<client_id>.executor`、`desktop.<client_id>.notifier`
   - edge client -> `edge.<client_id>.executor`
4. 迁移已有 tool capability 到 endpoint_capabilities。
5. 新增 system actors：
   - `system.scheduler`
   - `system.heartbeat`
   - `system.maintenance`
6. 新增 core endpoints：
   - `core.local`
   - `core.scheduler`
   - `core.inbox`
   - `core.notification`
7. 新增 `system.heartbeat` scheduled job。

### 3.3 测试要求

- migration up/down 或至少 migration up + DB smoke。
- ORM create/list/update。
- bootstrap 幂等：重复启动不能重复创建 system heartbeat。
- 旧数据迁移 smoke。

---

## 4. Phase 2：Endpoint Protocol

### 4.1 新协议

入口：

```text
GET /endpoint/ws
protocol = meetyou.endpoint.ws.v4
```

生命周期：

```text
endpoint.hello
endpoint.capabilities.snapshot
endpoint.ready
endpoint.heartbeat
endpoint.goodbye
```

订阅：

```text
subscription.start
subscription.update
subscription.stop
```

投递：

```text
delivery.message
delivery.run_event
delivery.notice
delivery.operation_update
```

工具：

```text
tool.call.request
tool.call.result
tool.call.error
tool.call.cancel
```

### 4.2 删除旧协议

删除或替换：

```text
/client/ws
meetyou.client.ws.v1
client.hello
client.ready
client.heartbeat
client.tools.snapshot
```

### 4.3 测试要求

- endpoint ws connect。
- heartbeat 更新 endpoint_connection last_seen。
- capabilities snapshot 更新 endpoint_capabilities。
- subscription 能收到 thread/run events。
- 旧 `/client/ws` 不存在或明确返回 410 / 404。

---

## 5. Phase 3：Run / Message / Delivery / Streaming

### 5.1 实现任务

1. MessageService 管理 Thread 持久化消息。
2. RunService 创建 / 执行 / 取消 / 重试 Run。
3. RunEventService 维护 seq、durable events、replay。
4. DeliveryService 根据 DeliveryPolicy 投递。
5. EndpointOutbox 支持离线投递。
6. Streaming 通过 `message.delta` RunEvent 实现。
7. Final assistant reply 通过 MessageService 持久化。
8. `assistant.progress_notice` 替代 `short_reply`。

### 5.2 short_reply 处理要求

必须删除 directed tool 版 `short_reply`。

新增 runtime action：

```text
emit_progress_notice(text, severity="info", ttl_seconds=60)
```

它只做：

```text
RunEventService.append(type="assistant.progress_notice", durable=false)
DeliveryService.publish(event)
```

禁止：

```text
emit_progress_notice -> ToolRouter -> OperationCall
```

### 5.3 测试要求

- message.delta 能推给在线 endpoint。
- final message 会持久化。
- reconnect 能 replay durable events 或返回 final snapshot。
- progress_notice 不进入 messages final content。
- progress_notice 不创建 Operation / OperationCall。
- DeliveryPolicy 无 origin_endpoint 时不投递给 `core.scheduler`。

---

## 6. Phase 4：ToolRouter / ExecutionTarget

### 6.1 实现任务

1. 删除 `ClientToolDispatchService` 主链。
2. 新增：
   - `ToolRouterService`
   - `CapabilityResolver`
   - `ExecutionTargetResolver`
   - `CoreToolExecutor`
   - `EndpointToolExecutor`
   - `ExternalToolExecutor`
3. 权限检查从 Client 迁移到 Actor / Workspace / RunPolicy。
4. 执行能力从 Client 迁移到 EndpointCapability。
5. OperationCall 写 `target_endpoint_id` / `execution_target_id`。
6. 支持 fixed endpoint 和 selector。
7. 支持 offline policy。

### 6.2 测试要求

- core.local tool in-process 执行。
- desktop executor tool 通过 WS 执行。
- offline endpoint 根据 policy 进入 waiting_for_endpoint 或失败。
- approval_required 能拦截高风险工具。
- source_client_id / target_client_id 不再出现在新服务接口。

---

## 7. Phase 5：Scheduler / Heartbeat

### 7.1 实现任务

1. SchedulerService 管理 scheduled_jobs。
2. JobRunService 管理 scheduled_job_runs。
3. system.heartbeat bootstrap。
4. HeartbeatWorkflow 实现系统检查。
5. 用户定时任务 CRUD。
6. concurrency / misfire 策略。
7. manual trigger 支持。

### 7.2 system.heartbeat 规则

```text
不可删除
可 enable / disable
可修改 interval
可修改 delivery_policy
可修改部分 execution limits
必须通过 Scheduler 触发
必须创建 JobRun + Run
```

### 7.3 测试要求

- heartbeat job bootstrap 幂等。
- 删除 heartbeat 返回错误。
- 修改 interval 生效。
- disable 后不触发。
- enable 后恢复触发。
- heartbeat run actor = system.heartbeat。
- user job 可创建、编辑、删除。

---

## 8. Phase 6：Desktop / Edge / UI

### 8.1 Desktop

Desktop Provider 暴露：

```text
desktop.<id>.ui
desktop.<id>.executor
desktop.<id>.notifier
```

Desktop 后端连接 `/endpoint/ws`，发送 endpoint frames。

### 8.2 Edge

Edge Provider 暴露：

```text
edge.<id>.executor
edge.<id>.notifier optional
```

### 8.3 UI

UI 不再创建 client-bound session。UI 应：

```text
list workspaces
list/create threads
subscribe thread events
send user message
render message.delta
render assistant.progress_notice separately
render final assistant message
render operation updates
```

### 8.4 测试要求

- Desktop 能连接本地 Core。
- Desktop 能连接远程 Core。
- 下线重连后继续 Thread。
- 本地 file/shell 工具真实执行。
- Streaming UI 正常。
- progress_notice 显示但不进入最终消息。

---

## 9. Phase 7：External Delivery：Feishu / WeChatBot

### 9.1 实现任务

1. Feishu 和 WeChatBot 都作为 external endpoint。
2. DeliveryService 通过 ExternalToolExecutor / Adapter 投递。
3. 配置从 user config / env 加载。
4. 支持 dry-run，但 dry-run 不能替代最终真实测试。

### 9.2 测试顺序

Feishu 和 WeChatBot 放在最后测试。

原因：

- 它们依赖外部凭证和真实人类确认。
- 它们不应该阻塞核心架构重构的基础验证。
- 但最终上线验收必须真实投递成功。

### 9.3 人类提问工具要求

测试时发送唯一标识消息：

```text
[V4-REAL-TEST <timestamp> <random_suffix>] Feishu delivery test
[V4-REAL-TEST <timestamp> <random_suffix>] WeChatBot delivery test
```

发送后必须使用人类提问工具询问：

```text
我刚才发送了一条 Feishu 测试消息，内容包含 “[V4-REAL-TEST ...]”。请确认你是否收到，并把收到的完整文本或截图中的唯一标识回复给我。
```

WeChatBot 同理。

不能自行假设收到。

---

## 10. Phase 8：Cleanup / Docs / CI

### 10.1 删除旧名

必须搜索并处理：

```bash
grep -R "ClientToolDispatchService\|source_client_id\|target_client_id\|/client/ws\|short_reply" . \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules
```

允许出现在：

```text
docs/v4 删除清单
legacy migration 注释
测试中确认旧入口已删除
```

不允许出现在：

```text
新服务接口
新协议 schema
新运行时主链
prompt 中作为回复工具
工具 registry 中作为 directed tool
```

### 10.2 CI 要求

CI 至少覆盖：

```text
Python unit tests
Python integration tests
Alembic migration smoke
Endpoint WS tests
Scheduler tests
ToolRouter tests
Delivery tests
Desktop client protocol tests
UI build / typecheck
```

---

## 11. Phase 9：真实测试与上线验证

### 11.1 本地基础测试

必须运行：

```bash
python -m pytest
python -m pytest tests -q
```

如有前端：

```bash
npm test
npm run typecheck
npm run build
```

以仓库实际脚本为准，不存在的脚本要补充或记录。

### 11.2 本地真实测试

必须真实启动：

```text
local Core
local Desktop backend
local UI
optional local Edge
```

测试：

```text
创建 Thread
发送用户消息
Streaming 回复
progress_notice
Core tool
Desktop file/shell tool
Scheduler user job
system.heartbeat enable/disable/interval
Desktop disconnect/reconnect continue Thread
```

### 11.3 推送、合并、GitHub Actions

基础测试和本地真实测试完成后：

```text
提交 commit
推送 branch
合并到 main
等待 GitHub Actions CI 和 Deploy
CI 必须通过
Deploy 必须通过
```

Deploy 通过后，说明远程 Core 已成功更新代码。

### 11.4 远程 Core + 本地 Desktop 真实测试

Deploy 通过后必须：

```text
确认远程 /health
确认远程版本 / build sha
拉起本地 Desktop 指向远程 Core
做真实对话
做真实 streaming
做真实工具调用
做真实 scheduler / heartbeat
做断线重连
```

### 11.5 Feishu / WeChatBot 最后测试

最后执行：

```text
Feishu 真实发送
人类提问工具确认收到
WeChatBot 真实发送
人类提问工具确认收到
记录反馈
```

### 11.6 不能停止条件

如果 CI 失败：修复并继续。

如果 Deploy 失败：查看日志、修复并继续。

如果远程 Core 健康检查失败：修复部署并继续。

如果 Desktop 连不上远程 Core：修复协议 / 配置 / token 并继续。

如果 Feishu / WeChatBot 凭证缺失：使用人类提问工具索取或要求确认跳过该项，不能直接结束。

---

## 12. 最终验收清单

- [x] AGENT.md / AGENTS.md 已更新 V4 规则。
- [x] docs/v4 已成为实现真源。
- [x] `/endpoint/ws` 正常。
- [x] `/client/ws` 删除或明确不可用。
- [x] Actor / Endpoint / Run / RunEvent / Scheduler schema 完成。
- [x] Thread 不依赖 Client。
- [x] Client 下线重连继续 Thread。
- [x] Run 支持 user_message / scheduled_job / system_heartbeat。
- [x] system.heartbeat 是不可删除 scheduled job。
- [x] 用户定时任务 CRUD 完成。
- [x] ToolRouter 基于 ExecutionTarget。
- [x] Core tool 走 core.local。
- [x] Desktop / Edge tool 走 endpoint executor。
- [x] Delivery 统一投递 message / run_event / notice。
- [x] Streaming 正常。
- [x] `short_reply` 不再作为 directed tool。
- [x] `assistant.progress_notice` 正常显示。
- [x] 本地基础测试通过。
- [x] 本地真实测试通过。
- [ ] 代码提交、推送、合并 main。
- [ ] GitHub Actions CI 通过。
- [ ] GitHub Actions Deploy 通过。
- [ ] 远程 Core 已更新并健康。
- [ ] 本地 Desktop 连接远程 Core 真实测试通过。
- [ ] Feishu 真实测试通过且人类确认。
- [ ] WeChatBot 真实测试通过且人类确认。
- [ ] 测试报告写入 docs/v4 或 PR description。
## 13. Current Implementation Status

- Completed locally on 2026-04-29: V4 domain schema/migration/bootstrap, `/endpoint/ws`, `/runtime/*`, Thread / Message / RunEvent / Delivery fan-out, `assistant.progress_notice`, ToolRouter + ExecutionTarget, Scheduler-owned `system.heartbeat`, Desktop Provider routing, UI runtime API rename, SKILL-first workflow layer, and Procedure removal.
- Completed locally on 2026-04-29: Python full discovery, frontend typecheck/test/build, migration/protocol/scheduler/tool-router/delivery coverage, and local Core + Desktop + UI real acceptance with real Desktop Provider `utility.echo`.
- Pending after this local batch: commit/push to `main`, GitHub Actions CI and Deploy, remote Core `/health` + commit verification, local Desktop -> remote Core real acceptance, and Feishu / WeChatBot human confirmation.
