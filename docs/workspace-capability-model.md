# Workspace Capability Model V4

V4 的能力模型由 Workspace 策略、Actor 权限、EndpointCapability 和 ToolRouter 共同决定。

## Workspace

Workspace 保存：

- `workspace_id`
- `base_mode`
- `prompt_overlay`
- `default_execution_target`
- `tool_policy`
- `allowed_tool_ids`
- `preferred_target_endpoint_ids`
- `preferred_endpoint_provider_types`
- `preferred_source_profiles`
- `tool_target_routing_policy`
- `memory_ranking_policy`

公开 mode 仅为 `general`、`automation`、`danxi`。

## EndpointCapability

Endpoint Provider 通过 `/endpoint/ws` 上报能力快照。能力描述执行能力，不描述权限。权限由 Actor、Workspace 和 RunPolicy 决定。

Capability/provider id 应面向 Endpoint，而不是旧 Client。

## ExecutionTarget

合法执行目标：

- `core.local`
- `endpoint`
- `workspace_any_endpoint`
- `prefer_endpoint_fallback_core`

`core.local` 是 Core 内进程执行目标。旧 `core_only`、`specific_agent`、`workspace_any_agent`、`specific_endpoint` 不再使用。

## ToolRouter

工具调用流程：

1. 根据 Run、Actor、Workspace、RunPolicy 判断权限。
2. 根据 tool key 和 Workspace 偏好解析 ExecutionTarget。
3. 选择 CoreToolExecutor、EndpointToolExecutor 或 ExternalToolExecutor。
4. 记录 Operation / OperationCall，仅在工具调用需要 Operation 时创建。

`assistant.progress_notice` 不走 ToolRouter，不创建 Operation。

## SKILL

Procedure 已删除。复杂或可复用 workflow 使用 SKILL：

- mode SKILL 描述 `general`、`automation`、`danxi` 的工作策略。
- reusable SKILL 描述跨模式 workflow。
- `list_skills` 支持按标题、摘要、场景和推荐工具匹配。
- `load_skill` 将 SKILL 内容作为运行时指导注入。
- `create_skill` 只创建 SKILL，不创建 Procedure。

## UI

UI 只展示工作区策略、当前 Thread / Run / Operation 状态、可用 Endpoint 和 SKILL 信息。UI 不提供 Procedure 目录、固定 Procedure 或 Procedure 编辑入口。
