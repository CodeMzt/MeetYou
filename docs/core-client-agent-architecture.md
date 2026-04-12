# MeetYou Server / Client / Node Architecture V2

## 1. 目标形态

MeetYou V2 的目标不是单机桌面助手，而是一个以私人服务器为中心的个人智能体系统。

系统由一个服务器本体和多类客户端、节点组成：

- `Core Service`：长期在线，保存权威状态，负责编排。
- `Client`：提供交互入口，例如 PC 客户端、飞书客户端、未来手机客户端。
- `Client Local Backend`：属于部分客户端内部的本地执行 / 桥接后端，例如 PC 客户端里的 Desktop Agent 形态、未来手机端的本地运行时。
- `Edge / Bridge Node`：按 workspace 接入的边缘执行节点，例如树莓派、K230、局域网桥接节点。

核心原则：

- 服务器是唯一真相源。
- 客户端负责人与系统交互。
- 具备本地能力的客户端可内含本地后端。
- 设备能力通过客户端本地后端或边缘节点注册给 Core，而不是直接绑死在 Core 内。

## 2. 本版已确认决策

- 边缘设备使用 `MQTT transport`。
- `Desktop Agent` 必须支持局部离线任务缓存。
- Core 与 Agent 之间的大附件传输独立为对象存储通道。
- 飞书这种弱交互 Client 允许直接审批高风险执行。
- 不同会话之间必须能通过 Core 联系与协同。
- 一个 Agent 可以同时加入多个 workspace。
- Procedure 默认由 AI / Core 自动推断与维护；用户只通过确认回调参与持久化变更，不承担主动选择或编辑。
- 记忆采用全局统一存储，workspace 通过标签和检索优先级体现，而不是硬隔离存两份。
- 弱设备需要拉模式，而不是只支持 Core 主动推送。

## 3. 拓扑

```text
PC Client (UI + Local Backend) ----\
Feishu Client ----------------------> Core Service ---- Object Storage
Mobile Client (UI + Local Backend) -/        |
                                             |
                                      Agent Gateway
                                             |
                                        MQTT Broker
                                             |
                                  Edge / Bridge Nodes
```

说明：

- Client 与 Core 通过 HTTP / WebSocket 交互。
- PC / 手机客户端中的本地后端优先通过 WSS / HTTPS 连接 Core。
- Edge / Bridge Node 优先通过 MQTT 连接 Agent Gateway。
- 大文件、截图、音频、文档附件不走主消息通道，统一走对象存储。

## 4. 角色职责

### 4.1 Core Service

Core Service 是系统的大脑和账本，负责：

- 对话编排
- 记忆、任务、自动化、审批、审计
- Procedure / Skill / Mode / Source Profile 管理
- Workspace、Agent、Client 元数据管理
- 能力选路与执行调度
- 会话、线程、操作记录管理
- 对象存储元数据与附件引用管理

Core Service 不应承担设备专属执行：

- 本地文件系统修改
- 本地桌面自动化
- 本地 IDE / shell / Git
- GPIO、串口、摄像头、局域网设备控制
- 本地 MCP 生命周期管理

### 4.2 Client

Client 负责交互展示和用户输入，不保存权威状态。

典型 Client：

- PC 客户端
- 飞书 Bot
- 未来手机 App

Client 负责：

- 发送消息
- 查看消息流、任务、引用、审批、设备状态
- 发起操作
- 订阅操作结果与附件
- 切换 workspace 与 mode

Client 不负责：

- 能力选路
- 最终状态持久化
- 长期记忆写入策略
- 全局设备执行策略

补充：

- PC 客户端、未来手机端可以在客户端内部同时包含前端与本地后端。
- 飞书这类轻客户端通常只有交互入口，不自带完整本地后端。

### 4.3 Client Local Backend

Client Local Backend 是客户端内部的本地执行 / 桥接后端。

典型形态：

- PC 客户端内的 `desktop-agent`
- 未来手机客户端内的本地运行时

它负责：

- 与 Core 交换数据并维持连接
- 注册客户端所在终端可用的本地能力
- 执行本地文件、Shell、本地 MCP、桌面或设备能力
- 上报设备状态、执行进度、错误
- 在允许范围内缓存离线任务与离线执行收据

