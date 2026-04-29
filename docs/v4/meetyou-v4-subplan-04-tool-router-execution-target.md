# V4 细分计划 04：ToolRouter / ExecutionTarget / Operation

## 目标

用 ToolRouter + ExecutionTarget 替换 V3 的 ClientToolDispatchService。工具调用不再从 source_client 到 target_client，而是从 Run / Actor / Workspace policy 解析到 ExecutionTarget。

---

## 新主链

```text
Run step needs tool_key
  -> Actor / Workspace / RunPolicy permission check
  -> CapabilityResolver
  -> ExecutionTargetResolver
  -> ApprovalService if needed
  -> OperationService creates Operation
  -> OperationCallService creates OperationCall
  -> Executor dispatches
  -> Result returns
  -> OperationCall updated
  -> RunEvent emitted
  -> Run continues
```

---

## 服务

新增：

```text
ToolRouterService
CapabilityResolver
ExecutionTargetResolver
CoreToolExecutor
EndpointToolExecutor
ExternalToolExecutor
ToolPolicyService
```

删除或重写：

```text
ClientToolDispatchService
resolve_specific_tool(client_id=...)
dispatch_directed_tool(source_client_id=..., target_client_id=...)
dispatch_workspace_tool based on client
```

---

## 权限设计

V4 不再使用 `Client.available_tools` 表示请求方权限。

改为：

```text
ActorPermissionProfile
WorkspacePolicy
RunPolicy
```

检查顺序：

```text
1. actor can start run/tool?
2. workspace allows tool_key?
3. run_policy allows tool_key?
4. capability exists?
5. execution target is allowed?
6. approval required?
7. credentials allowed?
```

---

## 能力设计

V4 不再使用 `Client.executable_tools` 表示目标执行能力。

改为：

```text
EndpointCapability
```

字段：

```text
endpoint_id
tool_key
schema
risk_level
requires_confirmation
enabled
constraints
```

---

## ExecutionTarget 类型

```text
core.local
endpoint:<endpoint_id>
external:<adapter_id>
```

Executor：

```text
core.local       -> CoreToolExecutor, in-process
endpoint         -> EndpointToolExecutor, websocket
external         -> ExternalToolExecutor, adapter/http
```

---

## Target selector

固定 endpoint：

```json
{
  "endpoint_id": "desktop.home.executor"
}
```

Selector：

```json
{
  "selector": {
    "workspace_id": "personal",
    "capability": "shell.exec",
    "endpoint_type": "desktop_executor",
    "labels": ["trusted"],
    "online_required": true,
    "priority": ["desktop.home.executor", "edge.server01.executor"]
  }
}
```

---

## Offline policy

```text
fail_fast
queue_until_online
store_in_outbox
fallback_to_core
manual_retry
```

后台 run 允许：

```text
waiting_for_endpoint
```

用户交互 run 默认可以更快反馈：

```text
fail_fast or ask_user
```

---

## Operation 记录

Operation：

```text
operation_id
run_id
thread_id nullable
workspace_id
operation_type
requested_by_actor_id
execution_target_type
execution_target_id
status
metadata
```

OperationCall：

```text
call_id
operation_id
capability_id
target_endpoint_id nullable
execution_target_id
status
arguments
result
error
```

---

## 测试

### Core tool

- `memory.query` / `summarize` / `web.search` 可解析到 `core.local`。
- 不经过 websocket。
- OperationCall target = core.local。

### Endpoint tool

- `file.read` 可解析到 desktop executor。
- endpoint 在线时发 `tool.call.request`。
- result 更新 OperationCall。

### External tool

- Feishu / WeChatBot dry-run adapter 可解析。
- 真实测试放最后。

### Policy

- Actor 不允许时拒绝。
- Workspace 不允许时拒绝。
- 高风险工具进入 approval。
- endpoint 离线按 policy 处理。

### 删除旧接口

```bash
grep -R "ClientToolDispatchService\|source_client_id\|target_client_id" core gateway desktop_client edge_client tests \
  --exclude-dir=.git --exclude-dir=.venv || true
```

允许只出现在 migration legacy 注释或 V4 删除测试中。

---

## 真实测试

1. 本地 Core + Desktop。
2. 用户在 UI 发起“读取一个允许目录内的测试文件”。
3. ToolRouter 选择 desktop executor。
4. Desktop 返回文件内容。
5. Run 继续生成最终回复。
6. 断开 Desktop，再触发必须 Desktop 执行的工具，确认进入 waiting_for_endpoint 或合理失败。
7. 重新连接 Desktop，确认 queued call 可继续或手动 retry。

---

## 验收

- [x] ClientToolDispatchService 不再是主链。
- [x] ToolRouterService 完成。
- [x] ExecutionTargetResolver 完成。
- [x] core.local 可执行 core tool。
- [x] endpoint executor 可执行 desktop / edge tool。
- [x] Operation/OperationCall 记录 endpoint / execution target。
- [x] source_client_id / target_client_id 不出现在新运行时接口。
