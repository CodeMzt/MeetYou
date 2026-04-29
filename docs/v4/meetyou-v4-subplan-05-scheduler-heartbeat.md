# V4 细分计划 05：Scheduler / system.heartbeat

## 目标

把 Scheduler 作为唯一系统级调度时钟。真正的 AI / 系统 heartbeat 作为 Scheduler 中一条不可删除、可启停、可修改间隔的系统预设 Job。普通定时任务可创建、启停、编辑、删除。

---

## 核心设计

```text
SchedulerService
  -> scheduled_jobs
  -> due detection
  -> lock / lease
  -> scheduled_job_runs
  -> RunService.create(trigger=scheduled_job/system_heartbeat)
  -> RunQueue / RunWorker
```

Heartbeat：

```text
scheduled_job: system.heartbeat
kind: system_heartbeat
deletable: false
enabled: true/false editable
interval editable
```

---

## 数据结构

### scheduled_jobs

```text
job_id
workspace_id nullable
kind: system_heartbeat | user_task | workflow | maintenance
singleton_key nullable
name
enabled
deletable
editable_fields
trigger_type: interval | cron | manual | event
trigger_config
timezone
action_ref
run_template
execution_policy
delivery_policy
concurrency_policy
misfire_policy
```

### scheduled_job_runs

```text
job_run_id
job_id
run_id nullable
scheduled_at
started_at
finished_at
status
error
metadata
```

---

## system.heartbeat 配置

```json
{
  "job_id": "system.heartbeat",
  "workspace_id": null,
  "kind": "system_heartbeat",
  "singleton_key": "core.system.heartbeat",
  "name": "System Heartbeat",
  "enabled": true,
  "deletable": false,
  "editable_fields": [
    "enabled",
    "trigger_config.interval_seconds",
    "execution_policy.limits",
    "delivery_policy"
  ],
  "trigger_type": "interval",
  "trigger_config": {
    "interval_seconds": 600
  },
  "timezone": "Asia/Shanghai",
  "action_ref": "core.workflow.heartbeat",
  "concurrency_policy": {
    "type": "skip_if_running"
  },
  "misfire_policy": {
    "type": "run_once"
  }
}
```

---

## HeartbeatWorkflow

Heartbeat 每次触发时应检查：

```text
pending / stuck runs
waiting_for_endpoint operations
waiting_for_approval operations
scheduled jobs health
endpoint liveness
memory signals
reminders
workspace-level proactive tasks
outbox delivery backlog
```

输出可以是：

```text
no-op run event
notice
message
operation
new scheduled job
retry request
```

---

## 用户定时任务

必须支持：

```text
create
list
get
update
enable
disable
delete
manual trigger
```

但 system.heartbeat：

```text
delete -> forbidden
update unsupported fields -> forbidden
```

---

## API 建议

```text
GET    /scheduler/jobs
POST   /scheduler/jobs
GET    /scheduler/jobs/{job_id}
PATCH  /scheduler/jobs/{job_id}
DELETE /scheduler/jobs/{job_id}
POST   /scheduler/jobs/{job_id}/trigger
GET    /scheduler/jobs/{job_id}/runs
```

删除 system.heartbeat 返回：

```json
{
  "error": {
    "code": "system_job_not_deletable",
    "message": "system.heartbeat cannot be deleted"
  }
}
```

---

## 测试

### Unit

- due detection。
- cron / interval 计算。
- concurrency skip_if_running。
- misfire run_once。
- system.heartbeat editable fields。
- system.heartbeat delete forbidden。

### Integration

- bootstrap 后存在 system.heartbeat。
- Scheduler tick 创建 JobRun。
- JobRun 创建 Run。
- heartbeat run actor = system.heartbeat。
- disable 后不触发。
- enable 后触发。
- interval 修改后生效。
- user job 可 CRUD。

---

## 真实测试

本地真实测试：

1. 启动 Core。
2. 设置 system.heartbeat interval 为短间隔，例如 30 秒。
3. 确认产生 JobRun 和 Run。
4. disable heartbeat，确认不再产生。
5. enable heartbeat，确认恢复。
6. 创建一个用户定时任务。
7. 确认任务触发后生成 Run 和 Message / Notice。
8. 删除用户定时任务。
9. 尝试删除 system.heartbeat，确认被拒绝。

远程真实测试：

1. Deploy 通过后连接远程 Core。
2. 重复上述 heartbeat 和用户定时任务测试。
3. 本地 Desktop 订阅相关 Thread / Inbox，确认收到 Delivery。

---

## 验收

- [x] SchedulerService 完成。
- [x] system.heartbeat 是 scheduled job。
- [x] system.heartbeat 不可删除。
- [x] system.heartbeat 可启停、可调 interval。
- [x] 用户定时任务 CRUD 完成。
- [x] 每次触发都会生成 JobRun + Run。
- [x] HeartbeatWorkflow 至少能 no-op 并记录事件。
- [x] 本地和远程真实测试通过。
