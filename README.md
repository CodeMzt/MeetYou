# MeetYou

MeetYou 是一个基于大语言模型（LLM）的仿生智能体应用，旨在模拟人类认知过程。项目采用仿生模块化架构，将能力划分为“Brain（推理）”“Heart（后台心跳）”“Memory（长时记忆）”“Sensors（感知输入）”“Speaker（统一输出）”等层次，并开始演进为支持 CLI、FastAPI 网关与飞书 Bot 的统一输入输出协议体系。

## 核心特性

- **仿生认知架构：** Brain、Heart、Memory、Context、Proprioceptor 等模块异步协作，模拟“前台意识 + 后台潜意识”的工作方式。
- **统一 I/O 协议：** 输入输出开始从旧 Listener 中拆分，形成标准 `InboundEvent` / `OutboundEvent` 协议、`SessionManager` 和 `Speaker` 路由层。
- **多通道扩展能力：** 当前保留 CLI 交互，同时加入 FastAPI 网关骨架与飞书 Bot 适配骨架，便于后续接前端与 IM。
- **高级上下文管理：** 结合滑动窗口、动态摘要和长时记忆检索，在长对话中维持语义连贯性。
- **记忆图谱系统：** 基于语义向量与图结构构建长期记忆，详见下方技术论述。
- **多模型支持：** 灵活接入 OpenAI、Anthropic、Gemini、Ollama 等多种 LLM 推理后端。

---

## 记忆图谱算法：技术论述

### 1. 概述（Abstract）

MeetYou 的记忆系统提出了一种**基于语义向量嵌入的动态知识图谱**（Semantic Embedding-based Dynamic Knowledge Graph）方案，用于为 LLM 智能体提供持久化、可遗忘、可联想的长时记忆能力。该系统以 `NetworkX` 无向图为底层数据结构，以**文本嵌入向量**（Text Embedding Vector）为语义表示，通过**余弦相似度**驱动边（"突触"）的生成与更新，并引入**指数衰减遗忘机制**和**情绪权重调制**来模拟人类记忆的动态特性。

### 2. 图结构定义（Graph Formalization）

记忆图谱 $G = (V, E)$ 是一个无向加权图，其中：

**节点 $v_i \in V$（记忆节点）** 的属性定义为一个五元组：

| 属性 | 符号 | 类型 | 描述 |
|---|---|---|---|
| `content` | $c_i$ | `string` | 记忆的原始文本内容 |
| `vector` | $\vec{e}_i$ | `float[]` | 由外部 Embedding API 编码的高维语义向量 |
| `memory_weight` | $w_i$ | `float` | 记忆强度权重，表示该记忆被遗忘的难易程度 |
| `emotion_intensity` | $\epsilon_i$ | `float ∈ [0, 1]` | 情绪强度系数，调节记忆初始权重与召回强化幅度 |
| `node_id` | $\text{id}_i$ | `string` | 由 `SHA-256(content)` 截取前 16 位生成的确定性唯一标识 |

**边 $e_{ij} \in E$（突触连接）** 携带属性：

| 属性 | 符号 | 描述 |
|---|---|---|
| `sim_weight` | $s_{ij}$ | 两节点嵌入向量的余弦相似度，充当突触强度 |

### 3. 核心算法（Core Algorithms）

#### 3.1 记忆编码与存储（Memory Encoding & Storage）

当 LLM 决定持久化一条信息时，系统执行以下流程：

1. **向量化：** 调用外部 Embedding API 将文本 $c$ 编码为高维向量 $\vec{e}$。
2. **去重检验：** 以 `SHA-256(c)[:16]` 生成确定性节点 ID，若图中已存在该 ID 则拒绝写入。
3. **权重初始化：** 初始记忆权重通过情绪强度线性调制：
   $$w_0 = 0.5 + \epsilon \times 0.5$$
   其中 $\epsilon \in [0, 1]$，使得日常琐事（$\epsilon \approx 0.2$）的初始权重约为 $0.6$，而强烈情感事件（$\epsilon \approx 1.0$）的初始权重达到 $1.0$。
