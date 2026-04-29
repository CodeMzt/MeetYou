# V4 细分计划 06：Desktop / Edge / UI Endpoint Provider

## 目标

把 Desktop 和 Edge 改造成 Endpoint Provider。UI 不再依赖 client-bound session，而是通过 Core Thread / Message / Run / Delivery 工作。

---

## Desktop Provider

Desktop 应暴露多个 endpoint：

```text
desktop.<device_id>.ui          roles=input, output
desktop.<device_id>.executor    roles=execution
desktop.<device_id>.notifier    roles=output optional
```

连接 Core：

```text
/endpoint/ws
meetyou.endpoint.ws.v4
```

发送：

```text
endpoint.hello
endpoint.capabilities.snapshot for executor
endpoint.ready
endpoint.heartbeat keepalive
```

---

## Edge Provider

Edge 应暴露：

```text
edge.<node_id>.executor
edge.<node_id>.notifier optional
```

Edge 没有 UI，不创建 Thread，不拥有对话。

---

## UI 行为

UI 应使用 Core 的 Thread / Message / Delivery API：

```text
list workspaces
list threads
create thread
send message
subscribe thread events
render streaming deltas
render progress notices
render final messages
render operation updates
```

UI 不应该：

```text
create client-bound session as conversation owner
assume source_client_id
assume reply always goes back to same client
render short_reply as final assistant message
```

---

## 配置更新

示例：

```json
{
  "provider_id": "home-pc",
  "provider_type": "desktop",
  "core_base_url": "https://core.example.com",
  "endpoint_ws_path": "/endpoint/ws",
  "endpoints": {
    "ui": "desktop.home-pc.ui",
    "executor": "desktop.home-pc.executor",
    "notifier": "desktop.home-pc.notifier"
  },
  "workspace_ids": ["personal"],
  "capabilities_path": "user/desktop_capabilities.json"
}
```

---

## UI 渲染规则

### message.delta

显示在当前 assistant bubble 中。

### assistant.progress_notice

显示为临时状态条 / toast / inline progress，不进入 final message bubble。

### message.completed

替换 / 固化 assistant bubble。

### operation_update

显示工具执行状态，例如：

```text
正在读取文件
等待确认
执行完成
执行失败
等待 endpoint 上线
```

---

## 断线重连

Desktop 重连流程：

```text
1. reconnect /endpoint/ws
2. endpoint.hello
3. endpoint.ready
4. UI list existing threads
5. subscription.start(thread_id, last_seen_event_seq)
6. Core replay durable events or messages snapshot
7. continue live events
```

---

## 测试

### Desktop backend

- endpoint.hello 发送正确 endpoints。
- capabilities snapshot 正确。
- heartbeat keepalive 正确。
- tool.call.request 能执行 file.read。
- tool.call.result 返回。

### Edge

- edge executor 能注册 capability。
- edge 不创建 UI endpoint。

### UI

- Thread list。
- 创建 Thread。
- 发送 message。
- streaming delta 渲染。
- progress_notice 单独渲染。
- final message 持久显示。
- reconnect 恢复。

---

## 真实测试

本地：

1. 启动本地 Core。
2. 启动 Desktop backend。
3. 启动 UI。
4. 创建 Thread。
5. 发送问题，观察 streaming。
6. 触发 progress_notice。
7. 触发 file.read。
8. 断开 Desktop backend。
9. 重启 Desktop backend。
10. 继续原 Thread。

远程：

1. CI + Deploy 通过后，确认远程 Core 更新。
2. 本地 Desktop 配置指向远程 Core。
3. 重复真实测试。

---

## 验收

- [x] Desktop 使用 /endpoint/ws。
- [x] Edge 使用 /endpoint/ws。
- [x] UI 不再依赖 client-bound conversation。
- [x] Thread 可跨重连继续。
- [x] Streaming 正常。
- [x] progress_notice 单独显示。
- [x] 本地 Desktop -> 远程 Core 真实测试通过。
