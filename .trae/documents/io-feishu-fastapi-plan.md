# MeetYou 输入输出解耦、FastAPI 网关与飞书 Bot 接入计划

## Summary

目标是把当前 CLI 强耦合的输入输出链路重构为统一的事件协议与 I/O 端口架构，使 `listener` 只负责接收输入、`speaker` 只负责输出路由，并在此基础上规划 FastAPI 统一网关与飞书 Bot 长连接接入。

本次计划按“全量方案设计”制定，首版会话模型采用“每来源独立会话”，Brain 只决策“语义目标”，统一网关首版采用“HTTP 入站 + WebSocket 出站”。

README 需要同步到最新项目现状与新架构方向，修正文档中已过时的模块说明，并补充新的系统结构、接入方式和演进路线。

## Current State Analysis

### 已确认的现状

1. 当前程序入口为 [main.py](file:///e:/Documents/Project/MeetYou/main.py#L13-L23)，应用装配与生命周期集中在 [app.py](file:///e:/Documents/Project/MeetYou/core/app.py#L31-L213)。
2. 当前运行时并发启动 `brain_processor()`、`heart.heartbeat_processor()`、`listener.run()`、`proprioceptor.run()`，见 [app.py](file:///e:/Documents/Project/MeetYou/core/app.py#L193-L202)。
3. 当前主输入流是 `Listener/Heart -> EventBus.sensory_queue -> App.brain_processor -> Brain.input_brain()`，见 [listener.py](file:///e:/Documents/Project/MeetYou/sensors/listener.py#L89-L94)、[heart.py](file:///e:/Documents/Project/MeetYou/core/heart.py#L115-L120)、[app.py](file:///e:/Documents/Project/MeetYou/core/app.py#L136-L173)。
4. 当前输出直接由 `App.output()` 写入 `Listener.output_field`，输出层与 CLI 强耦合，见 [app.py](file:///e:/Documents/Project/MeetYou/core/app.py#L110-L116)。
5. 当前 `Listener` 同时承担界面渲染、用户输入采集、系统输出展示和确认交互四类职责，见 [listener.py](file:///e:/Documents/Project/MeetYou/sensors/listener.py#L35-L41)、[listener.py](file:///e:/Documents/Project/MeetYou/sensors/listener.py#L67-L107)、[listener.py](file:///e:/Documents/Project/MeetYou/sensors/listener.py#L116-L123)。
6. `Heart` 已是一个平行输入源，会向感知队列投递后台输入事件，见 [heart.py](file:///e:/Documents/Project/MeetYou/core/heart.py#L103-L120)。
7. 当前 `EventBus` 同时提供发布订阅和 `sensory_queue`，但主业务流主要走队列，确认机制才显式走事件发布，事件模型双轨并存，见 [event_bus.py](file:///e:/Documents/Project/MeetYou/core/event_bus.py#L23-L48)、[event_bus.py](file:///e:/Documents/Project/MeetYou/core/event_bus.py#L57-L127)。
8. 当前 `Brain` 维护单实例全局 `_chat_history`，尚不支持多来源独立会话，见 [brain.py](file:///e:/Documents/Project/MeetYou/core/brain.py#L45-L59)。
9. 项目当前没有 FastAPI、uvicorn 等依赖，说明统一网关需要全新接入，见 [requirements.txt](file:///e:/Documents/Project/MeetYou/requirements.txt#L1-L10)。
10. README 存在过时描述，例如仍提到 `context.py` 是“上下文总线”、`sensors.py`、`config_manage.py` 等与现代码不一致的内容，见 [README.md](file:///e:/Documents/Project/MeetYou/README.md#L161-L170)。

### 当前问题归纳

1. 输入与输出职责没有彻底分离，导致接入新渠道必须穿透 CLI 实现。
2. 事件协议未统一，`sensory_queue` 与 `publish/subscribe` 并存，扩展复杂。
3. 会话状态是全局单例，不适合 FastAPI 前端与飞书 Bot 并存。
4. 危险命令确认链路绑定 CLI 文本交互，无法复用于飞书和前端。
5. 文档未同步真实代码结构，不利于后续协作和新模块落地。

## Assumptions & Decisions

### 已锁定决策

1. 本次产出的是全量可执行方案，而不是只为某个最小里程碑做局部设计。
2. 首版会话模型采用“每来源独立会话”：
   - CLI 一个 session
   - Web 前端每连接或每显式会话一个 session
   - 飞书私聊、群聊、线程等根据来源标识各自映射 session
3. Brain 只做“语义目标”决策，不直接指定底层连接 ID。
4. 首版统一网关采用“HTTP 入站 + WebSocket 出站”：
   - HTTP 负责投递标准输入事件
   - WebSocket 负责订阅输出、状态、确认、流式事件
5. 飞书 Bot 在架构上与当前 `listener` 平行，属于新的输入适配器和输出适配器，不直接侵入 Brain。

### 本计划中的补充技术决策

1. 不把 FastAPI 作为核心总线，只把它作为外部网关与适配层。
2. 先定义进程内统一事件协议，再让 CLI、Heart、FastAPI、飞书对接该协议。
3. 保留现有 `core/`、`sensors/`、`tools/` 目录风格，在现结构上演进，避免一次性大搬家。
4. 首版不让 Brain 持有输出适配器实例，而是把输出写入统一 `Speaker`。
5. 首版统一支持流式输出事件，至少区分：开始、增量、结束、错误。
6. 首版确认机制采用协议化事件，CLI、前端、飞书共享同一确认模型。

## Proposed Changes

### 一、建立统一 I/O 协议层

#### 新增文件

1. `core/io_protocol.py`
2. `core/session_manager.py`

#### 变更目标

在核心层定义输入输出标准消息结构、会话绑定规则与路由目标枚举，为所有输入源和输出目标提供统一协议。

#### 具体设计

1. 在 `core/io_protocol.py` 定义标准数据模型：
   - `InboundEvent`
   - `OutboundEvent`
   - `EventSource`
   - `EventTarget`
   - `StreamEventType`
   - `ConfirmRequestEvent`
   - `ConfirmResponseEvent`
2. 首版字段固定为：
   - `event_id`
   - `session_id`
   - `type`
   - `role`
   - `source`
   - `target`
   - `content`
   - `stream_id`
   - `reply_to`
   - `metadata`
3. `source.kind` 预设枚举：
   - `cli`
   - `heart`
   - `feishu`
   - `web`
   - `system`
4. `target.kind` 预设枚举：
   - `current_session`
   - `cli`
   - `feishu`
   - `web`
   - `broadcast`
   - `internal`
5. `session_manager.py` 负责：
   - 来源到 `session_id` 的映射
   - 会话元数据登记
   - 当前 session 的默认输出目标绑定
   - 流式输出时 `stream_id` 分配

#### 设计原因

1. 先统一协议，后续适配器才能共享一套输入输出链路。
2. `session_id` 前置到一级字段，避免后续多端接入再返工上下文模型。
3. `target` 与 `source` 分离，可以支持“收到自飞书，回复到 Web”这类跨渠道语义。

### 二、从 Listener 中拆分输入与输出职责

#### 现有文件

1. [sensors/listener.py](file:///e:/Documents/Project/MeetYou/sensors/listener.py)
2. [core/app.py](file:///e:/Documents/Project/MeetYou/core/app.py)

#### 新增文件

1. `sensors/cli_input_adapter.py`
2. `sensors/cli_output_adapter.py`
3. `core/speaker.py`

#### 变更目标

把当前 `Listener` 拆成两个平行职责：
1. CLI 输入适配器：只负责收集用户输入和确认回复
2. CLI 输出适配器：只负责渲染普通输出、状态输出、确认提示

#### 具体设计

1. `cli_input_adapter.py`
   - 保留 `prompt_toolkit` 输入区与按键绑定
   - 仅负责把用户输入转换成 `InboundEvent`
   - 检测确认态时输出 `ConfirmResponseEvent`
2. `cli_output_adapter.py`
   - 持有当前输出区组件
   - 负责渲染：
     - `assistant` 文本
     - 系统错误
     - 状态消息
     - 确认提示
3. `speaker.py`
   - 提供统一 `emit(event: OutboundEvent)` 接口
   - 内部按 `target.kind` 路由到已注册输出适配器
   - 支持 `emit_stream_start / emit_stream_chunk / emit_stream_end / emit_error`
4. `listener.py` 处理策略：
   - 不直接删除
   - 先改为兼容包装器或迁移期间桥接层
   - 第二阶段实施后再决定是否完全退场

#### 设计原因

1. 这是把 CLI 从“核心依赖”降级为“一个适配器”的关键步骤。
2. 先保留 `prompt_toolkit` 资产，避免为重构付出额外 UI 成本。
3. 新的 `Speaker` 是后续飞书与前端共享输出能力的中心点。

### 三、收敛 EventBus 为统一事件流

#### 现有文件

1. [core/event_bus.py](file:///e:/Documents/Project/MeetYou/core/event_bus.py)
2. [core/app.py](file:///e:/Documents/Project/MeetYou/core/app.py)

#### 变更目标

把现在“`sensory_queue` 主链路 + publish/subscribe 局部机制”的双轨通信，收敛到单一事件协议和统一事件入口。

#### 具体设计

1. `EventBus` 保留一个主输入队列，队列元素统一改为 `InboundEvent`
2. 保留发布订阅能力，但只用于：
   - 内部状态广播
   - 确认请求广播
   - 输出适配器订阅类事件
3. `sensory_queue` 更名为更语义化的输入队列属性，例如：
   - `inbound_queue`
4. 事件类型固定为：
   - `message`
   - `signal`
   - `confirm_request`
   - `confirm_response`
   - `status`
   - `control`
5. `Heart` 不再手写 `{"source": "heart"}`，而是产出标准 `InboundEvent`

#### 设计原因

1. 不统一事件模型，FastAPI 和飞书接入后会重复做协议转换。
2. 统一输入事件后，`App` 只需要处理一种结构，Brain 前的逻辑会大幅简化。

### 四、引入 SessionManager，改造 Brain 为多会话模式

#### 现有文件

1. [core/brain.py](file:///e:/Documents/Project/MeetYou/core/brain.py)
2. [core/context.py](file:///e:/Documents/Project/MeetYou/core/context.py)

#### 新增文件

1. `core/brain_session.py`

#### 变更目标

把当前全局 `_chat_history` 改为“每 session 一份对话状态”，为 CLI、Web、飞书并行接入提供基础。

#### 具体设计

1. `brain_session.py` 定义单会话状态对象，封装：
   - `chat_history`
   - 最近活跃时间
   - 当前流状态
   - 会话级上下文元数据
2. `Brain` 改为通过 `session_id` 获取会话状态：
   - `get_or_create_session(session_id)`
   - `close_session(session_id)`
3. `ContextManager.trim_history()` 继续复用，但入参改为单 session 的 `chat_history`
4. `Brain.close_brain()` 关闭时遍历所有活跃会话，按 session 做上下文摘要持久化
5. 首版会话隔离规则：
   - CLI 固定一个本地 session
   - Web 使用客户端分配或服务端回传的 `session_id`
   - 飞书使用来源标识映射到独立 session

#### 设计原因

1. 多来源接入的根问题不是通道，而是上下文隔离。
2. 不先改 Brain 会话模型，FastAPI 和飞书都只能假装多端，实际上仍是单脑共享上下文。

### 五、调整 App 编排，去除对 Listener 的直接依赖

#### 现有文件

1. [core/app.py](file:///e:/Documents/Project/MeetYou/core/app.py)

#### 变更目标

让 `App` 只编排核心模块与适配器，不直接操作任意具体界面组件。

#### 具体设计

1. `App.__init__()` 中新增装配：
   - `SessionManager`
   - `Speaker`
   - `CLIInputAdapter`
   - `CLIOutputAdapter`
   - 后续预留 `FastAPIGateway`、`FeishuInputAdapter`、`FeishuOutputAdapter`
2. 删除或废弃 `App.output()` 里直接写 `listener.output_field` 的方式
3. `brain_processor()` 改为：
   - 从统一输入队列读取 `InboundEvent`
   - 根据 `session_id` 交给 Brain
   - 把 Brain 产出的文本片段封装为 `OutboundEvent`
   - 交给 `Speaker`
4. 启动问候消息同样走 `Speaker`，不再走本地 UI 直写
5. 错误展示 `_display_error()` 也改为构造系统输出事件，通过 `Speaker` 分发

#### 设计原因

1. `App` 应该是编排层，不是 UI 操作层。
2. 去除 `Listener` 依赖后，FastAPI 和飞书才能并列挂到同一编排层。

### 六、把 Heart 明确为标准输入源

#### 现有文件

1. [core/heart.py](file:///e:/Documents/Project/MeetYou/core/heart.py)

#### 变更目标

将 `Heart` 从“向特殊队列塞特殊字典”的实现，改造成一个正式输入源。

#### 具体设计

1. `Heart` 输出的后台事务封装为 `InboundEvent`
2. `source.kind` 固定为 `heart`
3. `type` 固定为 `signal`
4. 首版 `Heart` 事件不绑定已有用户来源，使用独立系统 session，例如：
   - `session_id = system:heart`
5. `App` 收到心跳信号时，不再拼接硬编码中文前缀，而是通过统一规则转换为 Brain 的系统输入

#### 设计原因

1. 这一步把你提出的“heart 也会给输入”正式制度化。
2. 后续其他后台模块也可以复用同一输入协议。

### 七、协议化确认机制，脱离 CLI 专属实现

#### 现有文件

1. [core/event_bus.py](file:///e:/Documents/Project/MeetYou/core/event_bus.py)
2. [sensors/listener.py](file:///e:/Documents/Project/MeetYou/sensors/listener.py)
3. [tools/system_tools.py](file:///e:/Documents/Project/MeetYou/tools/system_tools.py)

#### 变更目标

把危险命令确认从“CLI 文本问答”升级为“跨渠道统一确认事件”。

#### 具体设计

1. `system_tools.py` 发起确认时，不再默认面向 CLI，而是创建 `ConfirmRequestEvent`
2. `Speaker` 按当前 session 默认输出目标，把确认请求推给：
   - CLI 输出适配器
   - WebSocket 客户端
   - 飞书消息发送端
3. 输入适配器收到确认回复后，统一产出 `ConfirmResponseEvent`
4. `EventBus` 内部保留等待确认 Future 的机制，但输入输出表面协议统一
5. 确认事件至少包含：
   - `request_id`
   - `session_id`
   - `prompt`
   - `timeout`
   - `default_decision`

#### 设计原因

1. 这是多渠道行为一致性的关键。
2. 如果确认机制不改，飞书和前端只能绕过安全流程或重写一套专属逻辑。

### 八、接入 FastAPI 统一网关

#### 新增文件

1. `gateway/__init__.py`
2. `gateway/api.py`
3. `gateway/models.py`
4. `gateway/ws_manager.py`

#### 配套修改

1. [requirements.txt](file:///e:/Documents/Project/MeetYou/requirements.txt)
2. [main.py](file:///e:/Documents/Project/MeetYou/main.py)
3. [core/app.py](file:///e:/Documents/Project/MeetYou/core/app.py)

#### 变更目标

提供统一外部接入口，使前端或外部系统可以投递输入并接收流式输出与系统事件。

#### 具体设计

1. `gateway/models.py`
   - 定义 HTTP 请求与响应模型
   - 模型字段与 `io_protocol.py` 保持一一映射
2. `gateway/api.py`
   - 提供 `POST /inputs`
   - 提供 `GET /health`
   - 提供 `WebSocket /ws`
3. `ws_manager.py`
   - 管理 WebSocket 连接
   - 维护 `session_id -> connections`
   - 提供按 session 推送和广播推送
4. `App.run()` 增加 FastAPI/uvicorn 生命周期编排
5. HTTP 入站行为：
   - 请求体转 `InboundEvent`
   - 放入统一输入队列
   - 返回接收确认与 `session_id`
6. WebSocket 出站行为：
   - 订阅某个 `session_id`
   - 推送普通文本、流式事件、确认请求、状态事件
7. WebSocket 首版不承担通用入站，只做订阅与控制消息；用户消息一律先走 HTTP，保持责任清晰

#### 设计原因

1. 用户已明确首版偏好“HTTP 入站 + WebSocket 出站”。
2. 这种模式比纯双向 WebSocket 更利于后续前端和服务端分层。

### 九、接入飞书 Bot 长连接适配器

#### 新增文件

1. `sensors/feishu_input_adapter.py`
2. `sensors/feishu_output_adapter.py`
3. `adapters/feishu_ws_client.py`

#### 配套修改

1. [core/app.py](file:///e:/Documents/Project/MeetYou/core/app.py)
2. [core/config.py](file:///e:/Documents/Project/MeetYou/core/config.py)
3. [requirements.txt](file:///e:/Documents/Project/MeetYou/requirements.txt)

#### 变更目标

把飞书 Bot 以“平行于 CLI Listener”的方式接入统一协议链路，实现独立输入源与输出目标。

#### 具体设计

1. `feishu_ws_client.py`
   - 负责飞书长连接 websocket 生命周期
   - 负责接收飞书事件包并交给输入适配器
   - 负责重连、鉴权、心跳
2. `feishu_input_adapter.py`
   - 把飞书消息事件映射为 `InboundEvent`
   - 解析来源标识，生成稳定 `session_id`
   - 区分私聊与群聊来源
3. `feishu_output_adapter.py`
   - 把 `OutboundEvent` 转为飞书发送请求
   - 支持普通文本、确认提示、错误输出
4. `core/config.py`
   - 增加飞书相关配置读取项
   - 保持敏感密钥优先从环境变量取值
5. 首版 session 映射策略：
   - 私聊：`feishu:chat:<chat_id>`
   - 群聊：`feishu:chat:<chat_id>`
   - 如需更细粒度，再扩展线程或用户维度

#### 设计原因

1. 飞书是新的输入输出通道，不应再复刻一套业务逻辑。
2. 通过统一协议接入后，飞书与 Web 前端都能复用同一个 Brain 与安全链路。

### 十、更新 README，使文档与代码同步

#### 现有文件

1. [README.md](file:///e:/Documents/Project/MeetYou/README.md)

#### 变更目标

把 README 从“旧 CLI 单入口叙事”更新为“当前真实结构 + 即将演进的统一 I/O 架构”。

#### 具体设计

1. 修正项目结构章节中的过时描述：
   - 替换不存在或不准确的 `sensors.py`、`config_manage.py`
   - 改为真实文件与职责
2. 新增“系统运行架构”章节：
   - App、Brain、Heart、Context、Memory、EventBus、Proprioceptor
3. 新增“输入输出架构演进”章节：
   - Listener 仅输入
   - Speaker 统一输出
   - FastAPI 网关
   - 飞书 Bot 适配器
4. 新增“会话模型”章节：
   - 每来源独立会话
5. 新增“统一协议概览”章节：
   - `InboundEvent`
   - `OutboundEvent`
6. 更新安装与运行说明：
   - 说明新增依赖
   - 说明 CLI/FastAPI/飞书三类运行入口或开关
7. 明确列出安全说明：
   - 飞书凭证与 API Key 不入库
   - 配置放置位置与环境变量优先级

#### 设计原因

1. 当前 README 已与仓库实际结构脱节。
2. 这次改造属于架构升级，若文档不跟进，后续实现和协作会持续失真。

## Implementation Order

1. 建立 `io_protocol.py` 与 `session_manager.py`
2. 建立 `speaker.py`
3. 拆分 `listener.py` 为 CLI 输入/输出适配器
4. 收敛 `event_bus.py` 的事件协议
5. 改造 `brain.py` 为多 session 模式
6. 改造 `app.py` 去除对具体 CLI 输出控件的直接依赖
7. 协议化 `heart.py` 与确认机制
8. 接入 FastAPI 网关骨架
9. 接入飞书长连接适配器
10. 更新 `README.md`

## Verification Steps

### 代码级验证

1. CLI 模式下仍能完成：
   - 输入消息
   - 流式回复
   - 危险命令确认
2. `Heart` 产出的后台信号能进入统一输入链路且不污染其他 session。
3. 多来源 session 不共享 `_chat_history`。
4. `Speaker` 能正确按 `target.kind` 分发输出。

### 网关验证

1. `POST /inputs` 能创建或使用指定 `session_id` 投递消息。
2. `WebSocket /ws` 能按 `session_id` 接收：
   - 流式文本
   - 状态事件
   - 确认请求
   - 错误事件
3. Web 断开连接不影响核心 Brain/Heart 运行。

### 飞书验证

1. 飞书 websocket 建立后能正常收消息。
2. 私聊与群聊能映射到稳定 `session_id`。
3. Brain 输出经 `Speaker` 路由后能回到对应飞书会话。
4. 确认事件能在飞书侧发起并回传。

### 回归验证

1. 原有记忆、工具调用、上下文裁剪流程不被破坏。
2. 启动、关闭、异常处理与资源释放仍正确。
3. README 中的结构描述、启动说明、配置说明与实现一致。

## Risks & Mitigations

1. 风险：会话改造会波及 Brain、Context 和关闭持久化流程。
   - 缓解：先引入 `BrainSession` 包装层，再逐步替换直接访问 `_chat_history` 的逻辑。
2. 风险：确认机制跨渠道统一后，CLI 现有交互可能短期不兼容。
   - 缓解：先做桥接实现，让 CLI 继续基于文本确认，再逐步切到统一事件。
3. 风险：FastAPI 与 CLI 同进程运行时的生命周期协调复杂。
   - 缓解：由 `App` 统一编排启动和关闭，所有外部适配器只通过统一协议通信。
4. 风险：飞书事件模型和项目内部协议语义不完全一致。
   - 缓解：把差异封装在飞书输入/输出适配器内，不让核心层感知平台特性。

## Out of Scope

1. 本次计划不包含前端页面具体 UI 设计。
2. 本次计划不包含飞书卡片消息、线程消息等高级能力的细化设计。
3. 本次计划不包含把所有工具调用改为并发执行。
4. 本次计划不包含重新设计 Memory 算法本身。