4. **增量突触构建：** 新节点入图后立即触发 `rebuild_synapses`，仅计算新节点与所有既有节点的相似度（复杂度 $O(N)$），避免全量重建。相似度阈值 $\theta_{\text{incr}} = 0.7$。

#### 3.2 突触构建算法（Synapse Construction）

突触构建是记忆图谱的核心关联机制，分为两种模式：

**全量批次重建 `build_synapses()`** — 在系统初始化或"睡眠"周期执行：

```
输入：记忆图 G = (V, E)
输出：更新后的边集 E'

1. 提取所有节点的有效嵌入向量，构成矩阵 M ∈ ℝ^{N×D}
2. 按行归一化：M̂ = M / ‖M‖₂  （L2-norm, 零向量保护）
3. 计算全局相似度矩阵：S = M̂ · M̂ᵀ  （矩阵乘法, O(N²D)）
4. 遍历上三角 S[i,j] (i < j):
     若 S[i,j] > θ_batch (0.5):
       - 边不存在 → 创建边 (v_i, v_j, sim_weight=S[i,j])
       - 边已存在且 |Δweight| > 0.01 → 更新权重（静默）
```

该方法通过 **NumPy 矩阵运算**将 $O(N^2)$ 次独立余弦相似度计算优化为单次矩阵乘法 $S = \hat{M}\hat{M}^T$，利用 BLAS 级别的向量化加速，在节点规模较大时获得显著性能提升。

**增量重建 `rebuild_synapses(new_id)`** — 在新节点写入时即时触发：

```
输入：新节点 ID, 记忆图 G
输出：新节点的突触边集

1. 提取新节点向量 ê_new
2. 逐一计算 cos(ê_new, ê_i) ∀ v_i ∈ V \ {v_new}
3. 若 cos > θ_incr (0.7) → 建立边 (v_new, v_i)
```

增量模式采用较高阈值（$0.7$ vs $0.5$），确保实时操作仅建立高置信度关联，而宽松关联留给批次周期处理。

#### 3.3 指数衰减遗忘机制（Exponential Decay Forgetting）

遗忘模型灵感来源于 Ebbinghaus 遗忘曲线。系统在每个心跳周期（默认 60 秒）触发一次衰减：

$$w_i^{(t+1)} = w_i^{(t)} \times \lambda, \quad \lambda = 0.95$$

当权重衰减至清除阈值 $w_i \leq \theta_{\text{forget}} = 0.2$ 时，节点及其所有关联边从图中永久移除。

这意味着一个初始权重为 $1.0$ 的强记忆，在无任何召回强化的情况下：
- 经过约 **10 个周期** 衰减至 $\approx 0.60$
- 经过约 **32 个周期** 衰减至 $\approx 0.19$（被清除）

而初始权重为 $0.6$ 的弱记忆仅能存活约 **21 个周期** 即被遗忘。情绪强度通过初始权重间接影响记忆的"自然寿命"。

#### 3.4 记忆召回与扩散激活（Recall & Spreading Activation）

召回过程模拟了人类记忆的"联想"特性，分为**锚点定位**和**扩散检索**两个阶段：

**阶段一：语义锚点定位**
```
1. 将查询文本编码为向量 ê_query
2. 遍历所有节点，计算 cos(ê_query, ê_i)
3. 选取最高分节点作为锚点 v_anchor（需 score ≥ 0.4）
```

**阶段二：图扩散检索（Ego-Graph Spreading Activation）**
```
1. 以 v_anchor 为中心，提取 k-hop 子图（默认 k=3）
   SubG = ego_graph(G, v_anchor, radius=3)
2. 遍历 SubG 中所有节点：
   若 w_i ≥ θ_recall (0.4) → 纳入结果集
3. 对被召回的节点执行"记忆强化"
```

**记忆强化公式：**
$$w_i^{(\text{new})} = w_i + \frac{10 \times \epsilon_i}{1 + w_i}$$