它不负责：

- 全局编排
- 最终审批决策
- 全局记忆与任务真相源

### 4.4 Edge / Bridge Node

Edge / Bridge Node 是按 workspace 接入的设备执行节点。

典型节点：

- `raspi-agent`
- `bridge-agent`

它负责：

- 注册自身与能力
- 执行 Core 下发的 capability 调用
- 上报设备状态、执行进度、错误
- 管理边缘设备、本地工具、本地资源句柄
- 在允许范围内缓存离线任务与离线执行收据

它不负责：

- 全局编排
- 最终审批决策
- 全局记忆与任务真相源

## 5. 会话、线程、操作

V2 需要把“聊天窗口”和“跨端协作”拆开建模。

### 5.1 Session

`session` 表示某个 Client 上的一次具体交互会话。

例如：

- 某次 Electron 聊天窗口
- 某次飞书对话入口

### 5.2 Thread

`thread` 表示逻辑上的连续对话主题，可跨多个 session。

一个 thread 可以挂多个 session：

- 你在飞书发起一条操作请求
- 你在桌面 UI 继续查看执行进度
- 你在手机上稍后查看结果

### 5.3 Operation

`operation` 表示一项独立执行请求，是跨会话协同的核心对象。

示例：

- 让桌面电脑执行某个脚本
- 请求桌面截图并回传
- 调起某个边缘设备采样

Operation 绑定：

- `thread_id`
- `workspace_id`
- `requested_by_client_id`
- `target_agent_id` 或 `execution_target`
- `attachments`

结论：不同 session 不直接互相通信，而是通过共享 `thread` 和 `operation` 由 Core 统一协调。

## 6. 关键场景

### 6.1 飞书发消息，让 PC 客户端执行操作

```text
Feishu Client -> Core
Core: 创建 operation，目标为 PC Client Local Backend
Core -> PC Client Local Backend: 下发执行请求
PC Client Local Backend: 执行并截图
PC Client Local Backend -> Object Storage: 上传截图
PC Client Local Backend -> Core: 回传 attachment reference
Core -> Feishu / Desktop UI / Mobile: 推送 operation 结果与附件引用
```

### 6.2 Core 在线但 PC 客户端本地后端离线

- Core 仍然可处理纯服务端能力，例如研究、记忆、任务。
- 需要桌面能力的 operation 进入待执行队列。
- 若用户在桌面本机，PC 客户端本地后端可进入局部离线模式，缓存本地任务与结果，待回连后同步给 Core。

### 6.3 边缘设备弱联网场景

- 使用 MQTT transport
- 支持 pull 模式
- 设备周期性请求下一条任务，而不是要求 Core 总是主动推送

## 7. API 面分层

Core 暴露四类 API 面：

- `Client API`
- `Agent API`
- `Operator API`
- `Developer API`

原则：

- 普通用户面不再依赖 `/runtime/debug`
- Agent 与 Client 使用不同鉴权和资源模型
- 审批流由 Core 统一管理

详细设计见 `docs/core-api-surfaces.md`。

## 8. 数据归属

### 8.1 Core 持久化的数据

- 记忆
- 任务与自动化
- Workspace、Agent、Client 元数据
- Thread、Session、Operation
- 审批记录与审计记录
- Capability 目录与路由诊断
- 附件元数据

### 8.2 客户端本地后端 / 节点本地数据

- 本地 MCP 配置
- 本地工具缓存
- 本地设备日志
- 本地离线任务缓存
- 临时文件与对象存储上传缓存

### 8.3 对象存储中的数据

- 截图
- 文档附件
- 大文件中间产物
- 音视频与图片

详细设计见 `docs/storage-and-binary-transfer.md`。

## 9. Workspace 设计原则

Workspace 是组织上下文和设备资源的作用域，而不是多租户概念。

Workspace 用于定义：

- situational prompt
- capability overlay
- source profile 偏好
- 任务与自动化目标
- 允许接入的客户端本地后端 / 节点集合

一个客户端本地后端或边缘节点可以属于多个 workspace。

例如：

- `desktop-main-agent` 作为 PC 客户端本地后端，同时属于 `personal`、`desktop-main`、`study`
- `raspi-agent` 同时属于 `personal`、`home-lab`

