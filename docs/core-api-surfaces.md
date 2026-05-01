# Core API Surfaces V4

Current rule: /client/* and /client/ws are removed V3 surfaces. Do not register removed-response compatibility handlers; new runtime work must use /runtime/*, /endpoint/ws, /desktop/*, /operator/*, or /developer/* according to the boundary below.
V4 鐨勫澶栨帴鍙ｆ寜鑱岃矗鍒嗗眰锛屼笉鍐嶄繚鐣?V3 Client surface銆?

## 姝ｅ紡鍏ュ彛

- Runtime HTTP facade: `/runtime/*`锛岄潰鍚?UI銆丏esktop 鏈湴妗ャ€佸閮?channel adapter 鐨勮祫婧愬叆鍙ｃ€?
- Endpoint WebSocket: `GET /endpoint/ws`锛屽崗璁悕 `meetyou.endpoint.ws.v4`锛岄潰鍚?Desktop銆丒dge銆丗eishu銆乄eChatBot銆亀ebhook 绛?Endpoint Provider銆?
- Desktop 鏈湴妗? `/desktop/*`锛屽彧浠ｇ悊 `/runtime/*`銆乣/operator/*`銆乣/developer/*`銆?
- Operator: `/operator/*`锛岀敤浜庨儴缃层€佸伐浣滃尯銆佽皟搴?Job 鍜屽彈鎺ф不鐞嗐€?
- Developer: `/developer/*`锛屽彧鐢ㄤ簬璋冭瘯鍜岃瘖鏂€?


## Runtime 璧勬簮

Core 鎷ユ湁浠ヤ笅璧勬簮鍜岃涔夛細Thread銆丮essage銆丷un銆丷unEvent銆丼cheduler銆丠eartbeat銆丮emory銆丱peration銆丏elivery銆丄ttachment銆丆ontextPool銆?

Runtime HTTP 涓昏璧勬簮锛?

- `POST /runtime/threads`
- `POST /runtime/sessions`
- `POST /runtime/sessions/{session_id}/confirm-response`
- `POST /runtime/sessions/{session_id}/human-input-response`
- `POST /runtime/sessions/{session_id}/reply-control`
- `POST /runtime/messages`
- `POST /runtime/operations`
- `GET /runtime/operations/{operation_id}`
- `POST /runtime/approvals/{approval_id}/decision`
- `GET /runtime/workspaces`
- `GET /runtime/workspaces/{workspace_id}/endpoints`
- `GET /runtime/context-pool/query`
- `POST /runtime/attachments/upload-ticket`
- `PUT /runtime/attachments/upload/{ticket_id}`
- `POST /runtime/attachments/{attachment_id}/complete`
- `GET /runtime/threads/{thread_id}/attachments`
- `GET /runtime/attachments/{attachment_id}/download-ticket`
- `GET /runtime/attachments/content/{attachment_id}`

`POST /runtime/messages` accepts `endpoint_message_id` for Endpoint Provider inbound idempotency. For the same thread, endpoint, role, and `endpoint_message_id`, Core returns the existing Message with `idempotent_replay=true` and does not enqueue another assistant run.

`POST /runtime/sessions/{session_id}/reply-control` is the V4 conversation control entrypoint for `stop`, `append_guidance`, `regenerate`, and `rollback`. UI surfaces must use this Runtime HTTP facade instead of sending bare control payloads over `/endpoint/ws`.

Danxi 璧勬簮涔熷湪 `/runtime/danxi/*` 涓嬨€傜櫥褰曞拰 WebVPN Cookie 鏇存柊鍙帴鍙楀姞瀵嗚浇鑽锋垨鏈嶅姟绔幆澧冨嚟鎹紝涓嶆帴鍙楁槑鏂囧瘑鐮併€丆ookie 鎴?token銆?

`GET /runtime/danxi/posts/{hole_id}/floors` exposes paginated replies with `offset` as a zero-based reply cursor and returns `next_offset` for the next page.
## Endpoint Protocol

Endpoint Provider 鍙彁渚涚鐐瑰拰鑳藉姏锛屼笉鎷ユ湁浼氳瘽銆佽繍琛屻€佽蹇嗐€佽皟搴︺€佹姇閫掓垨鏉冮檺璇箟銆?

V4 WebSocket frame锛?

- 鐢熷懡鍛ㄦ湡锛歚endpoint.hello`銆乣endpoint.capabilities.snapshot`銆乣endpoint.ready`銆乣endpoint.heartbeat`銆乣endpoint.goodbye`
- 璁㈤槄锛歚subscription.start`銆乣subscription.update`銆乣subscription.stop`
- 鎶曢€掞細`delivery.message`銆乣delivery.run_event`銆乣delivery.notice`銆乣delivery.operation_update`銆乣delivery.inbox_item`
- 宸ュ叿锛歚tool.call.request`銆乣tool.call.result`銆乣tool.call.error`銆乣tool.call.cancel`

`endpoint.heartbeat` 鍙仛杩炴帴淇濇椿锛屼笉瑙﹀彂 `system.heartbeat`銆?

## Message / Run / Delivery

- 鐢ㄦ埛杈撳叆鍏堣繘鍏?Core-owned Thread / Message銆?
- Run 鐢?Core 鍒涘缓锛屾祦寮忎簨浠跺啓鍏?RunEventLog銆?
- Delivery 鍙礋璐ｆ姇閫?`message`銆乣run_event`銆乣notice`銆乣operation_update`锛屼笉鐢熸垚鍥炲銆?
- Streaming 蹇呴』璧?RunEventLog + Delivery fan-out銆?
- 鏈€缁?assistant reply 蹇呴』鐢?MessageService 鎸佷箙鍖栦负 assistant Message銆?
- `assistant.progress_notice` 鏄?Runtime Action / RunEvent锛屼笉璧?ToolRouter锛屼笉鍒涘缓 Operation锛屼笉杩涘叆鏈€缁?assistant message銆?

## Tool / Execution

宸ュ叿璋冪敤缁熶竴璧?ToolRouter + ExecutionTarget锛?

- `core.local`: Core 杩涚▼鍐?ExecutionTarget锛屼笉鏄?Client銆?
- `endpoint`: 鎸囧畾 Endpoint 鑳藉姏銆?
- `workspace_any_endpoint`: 宸ヤ綔鍖哄唴鍙敤 Endpoint 閫夎矾銆?
- `prefer_endpoint_fallback_core`: 浼樺厛 Endpoint锛屽繀瑕佹椂鍥炶惤 Core銆?

鏉冮檺鎸傚湪 Actor / Workspace / RunPolicy锛涙墽琛岃兘鍔涙寕鍦?EndpointCapability銆?

## Scheduler / Heartbeat

Scheduler 鏄敮涓€绯荤粺绾ц皟搴︽椂閽熴€傛寔涔呭寲璧勬簮鏄?`scheduled_jobs` 鍜?`scheduled_job_runs`銆?

- `system.heartbeat` 鏄?Scheduler 棰勮绯荤粺 Job銆?
- `system.heartbeat` 涓嶅彲鍒犻櫎銆佷笉鍙墜鍔ㄥ垱寤恒€?
- `system.heartbeat` 鍙兘鍚仠鍜屼慨鏀?`interval_seconds`銆?
- 鏅€?scheduled job 鍙?CRUD銆佸惎鍋滃拰鎵嬪姩瑙﹀彂銆?
- 鏃?TaskManager 鍚庡彴鎺у埗娴佷笉鍐嶆墽琛?scheduled task / scheduled reminder銆?

## Workflow

Procedure 宸插垹闄ゃ€傚彲澶嶇敤宸ヤ綔娴佺粺涓€浣跨敤 SKILL锛?

- `list_skills` 鏌ユ壘鍙鐢ㄥ伐浣滄祦鎸囧銆?
- `load_skill` 娉ㄥ叆鍏蜂綋 SKILL銆?
- `create_skill` 鍙垱寤?SKILL锛屼笉鍒涘缓 Procedure銆?

鍏紑 assistant mode 浠呬负 `general`銆乣automation`銆乣danxi`銆傛棫 `normal`銆乣auto`銆乣documents`銆乣research`銆乣study` 褰掍竴鍒?`general`锛屾棫 `office` 褰掍竴鍒?`automation`銆?