该公式具有以下特性：
- **情绪放大（Emotion Amplification）：** 高情绪强度 $\epsilon_i$ 的记忆在被召回时获得更强的权重增益，模拟"刻骨铭心"的记忆效应。
- **边际递减（Diminishing Returns）：** 分母 $1 + w_i$ 随现有权重增长，使得已经很强的记忆不会被无限强化，防止单一记忆垄断，保持图结构的多样性。

### 4. 系统生命周期（System Lifecycle）

```mermaid
graph TD
    A["系统启动 init_memory()"] --> B["加载持久化图谱 JSON → NetworkX Graph"]
    B --> C["全量突触重建 build_synapses()"]
    C --> D["全局遗忘衰减 fade_memory()"]
    D --> E["进入运行态"]
    
    E --> F{"事件源"}
    F -->|"LLM 调用 save_memory()"| G["编码 → 入图 → 增量突触 → 持久化"]
    F -->|"LLM 调用 recall_memory()"| H["衰减 → 向量检索 → 锚点 → 扩散 → 强化 → 持久化"]
    F -->|"心跳周期 (60s)"| I["fade_memory(): 全局衰减 + 清除死节点"]
    
    G --> E
    H --> E
    I --> E
```

### 5. 设计动机与理论关联（Design Rationale）

| 设计选择 | 理论灵感 |
|---|---|
| 指数衰减遗忘（$\lambda = 0.95$） | Ebbinghaus 遗忘曲线（1885） |
| 情绪调制权重 | Yerkes-Dodson 定律；杏仁核-海马体情绪记忆增强机制 |
| 扩散激活检索 | Collins & Loftus 扩散激活模型（1975） |
| 召回时权重强化 | 测试效应（Testing Effect）；Bjork 必要难度理论（Desirable Difficulties） |
| 突触（边）以相似度为权重 | Hebb 定律："Neurons that fire together wire together" |
| 边际递减强化公式 | 韦伯-费希纳定律（Weber–Fechner Law）对数感知增长 |

---

## 项目结构

| 路径 | 描述 |
|---|---|
| `core/` | 核心编排与认知模块，包括 `app.py`、`brain.py`、`heart.py`、`context.py`、`event_bus.py`、`speaker.py`、`session_manager.py`、`io_protocol.py` |
| `sensors/` | 输入与感知相关模块，包括 `cli_input_adapter.py`、`cli_output_adapter.py`、`feishu_input_adapter.py`、`feishu_output_adapter.py`、`proprioceptor.py` |
| `gateway/` | FastAPI 网关骨架，提供 HTTP 入站和 WebSocket 出站能力 |
| `adapters/` | 模型适配器与外部连接适配器，包括各 LLM adapter 与 `feishu_ws_client.py` |
| `tools/` | 可扩展工具集，核心为 `memory.py`（记忆图谱）、`system_tools.py`（系统工具）、`mcp.py`（MCP 集成） |
| `platform_layer/` | 不同操作系统的能力抽象与检测 |
| `prompt/` | 系统级与场景级 Prompt 模板 |
| `user/` | 用户数据目录，存储配置、记忆图谱、MCP 配置等持久化数据（已 git-ignore） |
| `main.py` | 程序入口，创建 `App` 并启动事件循环 |

## 运行架构

当前主链路已经调整为统一事件协议：

```text
CLI / Heart / Feishu / Web
        ↓
   InboundEvent
        ↓
    EventBus.inbound_queue
        ↓
        App
        ↓
       Brain
        ↓
   OutboundEvent
        ↓
      Speaker
        ↓
CLI / WebSocket / Feishu
```

### 核心模块职责

- **App**：负责依赖注入、生命周期管理和主协程编排。
- **Brain**：按 `session_id` 维护多会话上下文，与模型通信并处理工具调用。
- **Heart**：周期性执行后台心跳检查，并将有效结果作为标准输入事件注入系统。
- **SessionManager**：维护来源与 `session_id` 的绑定关系，以及默认输出目标。
- **Speaker**：统一输出路由中心，根据目标将消息发往 CLI、WebSocket 或飞书。
- **EventBus**：统一输入队列与内部发布订阅中心。

