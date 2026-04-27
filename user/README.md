# User Templates

`user/` 鐢ㄤ簬鏈湴杩愯鎬侀厤缃€佺紦瀛樺拰鐘舵€佹枃浠躲€傜湡瀹炶繍琛屾枃浠堕粯璁よ `.gitignore` 蹇界暐锛涗粨搴撳彧淇濈暀鍙鍒剁殑妯℃澘銆?

甯哥敤妯℃澘锛?

- `config.example.json` -> `config.json`
- `config.docker.example.json` -> `config.json`锛圕ore Docker / Compose 璺緞锛?
- `tools.example.json` -> `tools.json`
- `core_mcp_servers.example.json` -> `core_mcp_servers.json`
- `mcp_servers.example.json` -> `mcp_servers.json`
- `cmd_policy.example.json` -> `cmd_policy.json`
- `source_catalog.example.json` -> `source_catalog.json`
- `memory_graph.example.json` -> `memory_graph.json`
- `feishu_chat_ids.example.json` -> `feishu_chat_ids.json`
- `desktop_client.example.json` -> `desktop_client.json`
- `edge_client.example.json` -> `edge_client.json`

涔熷彲浠ヤ娇鐢ㄥ垵濮嬪寲鑴氭湰锛?

- `python scripts/prepare_core_runtime.py --profile host`
- `python scripts/prepare_core_runtime.py --profile docker --output-root deploy/docker/runtime`
- `python scripts/check_core_runtime.py --profile host --env-file .env`
- `python scripts/check_core_runtime.py --profile docker --runtime-root deploy/docker/runtime`

`desktop_client.json` 甯哥敤瀛楁锛?

- `core_base_url`: Core Service 鍩哄湴鍧€锛況untime 浼氳浆鎹负 `GET /endpoint/ws`
- `core_access_token`: Desktop Client 璁块棶 Core 鐨勭粺涓€璁块棶浠ょ墝锛涗篃鍙敱 `MEETYOU_CLIENT_ACCESS_TOKEN` 鎴?`MEETYOU_GATEWAY_ACCESS_TOKEN` 鎻愪緵
- `gateway_access_token`: desktop backend 璁块棶 Core HTTP surface 鏃朵娇鐢ㄧ殑璁块棶浠ょ墝
- `client_id`: Desktop Endpoint Provider 唯一标识
- `display_name`: 鏄剧ず鍚嶇О
- `workspace_ids`: 褰撳墠 Endpoint Provider 声明鍔犲叆鐨?workspace 鍒楄〃
- `enabled_endpoint_tools`: Endpoint Provider 声明给 Core 的可执行 EndpointCapability tool key
- `read_roots`: 鏈湴鏂囦欢璇诲彇鏍圭洰褰?
- `trusted_write_roots`: 鏈湴鍐欏叆鍙俊鏍圭洰褰?
- `cmd_policy_path`: 鏈湴鍛戒护绛栫暐鏂囦欢璺緞
- `mcp_servers_path`: Desktop Client 鏈湴 MCP 閰嶇疆鏂囦欢璺緞
- `transport_profile`: 杩炴帴褰㈡€侊紝榛樿 `desktop_wss`
- `local_bridge_enabled`: 鏄惁寮€鍚?Electron UI 浣跨敤鐨勬湰鍦?`/desktop/*` HTTP / WS 鍏ュ彛
- `local_bridge_host` / `local_bridge_port`: 鏈湴 desktop backend 鐩戝惉鍦板潃锛岄粯璁?`127.0.0.1:38951`

`edge_client.json` 甯哥敤瀛楁锛?

- `core_base_url`: Core Service 鍩哄湴鍧€锛況untime 浼氳浆鎹负 `GET /endpoint/ws`
- `core_access_token`: Edge Client 璁块棶 Core 鐨勭粺涓€璁块棶浠ょ墝
- `client_id`: Edge Endpoint Provider 唯一标识
- `client_type`: 褰撳墠杈圭紭鎵ц鍣ㄧ被鍨嬶紝榛樿 `edge`
- `workspace_ids`: 鍏佽鍔犲叆鐨?workspace 鍒楄〃
- `enabled_endpoint_tools`: Endpoint Provider 声明给 Core 的可执行 EndpointCapability tool key
- `heartbeat_interval_seconds`: 蹇冭烦闂撮殧
- `transport_profile`: 杩炴帴褰㈡€侊紝榛樿 `edge_wss`

姝ｅ紡杩炴帴鍙ｅ緞锛?

- `desktop_client` 涓?`edge_client` 閮介€氳繃 `GET /endpoint/ws` + `meetyou.endpoint.ws.v4` 鎺ュ叆 Core
- 鎻℃墜甯т负 `endpoint.hello`、`endpoint.capabilities.snapshot`、`endpoint.ready`、`endpoint.heartbeat`
- directed tool 璋冪敤浣跨敤 `tool.call.request`銆乣tool.call.result`銆乣tool.call.error`
- 鍚屼竴 endpoint provider 鍏佽澶氭潯 `/endpoint/ws` 杩炴帴锛屾瘡鏉¤繛鎺ュ彲澹版槑鑷繁鐨勮闃呫€佷細璇濅笂涓嬫枃涓?endpoint capabilities
- 妗岄潰 UI 榛樿閫氳繃 `desktop_client` 鏆撮湶鐨?loopback `/desktop/*` API 涓庢湰鍦?backend 浜や簰
- 涓嶅啀瀛樺湪姝ｅ紡 `/agent/ws` 杩愯鏃讹紝涔熶笉鍐嶄娇鐢?`MEETYOU_AGENT_*` 璁块棶浠ょ墝

MCP 鏂囦欢杈圭晫锛?

- `core_mcp_servers.json`: 浠呯敤浜?Core 渚у畨鍏?MCP锛岄€傚悎鏈嶅姟绔彲杩愯涓斾笉渚濊禆缁堢鍦ㄧ嚎鐨勮兘鍔?
- `mcp_servers.json`: 浠呯敤浜?Desktop Client 鏈湴 MCP锛屼緷璧栨湰鏈虹幆澧冧笌鏈湴鏉冮檺杈圭晫
- 缂哄皯 `core_mcp_servers.json` 涓嶄唬琛?Desktop Client 鐨?`mcp_servers.json` 缂哄け
- Core 鑷韩鐨勮交閲忚繍琛屾椂宸ュ叿浠嶆槸 runtime-native tool锛屼笉闇€瑕侀厤缃埌 `core_mcp_servers.json`

杩愯鏃跺彲鑳借嚜鍔ㄧ敓鎴愶細

- `memory_tasks.json`
- `memory_tasks.json.bak`

棣栨鍒濆鍖栧缓璁嚦灏戝噯澶囷細

- `config.json`
- `tools.json`
- `cmd_policy.json`
- `source_catalog.json`
- `memory_graph.json`

