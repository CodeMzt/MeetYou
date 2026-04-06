# 前端回复控制与检查点功能集成计划

## Summary
将后端的“回复时打断”、“回复时追加引导”、“重新回复”与“检查点回退”能力对齐到前端，通过统一 WebSocket 协议实现交互。设计上保持与原前端风格严格一致，注重轻量和优雅，不过度干扰界面。

## Current State Analysis
- 后端已经暴露 `stop`、`append_guidance`、`regenerate`、`rollback` 的 WS/HTTP 控制接口，并在 `RuntimeStateSnapshot` 和 `RuntimeDebugSnapshot` 中暴露了 `finish_reason`、`reply_control` 与 `checkpoints`。
- 前端 `types.ts` 和 `protocolClient.ts` 尚未解析这几个新字段。
- 前端缺乏对应的 UI 按钮与发送指令的方法。

## Proposed Changes

### 1. 类型与协议层 (`types.ts`, `protocolClient.ts`)
- **`types.ts`**:
  - 在 `RuntimeStateSnapshot` 中添加 `finish_reason?: string` 和 `reply_control?: Record<string, unknown>`。
  - 在 `RuntimeDebugSnapshot` 中添加 `reply_control?: Record<string, unknown>` 和 `checkpoints?: Record<string, unknown>[]`。
- **`protocolClient.ts`**:
  - 在 `toRuntimeStateSnapshot` 和 `toRuntimeDebugSnapshot` 中补充对这三个字段的安全解析 (`toRecord`, `Array.isArray`)。

### 2. 状态钩子 (`useMeetYou.ts`, `App.tsx`)
- **`useMeetYou.ts`**:
  - 新增 `sendControlCommand` 方法，支持通过 WS 发送控制指令。
  - 格式：`{ action, ...params, metadata: { from: 'ui-control' } }`。
  - 将该方法从 hook 暴露出来。
- **`App.tsx`**:
  - 将 `sendControlCommand` 传递给 `MessageList` 和 `ChatInput` 组件。

### 3. 全局输入框集成：打断与追加引导 (`ChatInput.tsx`, `ChatInput.module.css`)
- **判断繁忙状态 (`isBusy`)**: `['thinking', 'tool_calling', 'answering'].includes(runtimeSnapshot?.status || '')`。
- **交互逻辑**:
  - 如果处于 `isBusy` 状态且输入框为空：发送按钮变为“停止”按钮（渲染为实心方块 `Square`），点击调用 `sendControlCommand('stop')`。
  - 如果处于 `isBusy` 状态且用户输入了内容：发送按钮仍为“发送”图标，但点击后调用 `sendControlCommand('append_guidance', { guidance: inputVal })`，且清空输入框。
  - 提示词 (placeholder) 增加动态判断，当 `isBusy` 时提示“可输入补充要求...”。
  - 键盘事件 `Enter` 在 `isBusy` 且有输入时同样触发 `append_guidance`。

### 4. 消息流组件集成：重新生成与检查点回退 (`MessageList.tsx`, `TurnBody.tsx`, `TurnBody.module.css`)
- **`MessageList.tsx`**:
  - 获取最后一个 Assistant 消息的 ID (`lastAssistantMessageId`)。
  - 遍历渲染 `TurnBody` 时，提取对应的 `checkpoint_id`（通过对比 `runtimeDebugSnapshot.checkpoints` 和 `message.turnId`）。
  - 向 `TurnBody` 传递 `isLastAssistantTurn`, `checkpointId`, `onRegenerate`, `onRollback`。
- **`TurnBody.tsx`**:
  - 如果不是流式生成 (`!turn.isStreaming`)，是 Assistant 角色，且非 `isBusy` 状态，则在消息末尾渲染一个动作栏 `.actionBar`。
  - **重新生成**: 若为最后一条 Assistant 消息且有回调，显示 `RefreshCw` 图标按钮。
  - **回退**: 若存在 `checkpointId` 且有回调，显示 `History` 图标按钮。
- **`TurnBody.module.css`**:
  - 为 `.actionBar` 添加默认透明 (`opacity: 0`) 和过度动画。
  - 利用 `:global(.messageInner):hover .actionBar` 实现在鼠标悬停在气泡上时显示操作栏，保持页面极简干净。

## Assumptions & Decisions
- **不污染会话历史**: 追加引导不会被当作普通用户消息持久化到 UI 列表中，而是直接合并后重放，前端无需手动维护追加的消息状态，只需依赖后端的 `message` 重写。
- **隐式关联 Checkpoint**: 前端无需单独调用 `list_checkpoints` 接口，因为 `RuntimeDebugSnapshot`（该快照已由前端自动按需刷新）中已经包含检查点列表。
- **渲染平滑**: 在消息气泡上悬停显示控制栏，与常见的 Chat UI 习惯一致，不破坏原有极简风格。

## Verification Steps
1. 在 AI 思考或输出时，输入框右侧会显示方形停止按钮。点击后流应立即中断。
2. 在 AI 输出时，在输入框打字并发送，会触发 `append_guidance`，UI 会中断当前生成并基于新提示词重放。
3. 对话结束后，鼠标悬停在最后一条助手回复上，点击刷新按钮触发重新生成。
4. 鼠标悬停在较早的助手回复上，点击回退按钮，对应的历史将被裁剪并回退到该检查点状态。