## 输入输出协议

首版统一协议基于两个核心事件：

- `InboundEvent`：统一输入事件
- `OutboundEvent`：统一输出事件

关键字段包括：

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

### 事件类型

- `message`
- `signal`
- `confirm_request`
- `confirm_response`
- `status`
- `control`
- `error`

### 会话模型

项目当前采用“每来源独立会话”的设计：

- CLI 默认绑定 `cli:local`
- Heart 默认绑定 `system:heart`
- Web 通过 `session_id` 或来源标识创建独立会话
- 飞书按 `chat_id` 绑定到 `feishu:chat:<chat_id>`

## FastAPI 网关

详细接口文档见 [interface.md](file:///e:/Documents/Project/MeetYou/docs/interface.md)。

项目已加入统一网关骨架：

- `POST /inputs`：提交标准文本输入
- `GET /health`：健康检查
- `WebSocket /ws`：订阅某个 `session_id` 的流式输出、状态事件与确认事件

首版网关策略为：

- HTTP 负责入站
- WebSocket 负责出站
- Brain 不直接感知 HTTP 或 WebSocket 连接细节

### WebSocket 事件格式

WebSocket 出站统一使用 `meetyou.ws.v1` 包装格式：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "event",
  "event": {
    "event_id": "string",
    "session_id": "string",
    "type": "message|status|confirm_request|error",
    "role": "assistant|system|user",
    "content": "string|object",
    "source": {},
    "target": {},
    "stream_id": "string",
    "reply_to": "string",
    "metadata": {}
  },
  "stream": {
    "id": "string",
    "phase": "start|chunk|end|error"
  },
  "confirm": {
    "request_id": "string",
    "timeout": 30.0,
    "default_decision": false
  }
}
```

连接建立后，服务端先发送：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "connection",
  "connection": {
    "session_id": "string",
    "source_id": "string",
    "status": "connected"
  }
}
```

### WebSocket 入站命令

当前 WebSocket 支持以下命令：

- `{"action": "ping"}`
- `{"action": "confirm_response", "request_id": "...", "accepted": true}`

