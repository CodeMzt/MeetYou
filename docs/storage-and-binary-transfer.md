# MeetYou Storage And Binary Transfer Design V2

## 1. 文档目的

本文档定义 MeetYou V2 的持久化与附件传输设计，重点解决：

- 服务器上的权威状态如何存储
- Desktop Agent 的离线缓存如何落地
- Core 与 Agent 之间的大附件如何传输
- 截图、图片、文档、音频等对象如何引用与下载

## 2. 存储分层

V2 推荐四层存储：

- `PostgreSQL`：权威业务数据
- `pgvector`：向量检索
- `Object Storage`：大附件与二进制对象
- `Agent Local Store`：Agent 本地缓存与离线队列

## 3. PostgreSQL 中的权威数据

建议落库的核心对象：

- principals
- clients
- agents
- workspaces
- threads
- sessions
- operations
- approvals
- tasks
- memory records
- capability registry snapshots
- attachment metadata
- audit logs

## 4. 记忆存储

### 4.1 模型

采用统一全局记忆表，而不是 global/workspace 两套独立库。

建议字段：

- `memory_id`
- `principal_id`
- `content`
- `origin_workspace_id`
- `workspace_tags[]`
- `memory_type`
- `visibility`
- `embedding`
- `created_at`
- `updated_at`

### 4.2 检索

- 统一从全局记忆全集检索
- 活跃 workspace 只影响召回排序和标签过滤
- 其他 workspace 来源记忆可见，但需要保留来源字段

## 5. Agent Local Store

### 5.1 Desktop Agent

建议使用本地 `SQLite` 或等价轻量数据库，保存：

- 离线 operation 队列
- 离线执行结果收据
- 待上传附件列表
- 本地 capability revision 缓存
- 本地对象上传失败重试记录

### 5.2 Edge Agent

建议按设备能力选择：

- 轻量 SQLite
- 简化 KV / 文件型缓存

### 5.3 原则

- Agent 本地存储只服务执行态与恢复
- Core 才是最终真相源

## 6. Object Storage

### 6.1 用途

Object Storage 用于保存：

- 截图
- 图片
- 音频
- 文档附件
- 大文本导出产物
- 中间分析结果文件

### 6.2 推荐实现

- S3-compatible storage
- MinIO 或云对象存储都可

### 6.3 当前不做的能力

- V2 暂不为极大文件引入分片上传

当前建议：

- 先通过上传大小限制控制复杂度
- 超过限制的对象由调用方显式失败并提示用户

### 6.4 不应通过主协议传输的内容

- Base64 图片
- 长文档原件
- 音视频
- 大型压缩包

## 7. Attachment 模型

建议核心字段：

```json
{
  "attachment_id": "att_123",
  "kind": "image",
  "owner_type": "operation",
  "owner_id": "op_123",
  "object_key": "ops/2026/04/08/att_123.png",
  "mime_type": "image/png",
  "size_bytes": 245120,
  "sha256": "...",
  "origin_agent_id": "desktop-main-agent",
  "created_at": "2026-04-08T10:00:00Z"
}
```

## 8. 上传流程

### 8.1 Agent 上传大附件

流程：

1. Agent 向 Core 请求上传票据
2. Core 创建附件元数据草稿，签发上传 ticket
3. Agent 直接上传到对象存储
4. Agent 调用 `attachment.complete`
5. Core 将附件挂到 operation / message / task

### 8.2 Client 上传附件

流程相同，只是调用方从 Agent 换成 Client。

## 9. 下载流程

### 9.1 Client 下载

1. Client 请求下载 ticket
2. Core 校验权限
3. Core 返回短时下载 URL
4. Client 直接从对象存储拉取

### 9.2 Agent 下载

Agent 需要下载输入附件时，同样先向 Core 请求短时下载票据。

## 10. 截图回传示例

```text
Feishu Client -> Core: 请求桌面截图
Core -> Desktop Agent: 创建截图 operation
Desktop Agent -> Object Storage: 上传 screenshot.png
Desktop Agent -> Core: attachment.complete
Core -> Feishu Client: 返回 attachment reference
```

## 11. 离线附件缓存

Desktop Agent 断开 Core 时，若本地执行产生附件：

- 先缓存到本地临时目录
- 在本地数据库登记待上传记录
- 回连后批量申请 upload ticket 并上传

### 11.1 Workspace 分桶

Agent 本地缓存目录按 workspace 分桶。

推荐结构：

```text
agent-data/
  workspace-personal/
    offline-queue.db
    attachments/
  workspace-desktop-main/
    offline-queue.db
    attachments/
  workspace-study/
    offline-queue.db
    attachments/
```

这样做的目的：

- 降低不同 workspace 执行态相互污染
- 简化清理与迁移
- 便于本地调试与故障恢复

### 11.2 本地缓存字段建议

- `local_attachment_id`
- `operation_id`
- `local_path`
- `mime_type`
- `size_bytes`
- `sha256`
- `upload_status`
- `retry_count`

## 12. 生命周期与清理

### 12.1 对象生命周期

建议支持：

- `ephemeral`
- `normal`
- `retained`

示例：

- 临时截图：`ephemeral`
- 项目文档：`normal`
- 长期重要资料：`retained`

截图类短期附件应启用更短生命周期。

推荐：

- 截图、临时调试图片：`24h - 72h`
- 普通导出文件：默认生命周期
- 用户显式收藏的附件：提升为 `retained`

### 12.2 清理策略

- Core 定时清理过期上传草稿
- 清理失效下载票据
- Agent 清理已成功上传的本地缓存文件

## 13. 推荐落地顺序

### Phase 1

- PostgreSQL 持久化核心对象
- Attachment metadata 表
- 基础对象存储接入

### Phase 2

- Agent / Client upload ticket
- attachment.complete
- download ticket

当前进度补充：

- `client` 侧 upload ticket / upload / complete / download ticket 已落地
- 第二版第一批仍使用服务端本地 attachment store 作为对象存储占位实现
- Desktop Agent uploader 与真正对象存储接入留待下一批

进一步进度补充：

- 第二版后续批次已引入 object store 抽象与 `s3_compatible` 后端实现位点
- 当前仍通过 Core 代理下载 attachment 内容；预签名 URL 将在后续批次评估

### Phase 3

- Desktop Agent 离线附件缓存
- 批量补同步

### Phase 4

- 生命周期清理
- 更细粒度权限与审计

## 14. 对当前仓库的指导

- `user/*.json` 不再适合作为长期权威业务数据存储。
- 当前内存、任务、配置、附件都应逐步迁到服务端持久化。
- 现有消息流不应继续承载大附件内容本体，只承载附件引用。

## 15. 待决问题

- 是否需要为 MQTT pull 模式附件下载增加预拉取缓存。
- 附件生命周期是否允许按 workspace override。
