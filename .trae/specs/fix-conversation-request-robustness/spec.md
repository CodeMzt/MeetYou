# 对话请求健壮性修复 Spec

## Why
当前前端对话过程中出现 DeepSeek 兼容接口 `400 Bad Request`，同时存在上下文预算估算偏差、超限压缩丢失结构化上下文、以及流式推理结束边界不稳定的问题，导致错误来源难以定位，且前端体验会出现“正文已输出但推理还在继续”的异常现象。  
本次变更聚焦对话请求健壮性与流式一致性，彻查并修复模型请求构造、上下文预算、自动压缩、推理/工具事件顺序，以及面向前端的调试暴露能力。

## What Changes
- 修复 OpenAI 兼容适配器与 DeepSeek 兼容路径的请求健壮性，确保构造出的请求参数、消息体与流式状态满足接口约束
- 统一上下文预算口径，使预算估算、真实发送消息体、自动压缩策略与 provider 限额一致
- 重构自动压缩语料生成逻辑，保留 tool_calls、tool 输出、provider_items 与必要的结构化上下文
- 修复流式推理生命周期，让 reasoning 在单轮模型 round 结束或进入工具阶段时正确结束
- 暴露调试/状态接口，说明本轮是否触发压缩、压缩前后预算、请求体规模、provider 限额与失败分类
- 为 DeepSeek / OpenAI 兼容路径补齐错误分类、上下文超限回退、以及前端可见状态提示
- 增加围绕长上下文、多轮工具调用、reasoning + answer 混合流式场景的系统级测试
- **BREAKING**：调整 reasoning 流事件边界，不再允许上一轮 reasoning 挂到下一轮工具或回答阶段
- **BREAKING**：调整历史压缩摘要内容结构，使其包含结构化上下文摘要而不再只保留纯文本内容

## Impact
- Affected specs: 对话运行时、OpenAI 兼容适配器、DeepSeek 兼容调用、上下文预算、自动压缩、流式事件协议、前端状态展示、调试接口、错误分类、测试体系
- Affected code: `adapters/openai_adapter.py`、`core/context.py`、`core/brain.py`、`core/app.py`、`core/protocol_schema.py`、`core/source_catalog.py`、`gateway/api.py`、`gateway/models.py`、`meetyou-ui/src/`、`tests/`

## ADDED Requirements
### Requirement: 兼容接口请求健壮性
系统 SHALL 在 OpenAI 兼容与 DeepSeek 兼容路径下构造合法、可诊断且与 provider 约束一致的对话请求。

#### Scenario: DeepSeek 兼容接口发送对话请求
- **WHEN** 系统向 DeepSeek 兼容对话接口发送请求
- **THEN** 请求体 SHALL 只包含该路径支持的字段与合法的流式参数
- **AND** 失败时 SHALL 记录结构化错误分类、provider 名称、请求规模与可定位上下文

### Requirement: 统一上下文预算口径
系统 SHALL 使用统一规则估算消息、tool_calls、tool 输出、provider_items 与压缩摘要所占预算，并让该口径与实际发出的请求体一致。

#### Scenario: 多轮工具调用后继续对话
- **WHEN** 会话包含多轮工具调用、provider_items 或 reasoning 续接信息
- **THEN** 系统 SHALL 将这些结构化上下文计入预算
- **AND** SHALL 在超预算前优先触发自动压缩或其他降载策略

### Requirement: 自动压缩保留结构化上下文
系统 SHALL 在历史压缩时保留后续对话继续所必需的结构化信息，而不是只保留纯文本摘要。

#### Scenario: 工具调用后历史被压缩
- **WHEN** 历史中包含 assistant tool_calls、tool 输出或 provider_items 且需要压缩
- **THEN** 压缩结果 SHALL 记录函数名、关键参数、工具结果摘要与必要的推理续接信息
- **AND** SHALL 维持后续对话所需的最小语义连续性

### Requirement: 单轮流式生命周期一致
系统 SHALL 为每一轮模型执行建立明确的 reasoning、answer、tool phase 与 round end 边界。

#### Scenario: 模型先推理再调用工具
- **WHEN** 模型输出 reasoning 后立即进入 tool_calls 阶段
- **THEN** 前端 SHALL 收到当前 reasoning 的完成信号
- **AND** 下一轮 reasoning 或回答 SHALL 不复用上一轮未关闭的推理流状态

### Requirement: 请求失败可诊断性
系统 SHALL 在对话失败时暴露足够的调试信息，帮助区分上下文超限、非法字段、流式协议问题、provider 限额或鉴权错误。

#### Scenario: 对话请求返回 400
- **WHEN** provider 返回 400 Bad Request
- **THEN** 系统 SHALL 记录结构化失败分类、估算 token、压缩是否触发、模型/provider 标识与请求路径
- **AND** SHALL 避免只向日志输出无法定位的通用异常文本

### Requirement: 前端上下文状态可见性
系统 SHALL 向前端或调试接口暴露本轮上下文预算与压缩状态，使用户能判断当前是否因长上下文降级或被自动压缩。

#### Scenario: 本轮触发自动压缩
- **WHEN** Brain 在发送请求前执行自动压缩
- **THEN** 前端或调试接口 SHALL 能看到压缩已发生、压缩级别、预算前后变化与是否仍接近 provider 上限

## MODIFIED Requirements
### Requirement: 上下文管理
上下文管理不再只按纯文本 message 估算预算。  
系统 SHALL 将 `provider_items`、tool_calls、tool 结果、压缩摘要与其他结构化消息一并纳入预算估算与压缩决策。

### Requirement: 流式对话事件
流式对话事件不再以“整轮 turn 完成”作为 reasoning 唯一结束边界。  
系统 SHALL 在单次模型 round 结束、进入工具阶段或进入下一轮模型执行前，正确结束当前 reasoning 生命周期。

### Requirement: 错误处理
对话错误处理不再仅依赖 HTTP 异常透传。  
系统 SHALL 将 provider 400、上下文超限、字段不兼容、鉴权失败与网络错误区分为稳定错误分类，并暴露必要诊断上下文。

## REMOVED Requirements
### Requirement: 纯文本压缩主路径
**Reason**: 仅以纯文本内容生成压缩摘要会丢失多轮工具调用、结构化推理与 provider 续接上下文，导致压缩后对话失真。  
**Migration**: 改为结构化压缩输入，至少保留 tool_calls、tool 结果摘要、provider_items 摘要和必要上下文元数据。

### Requirement: 模糊 reasoning 结束时机
**Reason**: 将 reasoning 结束时机绑定到整轮 turn 或正文首 token，会导致前端出现“答案已出但推理未结束”的错误状态。  
**Migration**: 以单轮模型执行为单位发出 reasoning start / reasoning end，并在 tool phase 切换时主动收束。