确认回传成功后，服务端返回：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "ack",
  "ack": {
    "action": "confirm_response",
    "request_id": "string"
  }
}
```

## 飞书 Bot

项目已加入飞书 Bot 接入骨架：

- 使用飞书长连接模式接收事件
- 输入侧通过 `FeishuInputAdapter` 映射为 `InboundEvent`
- 输出侧通过 `FeishuOutputAdapter` 发送文本消息
- 流式文本在飞书侧按 `stream_id` 聚合，结束后统一发送
- 确认事件会下发到原飞书会话，用户可直接回复 `y/yes/确认` 或 `n/no/拒绝`

### 建议的飞书开放平台配置

- 应用类型：企业自建应用
- 机器人能力：开启
- 事件订阅方式：长连接（WebSocket）
- 事件：`im.message.receive_v1`

## 快速开始

### 环境要求

- Python 3.10+
- 可用的 LLM 推理后端
- 可选：飞书应用凭证（如需启用飞书 Bot）

### 安装

1. 克隆仓库：
   ```bash
   git clone https://github.com/CodeMzt/MeetYou.git
   cd MeetYou
   ```
2. 创建并激活虚拟环境：
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
   Windows:
   ```bash
   .venv\Scripts\activate
   ```
3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

### 配置

在项目根目录下创建 `user/config.json`。该目录已被 `.gitignore` 排除，不要提交含密钥的配置文件。

配置示例：

```json
{
  "api_provider": "openai",
  "api_url": "https://api.openai.com/v1/chat/completions",
  "model": "gpt-4o",
  "heartbeat_api_provider": "openai",
  "heartbeat_api_url": "https://api.openai.com/v1/chat/completions",
  "heart_model": "gpt-4o-mini",
  "embedding_api_url": "https://api.openai.com/v1/embeddings",
  "embedding_model": "text-embedding-3-small",
  "tools_schema_path": "user/tools.json",
  "soul_path": "prompt/soul",
  "start_path": "prompt/start",
  "heartbeat_path": "prompt/heartbeat",
  "memory_file_path": "user/memory.json",
  "enable_gateway": true,
  "gateway_host": "127.0.0.1",
  "gateway_port": 8000,
  "enable_feishu_bot": false,
  "feishu_broadcast_chat_ids": ["oc_xxx"],
  "feishu_chat_registry_path": "user/feishu_chat_ids.json",
  "feishu_app_id": "cli_xxx",
  "feishu_app_secret": "your-secret"
}
```

支持通过环境变量覆盖敏感配置：

- `MEETYOU_API_KEY`
- `MEETYOU_HEARTBEAT_API_KEY`
- `MEETYOU_EMBEDDING_API_KEY`
- `MEETYOU_FEISHU_APP_ID`
- `MEETYOU_FEISHU_APP_SECRET`

### 运行

```bash
python main.py
```

默认会进入 launcher 控制台，可用命令：

- `help`
- `start gateway`
- `start cil`
- `start ui`
- `status`
- `exit`

也可以直接启动指定组件：

```bash
python main.py gateway
python main.py cil
python main.py launcher
```

### 默认行为

- 当前架构固定为 `gateway` 唯一后端。
- `python main.py` 启动的是 launcher，而不是直接进入旧版本地 CLI。
- `start cil` 与 `start ui` 会先检查本地 gateway，未运行时自动拉起。
- CIL 通过 gateway 的 HTTP/WebSocket 接口对话，不再与后端运行时同进程。
- 启用 `enable_feishu_bot` 后，会启动飞书长连接客户端。
- 飞书收到消息后，会自动把 `chat_id` 记录到 `user/feishu_chat_ids.json`，可再复制到广播配置中。

### CIL 命令

- `/help`
- `/config list`
- `/config get <key>`
- `/config set <key> <value>`

### Gateway 配置接口

- `GET /config`：读取全部受管配置快照，密钥字段只返回掩码。
- `GET /config/{key}`：读取单项配置。
- `PATCH /config`：批量更新配置，返回已应用项、已热更新组件、需重启项和警告。

## 安全说明

- 不要把 API Key、飞书 App Secret、用户配置提交到版本控制。
- 高风险系统命令会走统一确认机制，不再只依赖 CLI 专属逻辑。
- 飞书和 Web 前端都应通过标准确认事件完成危险操作授权。

## 快速开始

### 环境要求
- Python 3.8+
- LLM 推理后端的 API Key（如 OpenAI、Ollama）

### 安装
1. 克隆仓库：
   ```bash
   git clone https://github.com/CodeMzt/MeetYou.git
   cd MeetYou
   ```
2. 创建并激活虚拟环境（推荐）：
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

### 配置
在项目根目录下创建 `user/` 文件夹，并在其中新建 `user/config.json` 文件（该目录已通过 `.gitignore` 排除，**请勿将含有密钥的配置文件提交到版本控制**）。

配置文件示例：
```json
{
    "api_key": "YOUR_API_KEY",
    "api_url": "https://api.openai.com/v1/chat/completions",
    "model": "gpt-4o",
    "embedding_api_url": "https://api.openai.com/v1/embeddings",
    "embedding_model": "text-embedding-3-small",
    "tools_schema_path": "tools.json",
    "soul_path": "prompt/soul",
    "start_path": "prompt/start",
    "heartbeat_path": "prompt/heartbeat",
    "memory_file_path": "user/memory.json"
}
```

### 运行
```bash
python main.py
```

启动后使用 launcher 命令控制各组件；如需直接拉起指定组件，可用：

```bash
python main.py gateway
python main.py cil
```

## 作者

<a href="https://github.com/Codemzt">
  <img src="https://github.com/Codemzt.png" width="100px;" alt="用户名"/>
</a>

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
