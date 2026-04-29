# V4 细分计划 01：Domain Schema / Migration / Bootstrap

## 目标

建立 V4 的领域模型和数据库结构：Actor、Endpoint、Run、RunEvent、Scheduler、Delivery、Operation 的新主链。迁移目标不是保留 V3 协议兼容，而是把已有数据尽量转成 V4 语义。

---

## 新增模型

```text
Actor
Endpoint
EndpointConnection
EndpointCapability
Thread
Message
Run
RunEvent
ScheduledJob
ScheduledJobRun
EndpointOutbox
DeliveryAttempt
Operation
OperationCall
```

---

## 数据模型任务

### 1. Actor

创建 system actors：

```text
system.scheduler
system.heartbeat
system.maintenance
```

迁移或创建 user actor：

```text
user:<primary_user>
```

字段：

```text
actor_id
actor_type
owner_user_id nullable
display_name
permission_profile_id
metadata
```

### 2. Endpoint

创建 core endpoints：

```text
core.local           provider_type=core, transport_type=inproc
core.scheduler       provider_type=core, transport_type=inproc
core.inbox           provider_type=core, transport_type=database
core.notification    provider_type=core, transport_type=inproc
```

迁移旧 clients：

```text
desktop.<client_id>.ui
desktop.<client_id>.executor
desktop.<client_id>.notifier
edge.<client_id>.executor
```

### 3. EndpointCapability

把旧 `executable_tools` 迁移到 endpoint capabilities。

不要把旧 `available_tools` 直接照搬到 endpoint。V4 中 allowed tools 属于 Actor / Workspace / RunPolicy。

### 4. Thread / Message

Thread 不得包含 client ownership。

Message 可以记录：

```text
origin_endpoint_id nullable
created_by_actor_id nullable
run_id nullable
```

### 5. Run / RunEvent

Run 是所有执行的统一容器。

RunEvent 要有单调递增 seq，至少在 run 内唯一。

### 6. ScheduledJob / ScheduledJobRun

Bootstrap 时创建：

```text
job_id = system.heartbeat
kind = system_heartbeat
singleton_key = core.system.heartbeat
deletable = false
enabled = true
```

要求幂等。

### 7. Operation / OperationCall

替换：

```text
target_client_id -> target_endpoint_id / execution_target_id
requested_by_session_id -> requested_by_run_id / requested_by_actor_id
```

---

## Migration 注意事项

1. 不做运行时兼容，但 migration 要尽量保留数据。
2. 除非人类明确确认，不允许清空生产数据库。
3. 如果旧表字段仍需保留一段时间用于 migration，可保留数据库字段，但新代码不能依赖旧字段。
4. migration 完成后，bootstrap 不能重复创建 system records。
5. 如果旧 session 无法完整迁移，至少要保留 thread / messages。

---

## Bootstrap 要求

Core 启动时必须确保：

```text
system actors exist
core endpoints exist
system.heartbeat scheduled job exists
default workspace exists
default delivery policy exists
default execution policy exists
```

重复启动不能重复插入。

---

## 测试

### Alembic / DB

```bash
python -m pytest tests/db tests/core -q
```

补充测试：

- fresh DB bootstrap。
- old V3-ish data migration smoke。
- repeated bootstrap idempotency。
- scheduled_jobs 中 system.heartbeat 不重复。
- endpoints 中 core.local / core.scheduler / core.inbox 存在。

### 数据约束

测试 system.heartbeat：

- 不可删除。
- 可启停。
- 可修改 interval。

测试 Thread：

- Thread 创建不需要 endpoint / client。
- Message 可记录 origin_endpoint，但不是必填。

---

## 验收

- [x] Alembic migration 完成。
- [x] ORM / service models 完成。
- [x] bootstrap 幂等。
- [x] system actors 存在。
- [x] core endpoints 存在。
- [x] system.heartbeat scheduled job 存在且不可删除。
- [x] 旧 Client 数据能迁移成 Endpoint。
- [x] 新代码不依赖 source_client_id / target_client_id。
