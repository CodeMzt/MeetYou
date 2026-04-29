# Storage And Binary Transfer V4

附件和二进制内容由 Core 统一登记元数据，并通过对象存储票据完成上传、下载和删除。

## Runtime API

- `POST /runtime/attachments/upload-ticket`
- `PUT /runtime/attachments/upload/{ticket_id}`
- `POST /runtime/attachments/{attachment_id}/complete`
- `GET /runtime/threads/{thread_id}/attachments`
- `DELETE /runtime/attachments/{attachment_id}`
- `GET /runtime/attachments/{attachment_id}/download-ticket`
- `GET /runtime/attachments/content/{attachment_id}`

Desktop 本地桥只暴露 `/desktop/attachments/*` 代理，不使用旧 `/client/attachments/*`。

## 所有权

附件 owner 可以是 Thread、Message、Operation 或其他 Core 资源。Endpoint Provider 不拥有附件真相源，只能按票据上传或下载。

## Delivery

附件消息通过 MessageService 持久化，并由 Delivery 投递 `message` 或 `operation_update`。Delivery 不生成附件说明或 assistant 回复。

## 安全

- 上传票据和下载票据必须有过期时间。
- 删除操作应软删除记录并清理可清理对象。
- Danxi 凭据、WebVPN cookie、API token 不得以附件、日志、错误详情或测试样例明文暴露。