详细设计见 `docs/workspace-capability-model.md`。

## 10. 审批模型

审批是 Core 领域模型，不再散落在具体 tool 协议里。

### 10.1 审批来源

允许发起审批确认的 Client：

- Electron UI
- 飞书
- 未来手机 App

### 10.2 飞书高风险审批

V2 明确允许飞书审批高风险动作，但前提是：

- 飞书 Client 绑定到你的 principal
- Core 认为该 Client 具备高风险审批权限
- 审批记录必须入审计日志

不额外假设飞书是弱权限入口。

## 11. 节点分类

### 11.1 PC Client Local Backend / Desktop Agent

- 连接方式：WSS / HTTPS
- 负责：桌面文件、命令、本地 MCP、桌面自动化
- 特性：支持局部离线任务缓存

### 11.2 Edge Agent

- 连接方式：MQTT
- 负责：传感器、GPIO、局域网设备、边缘采样
- 特性：支持 pull 模式

### 11.3 Bridge Agent

- 连接方式：WSS 或 MQTT
- 负责：代管不能直接运行 MeetYou Agent 的子设备
- 特性：对外暴露的是“桥接后的能力”，而不是让 Core 直接理解所有底层设备协议

## 12. 降级与离线

### 12.1 Core 离线

- 普通 Client 无法获得权威状态更新
- 客户端本地后端可进入本地降级模式
- 本地降级模式只允许执行本地允许的 capability
- 离线期间产生的结果必须在回连后向 Core 补同步

### 12.2 本地后端 / 节点离线

- Core 仍可继续处理纯服务端能力
- 依赖该客户端本地后端或节点的 operation 转为待执行、失败或重试

### 12.3 对象存储短时不可用

- 小型文本结果仍可通过主协议返回
- 大附件进入待上传状态，操作本身不视为完全完成

## 13. 对当前仓库的映射

### 13.1 演进为 Core 的部分

- `core/`
- `gateway/`
- `service_runtime/`
- 记忆、任务、研究、source catalog、procedure/skill 管理

### 13.2 可保留在 Core / service runtime 的 platform 感知

- 启动期平台识别与 `platform_layer/detector.py`
- 运行宿主机时间、系统生命体征与后台状态观测
- `sensors/proprioceptor.py` 使用的 UI 焦点 / 运行进程感知

这些能力只用于服务端运行装配、健康观测和上下文补充，不直接执行终端命令或本地文件操作。

### 13.3 应归属到客户端本地后端的部分

- 本地文件与 shell 工具
- 本地 MCP
- 桌面自动化
- 与终端环境强耦合的工具

### 13.4 演进为 Client 前端的部分

- `meetyou-ui/`
- 飞书交互层

## 14. 实施阶段

### Phase 1

- 固化“Core + 多客户端 + 客户端内本地后端 / 边缘节点”模型
- 引入 `thread` 与 `operation`
- 修复 session/auth/approval 边界

### Phase 2

- 实现 PC 客户端本地后端
- 将本地 tools 从 Core 剥离
- 建立对象存储附件通道

### Phase 3

- 实现 Edge Agent MQTT transport
- 增加 pull 模式
- 实现 workspace overlay 与多 workspace agent membership

### Phase 4

- 引入 Bridge Agent
- 打通跨端操作联动与附件回传

## 15. ADR

### ADR-001

- 决策：采用模块化单体 Core，而不是微服务。
- 原因：当前仍处于领域模型定型期，微服务会提前放大复杂度。

### ADR-002

- 决策：采用“服务器本体 + 多客户端 + 客户端内本地后端 / 边缘节点”模型。
- 原因：最符合你的私人服务器 + 多终端 + 多设备体系，并能准确表达 PC / 手机客户端内部的本地能力层。

### ADR-003

- 决策：引入 `thread + operation`，而不是只靠 `session`。
- 原因：跨端协作和跨会话操作无法仅靠 session 解决。

### ADR-004

- 决策：大附件走对象存储独立通道。
- 原因：截图、文档、音视频不适合走主消息通道。

### ADR-005

- 决策：边缘设备走 MQTT，并支持 pull 模式。
- 原因：更适合弱设备与不稳定网络环境。
