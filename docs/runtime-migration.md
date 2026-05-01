# Runtime Migration Notes V4

Current rule: /client/* and /client/ws are removed V3 surfaces. Do not register removed-response compatibility handlers; use /runtime/* for Runtime HTTP, /endpoint/ws for provider realtime, and /desktop/* only as the local Desktop bridge/proxy surface.
V4 鏄紑鍙戞湡鏇挎崲锛屼笉鍋?V3 鍏煎灞傘€?
## 宸茶縼绉诲叆鍙?
- Runtime HTTP: `/runtime/*`
- Endpoint realtime: `/endpoint/ws`
- Desktop local bridge: `/desktop/*`锛屽彧浠ｇ悊 `/runtime/*`銆乣/operator/*`銆乣/developer/*`

## 宸茶縼绉绘ā鍨?
- Client 姒傚康闄嶇骇涓?Endpoint Provider銆?- `source_client_id` / `target_client_id` 鏇挎崲涓?`origin_endpoint_id`銆乣target_endpoint_id`銆乣execution_target_id`銆?- `core.local` 鏄?Core 杩涚▼鍐?ExecutionTarget銆?- Delivery 鍙仛鎶曢€掞紝涓嶇敓鎴愬洖澶嶃€?- Streaming 璧?RunEventLog + Delivery fan-out銆?- Scheduler 鍙栦唬鏃?TaskManager 鍚庡彴璋冨害鎺у埗娴併€?- Procedure 鍒犻櫎锛屽鐢ㄥ伐浣滄祦鏀圭敤 SKILL銆?
## 閰嶇疆娉ㄦ剰

- `user/config.json` 鏄湰鍦拌繍琛岄厤缃紝secret 鏀?`.env`銆?- 鏈湴鐪熷疄娴嬭瘯濡傞渶閬垮紑杩滅▼ Core 閰嶇疆锛屽簲浣跨敤褰撳墠杩涚▼鐜鍙橀噺瑕嗙洊锛屼笉瑕佹敼鐪熷疄 `.env`銆?- Desktop Provider 浣跨敤 `user/desktop_client.json`銆?- Edge Provider 浣跨敤 `user/edge_client.json`銆?- Core-side MCP 涓?Desktop local MCP 鍒嗗埆浣跨敤 `user/core_mcp_servers.json` 鍜?`user/mcp_servers.json`銆?
## 楠岃瘉

杩佺Щ鐩稿叧鏀瑰姩鑷冲皯璺戯細

- backend unittest discovery
- migration / bootstrap tests
- endpoint protocol tests
- scheduler tests
- tool router tests
- delivery tests
- frontend typecheck / test / build
- 鏈湴 Core + Desktop + UI 鐪熷疄娴嬭瘯
