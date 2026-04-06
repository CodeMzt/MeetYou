# MeetYou Backend Refactoring Plan

> 目标：精简、稳定、可维护。聚焦真实问题，不为重构而重构。

---

## 现状诊断

| 模块 | 行数 | 主要问题 |
|------|------|---------|
| `core/app.py` | ~1390 | 上帝对象：初始化、路由、事件、健康检查全混在一起 |
| `core/brain.py` | ~1941 | 单方法 `input_brain` 超500行；模式切换、工具调用、usage统计耦合 |
| `core/heart.py` | ~1000 | 后台任务与 `App` 双向引用，错误恢复策略不统一 |
| `core/assistant_modes.py` | ~1193 | 职责边界清晰，但与 `Brain` 的交互路径冗长 |
| `core/semantic_router.py` | ~1039 | 逻辑正确，与 `assistant_modes` 存在意图重叠 |

---

## Phase 1 — App 拆分（优先级：高）

**问题：** `App.__init__` 顺序初始化20+依赖，任何一步失败都难以定位。

**方案：**
- 将初始化逻辑拆为独立工厂函数，每个服务返回明确类型
- `App` 只持有顶层引用，不直接接触子模块内部

```
app.py          → 保留生命周期(setup / shutdown / brain_processor)
app_builder.py  → build_config(), build_memory(), build_brain(), build_heart() 等工厂
```

**验收：** `App.__init__` < 30 行；每个 `build_*` 函数独立可测试。

---

## Phase 2 — Brain 方法拆分（优先级：高）

**问题：** `input_brain` 是超500行的 async generator，包含：
1. 会话准备 & 上下文修剪
2. 主循环：调用模型 → 流式输出
3. 工具执行（多轮）
4. 模式切换
5. Usage 统计

**方案：拆为私有方法群**

```python
# 现有
async def input_brain(self, ...) -> AsyncGenerator:  # 500+ lines

# 目标
async def input_brain(self, ...):
    ctx = await self._prepare_turn(session, ...)      # 会话准备
    async for event in self._run_turn_loop(ctx, ...): # 主循环
        yield event

async def _prepare_turn(...)    # 修剪历史、build context plan
async def _run_turn_loop(...)   # while True: call model → handle tools → switch mode  
async def _handle_tool_round(...)   # 工具执行 + mode switch
async def _finalize_turn(...)   # usage 统计、persist
```

**验收：** 每个子方法 < 80 行；主循环可读性提升。

---

## Phase 3 — Heart 错误恢复（优先级：中）

**问题：** 三条后台循环（heartbeat / housekeeping / scheduler）各自有不同的错误处理逻辑，部分仅 `logger.error` 后继续，无统一的退避策略。

**方案：**
- 引入 `_loop_guard(name, coro, *, backoff)` 装饰器/上下文，统一捕获 + 退避 + 上报 health
- `Heart` 不再直接引用 `App`，通过回调或 `EventBus` 汇报状态
- 心跳失败超过阈值时，通过 `EventBus.publish(ERROR, ...)` 通知，由 `App` 决策

**验收：** 三条 `*_processor` 均通过 `_loop_guard`；`Heart` 去掉对 `App` 的直接引用。

---

## Phase 4 — 依赖方向整理（优先级：中）

**当前循环依赖：**
```
App → Brain → ContextManager → Memory
App → Heart → App(回调)
Brain → SessionActor → RouteRuntime
```

**目标依赖方向（单向）：**
```
ServiceRuntime
  └─ App (组装者)
       ├─ Brain   (依赖: Memory, ContextManager, ToolsManager, ModeManager)
       ├─ Heart   (依赖: EventBus, 回调接口)
       └─ Gateway (依赖: EventBus, SessionManager)
```

**具体动作：**
- `Heart` 中 `self._app` 引用替换为 `Callable` 接口（`get_background_status`, `run_heartbeat_turn` 等）
- `Brain` 不直接调用 `Gateway`，改为 `EventBus.publish`

---

## Phase 5 — 可观测性补强（优先级：低）

**问题：** 遥测分散在 `service_runtime` 和各模块的 `logger`，无统一结构化格式。

**方案（轻量）：**
- 在 `EventBus` 增加 `TELEMETRY` 事件类型，各模块发布结构化事件
- `RuntimeTelemetryRecorder` 订阅并聚合，现有健康检查接口不变
- 不引入外部 tracing 框架，保持零依赖

---

## 不做的事

| 项目 | 原因 |
|------|------|
| 全面重写为微服务 | 项目规模不到位，过度复杂 |
| 引入 DI 框架（injector/wire） | 工厂函数已足够，框架增加学习成本 |
| 替换 EventBus 为消息队列 | 单进程场景无需 |
| 拆分 `assistant_modes.py` | 职责合理，行数多但内聚，保留 |

---

## 执行顺序

```
Phase 1 (App拆分)  →  Phase 2 (Brain拆分)  →  Phase 3 (Heart)
       ↓                       ↓
   可独立合并             可独立合并
                                      ↓
                          Phase 4 (依赖方向)  →  Phase 5 (可观测性)
```

每个 Phase 作为独立 PR，保持主分支可运行。

---

## 评估标准

- `App.__init__` ≤ 30 行
- `input_brain` 主体 ≤ 60 行
- 单个方法/函数 ≤ 100 行（新增代码，存量逐步）
- `Heart` 无 `App` 直接引用
- 后台循环错误统一经 `_loop_guard` 处理
