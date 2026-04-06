# 回复控制与检查点能力 Spec

## Why
当前后端已经具备完整的流式回复主链路，但还缺少“回复时打断”“回复时追加引导”“重新回复”“检查点回退”这几项关键控制能力，导致会话一旦进入生成态，用户几乎无法低成本纠偏。  
本次变更从后端开始，先建立可中断、可重放、可回退的回复控制底座，再为后续前端交互和更复杂的编排策略提供稳定协议与状态模型。

## What Changes
- 为会话执行链路增加“当前回复控制”能力，支持在生成中显式中断当前回复
- 为模型流式执行增加取消信号与统一收束逻辑，确保中断后 runtime、stream、usage 与会话状态一致
- 增加“回复时追加引导”能力：在当前回复进行中接收补充指令，并以受控方式中断、合并意图、重新发起本轮回复
- 增加“重新回复”能力：允许基于最近一次可重放输入恢复到稳定检查点并重新生成答案
- 增加会话检查点模型：在关键轮次前后保存可恢复快照，为重新回复与显式回退提供统一基础
- 增加检查点查询与回退能力，支持按检查点恢复 chat history、runtime metadata、usage snapshot 与相关 turn 边界
- 扩展网关协议与后端控制命令，允许前端后续接入 stop / append guidance / regenerate / rollback
- 补齐围绕流式取消、控制重放、检查点恢复、幂等与异常回收的测试
- **BREAKING**：回复控制不再只依赖“整轮串行直至完成”的单一路径，执行链路需显式区分 active turn、canceling、replaying、rolled_back 等状态
- **BREAKING**：会话状态不再只保留线性 chat history，需要额外维护 checkpoint 元数据与最近可重放输入引用

## Impact
- Affected specs: 会话运行时、流式协议、会话状态模型、执行编排、网关控制命令、检查点回退、重新生成、测试体系
- Affected code: `core/app.py`、`core/brain.py`、`core/brain_session.py`、`core/session_actor.py`、`adapters/base.py`、`adapters/openai_adapter.py`、`gateway/api.py`、`gateway/models.py`、`core/speaker.py`、`gateway/ws_manager.py`、`tests/`

## ADDED Requirements
### Requirement: 回复中断控制
系统 SHALL 支持对正在进行的回复发起显式中断，并在中断后让执行态、流式态与会话态保持一致。

#### Scenario: 用户在回复生成中点击停止
- **WHEN** 会话存在正在输出中的 assistant 回复
- **THEN** 后端 SHALL 向当前执行链路发出取消信号
- **AND** SHALL 停止继续向前端发送新的正文或推理增量
- **AND** SHALL 以稳定方式结束或标记当前 stream，使前端可判定本轮被中断而非自然完成

### Requirement: 回复时追加引导
系统 SHALL 支持在当前回复尚未完成时接收补充引导，并基于同一用户意图重新生成更贴近新要求的回复。

#### Scenario: 用户要求“更简短一点”
- **WHEN** 当前 assistant 回复仍在流式输出中，且用户追加一条引导指令
- **THEN** 系统 SHALL 先中断当前回复
- **AND** SHALL 将追加引导与最近一次待完成用户意图进行受控合并
- **AND** SHALL 基于恢复后的稳定上下文重新发起回复，而不是把追加引导当作普通独立新轮次永久污染历史

### Requirement: 重新回复
系统 SHALL 支持对最近一次可重放回复执行重新生成，而无需用户重新输入原始问题。

#### Scenario: 用户要求“重新回复”
- **WHEN** 最近一次 assistant 回复存在对应的可恢复检查点与原始输入引用
- **THEN** 系统 SHALL 恢复到该回复开始前的稳定检查点
- **AND** SHALL 使用原始输入重新驱动模型生成新答案
- **AND** SHALL 避免保留上一次失败、中断或被替换回复的残留 assistant/tool 产物

### Requirement: 会话检查点
系统 SHALL 在回复控制相关关键边界建立检查点，为中断后重放、显式回退与调试诊断提供统一恢复基础。

#### Scenario: 新一轮回复即将开始
- **WHEN** 系统准备开始一次新的 assistant 回复轮次
- **THEN** 系统 SHALL 保存最小但充分的会话检查点
- **AND** 检查点 SHALL 至少覆盖 chat history 边界、turn 标识、runtime metadata、usage snapshot 与可重放输入引用

### Requirement: 检查点回退
系统 SHALL 支持显式回退到指定检查点，并让后续会话从该历史分叉继续推进。

#### Scenario: 用户选择回退到较早检查点
- **WHEN** 用户请求恢复到某个仍可用的检查点
- **THEN** 系统 SHALL 恢复该检查点对应的会话快照
- **AND** SHALL 丢弃其后的 assistant/tool 历史与失效的控制态
- **AND** SHALL 返回可供前端确认的新当前状态与可见检查点信息

### Requirement: 回复控制协议
系统 SHALL 暴露稳定的后端控制协议，供前端后续无缝接入回复中断、追加引导、重新回复与回退能力。

#### Scenario: 前端发送控制命令
- **WHEN** 网关收到 stop、append guidance、regenerate 或 rollback 控制命令
- **THEN** 后端 SHALL 对命令做会话归属、当前状态、幂等键与可执行性校验
- **AND** SHALL 返回明确的接受、拒绝或已完成语义，而不是静默忽略

## MODIFIED Requirements
### Requirement: 会话执行模型
会话执行模型不再只支持“输入事件进入后串行跑完整轮回复”的单一路径。  
系统 SHALL 为 active turn 建立可取消、可重放、可恢复的控制状态，并在串行执行前提下允许受控打断与重启当前回复。

### Requirement: 会话状态持久语义
会话状态不再只由线性 `chat_history` 驱动。  
系统 SHALL 同时维护检查点元数据、最近可重放输入、当前控制态与必要的恢复边界，以支持重新回复与显式回退。

### Requirement: 流式结束语义
流式结束语义不再只有“自然完成”一种完成原因。  
系统 SHALL 区分正常结束、用户中断、控制重放、异常失败等结束原因，并向前端暴露稳定可判定的结束状态。

## REMOVED Requirements
### Requirement: 只能等待当前回复自然结束
**Reason**: 仅允许当前回复跑到自然结束，会让用户无法在低成本下纠偏、缩短答案或重新引导模型，交互代价过高。  
**Migration**: 改为支持 stop / append guidance / regenerate 控制命令，并以检查点恢复保证历史干净与状态一致。
