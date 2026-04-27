# MeetYou Core API Surfaces V2

## 1. 鏂囨。鐩殑

鏈枃妗ｅ畾涔?Core Service 瀵瑰鏆撮湶鐨?API 闈㈠垎灞傦紝閬垮厤鍐嶆妸鐢ㄦ埛鎺ュ彛銆佽澶囨帴鍙ｃ€佽繍缁存帴鍙ｃ€佽皟璇曟帴鍙ｆ贩鍦ㄥ悓涓€濂?surface 涓€?
鐩爣锛?
- Client銆丄gent銆丱perator銆丏eveloper 鍚勮蛋鍚勭殑鍏ュ彛涓庨壌鏉冩ā鍨?- 鍓嶇鍙緷璧栫ǔ瀹氱敤鎴烽潰锛屼笉榛樿渚濊禆璋冭瘯闈?- 璁╄法浼氳瘽鍗忎綔銆佸鎵广€侀檮浠躲€丄gent 璋冨害閮芥嫢鏈夋竻鏅拌祫婧愭ā鍨?
## 2. 璧勬簮妯″瀷

V2 鎺ㄨ崘鐨勬牳蹇冭祫婧愶細

- `thread`
- `session`
- `message`
- `operation`
- `approval`
- `attachment`
- `workspace`
- `agent`
- `task`
- `memory`

## 3. Client API

### 3.1 鐢ㄩ€?
闈㈠悜锛?
- Electron UI
- 椋炰功
- 鏈潵鎵嬫満 App

### 3.2 涓昏璧勬簮

- `threads`
- `sessions`
- `messages`
- `operations`
- `approvals`
- `attachments`
- `workspaces`
- `tasks`
- `memory`

### 3.3 鍏抽敭鑳藉姏

- 鍙戦€佹秷鎭?- 鍒涘缓鎴栧姞鍏?thread
- 璁㈤槄 thread 浜嬩欢娴?- 鍙戣捣 operation
- 鏌ョ湅 operation 杩涘害銆佺粨鏋溿€侀檮浠?- 鎻愪氦瀹℃壒缁撴灉
- 鍒囨崲 workspace
- 鏌ョ湅 `user_todo` 涓?`assistant_schedule` 涓ょ被浠诲姟缁撴灉
- 鑾峰彇绠＄悊椤垫墍闇€鐨?workspace / procedure / operation / approval / pending human input 鑱氬悎鏁版嵁

### 3.4 寤鸿绔偣杞粨

- `POST /client/threads`
- `POST /client/sessions`
- `POST /client/messages`
- `POST /client/operations`
- `GET /client/operations/{operation_id}`
- `POST /client/approvals/{approval_id}/decision`
- `GET /client/procedures`
- `GET /client/procedures/{procedure_id}`
- `GET /client/threads/{thread_id}/procedure-context`
- `PUT /client/threads/{thread_id}/pinned-procedure`
- `DELETE /client/threads/{thread_id}/pinned-procedure`
- `GET /client/workspaces`
- `GET /client/workspaces/{workspace_id}/agents`
- `GET /client/tasks`
- `GET /client/memory/search`
- `POST /client/danxi/session/login`
- `GET /client/danxi/session`
- `PATCH /client/danxi/session/webvpn-cookie`
- `GET /client/danxi/profile`
- `GET /client/danxi/divisions`
- `GET /client/danxi/posts`
- `GET /client/danxi/posts/{hole_id}`
- `GET /client/danxi/posts/{hole_id}/floors`
- `POST /client/danxi/posts/{hole_id}/replies`
- `PATCH /client/danxi/floors/{floor_id}`
- `DELETE /client/danxi/floors/{floor_id}`
- `GET /client/danxi/posts/{hole_id}/summary`
- `GET /client/danxi/messages`
- `GET /endpoint/ws`

### 3.5 鍏抽敭鍘熷垯

- 涓嶆毚闇插簳灞?capability 鍐呴儴缁嗚妭缁欐櫘閫氱敤鎴烽潰
- 涓嶈鍓嶇榛樿渚濊禆 `/runtime/debug`
- 椋炰功涓?Electron 閮藉睘浜?Client API锛屽彧鏄氦浜掕兘鍔涗笉鍚?
### 3.6 Operation 璺敱璇箟

`POST /client/operations` 鐨勬寮忔墽琛岀洰鏍囨灇涓惧浐瀹氫负锛?
- `core_only`
- `specific_agent`
- `workspace_any_agent`
- `prefer_agent_fallback_core`

鍘熷垯锛?
- `execution_target` 鏄矾鐢辩瓥鐣ユ灇涓撅紝涓嶆槸鈥淎gent 鍒楄〃鈥濇帴鍙?- Client 鍙互琛ㄨ揪鐩爣鍋忓ソ锛屼絾涓嶈礋璐ｆ渶缁堥€夎矾
- Core 蹇呴』鍦ㄥ垱寤?`operation` 鍚庡畬鎴?capability routing
- 褰?`execution_target=specific_agent` 鏃讹紝`target_agent_id` 涓哄繀濉?- 褰?`execution_target` 涓哄叾浠栧€兼椂锛宍target_agent_id` 涓嶅簲鍐嶈褰撲綔姝ｅ紡蹇呭～瀛楁
- 褰?`execution_target` 涓虹┖鏃讹紝Core 鍙洖閫€鍒板綋鍓?workspace 鐨?`default_execution_target`

閰嶅绾﹀畾锛?
- `GET /client/workspaces/{workspace_id}/agents` 杩斿洖鐨勬槸褰撳墠 workspace 涓嬪湪绾垮彲璺敱鐨?Agent 鍒楄〃
- Client 鑻ラ渶瑕佹樉寮忓睍绀烘垨鎸戦€夌洰鏍?Agent锛屽簲浣跨敤璇ユ帴鍙ｏ紝鑰屼笉鏄妸 `execution_target` 褰撲綔鍊欓€夎妭鐐归泦鍚?
琛ュ厖绾﹀畾锛?
- `capability_id` 鏃㈠彲浠ユ槸鍏蜂綋 capability id锛屼篃鍙互鏄ǔ瀹氱殑鎶借薄 capability key
- 褰撲紶鍏ユ娊璞?capability key 鏃讹紝Core 闇€瑕佸厛瀹屾垚 workspace 鍐呭€欓€?agent 閫夋嫨锛屽啀瑙ｆ瀽涓虹洰鏍?agent 鐨勫叿浣?capability

琛ュ厖绾﹀畾锛?
- `procedure_call` 鐜板湪鍙互閫氳繃 `procedure_id` 鎺ㄥ preferred capability ref锛屽苟杩涘叆鍚屼竴濂?capability routing 涓婚摼
- scheduled task 鎵ц涓婁笅鏂囦篃鍙互鎼哄甫 preferred capability ref 涓?routing preference锛屼絾褰撳墠浠嶇敱鍚庡彴鎵ц璺緞娑堣垂锛岃€岄潪缁忕敱 `client/operations` 鐩存帴鍒涘缓

### 3.7 Workspace Surface

`GET /client/workspaces` 涓?`GET /operator/workspaces` 褰撳墠鑷冲皯搴旀毚闇诧細

- `workspace_id`
- `title`
- `description`
- `base_mode`
- `prompt_overlay`
- `default_execution_target`
- `capability_policy`
- `allowed_capability_ids`
- `preferred_agent_ids`
- `preferred_agent_types`
- `preferred_source_profiles`
- `agent_routing_policy`
- `memory_ranking_policy`
- `capability_routing_overrides`

琛ュ厖鍘熷垯锛?
- `base_mode` 鏄秷鎭叆鍙ｅ湪鏈樉寮忔寚瀹?mode 鏃剁殑榛樿鍊?- `default_execution_target` 鏄?operation 鍏ュ彛鍦ㄦ湭鏄惧紡鎸囧畾鎵ц鐩爣鏃剁殑榛樿鍊?- `prompt_overlay` 浼氳繘鍏?prompt 缁勮閾捐矾锛屼綔涓?workspace policy 鐨勪竴閮ㄥ垎
- 褰?workspace 鍚敤 `capability_policy=allowlist` 鏃讹紝鏄惧紡 `capability_call` 蹇呴』婊¤冻 allowlist 绾︽潫
- 褰?operation 浣跨敤 `workspace_any_agent` 鏃讹紝Core 鍙緷鎹?workspace `preferred_agent_ids` 涓?owner-client affinity 鑷姩琛ュ嚭鐩爣 agent
- 褰?workspace 閰嶇疆 `preferred_agent_types` 涓?`agent_routing_policy` 鏃讹紝Core 浼氭妸杩欎簺瀛楁绾冲叆鑷姩閫夎矾鎺掑簭
- 褰?workspace 閰嶇疆 `preferred_source_profiles` 鏃讹紝Core 浼氭妸杩欎簺鏉ユ簮鍋忓ソ娉ㄥ叆娑堟伅璺敱娌荤悊锛沺rocedure 鐨勬帹鑽愭潵婧愪粛浼樺厛浜?workspace 鍋忓ソ
- 褰撳墠 `memory_ranking_policy` 宸插叕寮€涓?workspace surface 瀛楁锛沄1 浠呮敮鎸?`workspace_first`
- 褰?workspace 閰嶇疆 `capability_routing_overrides` 鏃讹紝Core 浼氬鐗瑰畾 capability ref/abstract key 浼樺厛搴旂敤 capability 绾?override
- Electron 鐙珛鈥滃伐浣滃尯涓庤绋嬧€濈鐞嗛〉搴斿鐢ㄨ繖浜涘瓧娈典綔涓虹湡婧愶紝涓嶅簲鍦ㄥ墠绔淮鎶ょ浜屽 workspace 娌荤悊鐘舵€?
### 3.8 Task Surface And Heart Semantics

`task` 璧勬簮褰撳墠闇€瑕佹樉寮忓尯鍒嗕袱涓煙锛?
- `user_todo`锛氱敤鎴疯嚜宸辩殑寰呭姙瀵硅薄锛屽彲鎼哄甫 deadline/priority 绛夎涔夛紝浣嗕笉浼氬洜鑷劧璇█鏃堕棿鎻忚堪琚?`Core Heart` 鑷姩 claim
- `assistant_schedule`锛氬姪鎵嬫嫢鏈夌殑瀹氭椂缂栨帓瀵硅薄锛屽繀椤诲甫 trigger 璇箟锛屼細杩涘叆 `Core Heart` 鐨?`scheduler loop`锛屽苟鍦ㄨЕ鍙戞椂鍒涘缓鎴栧鐢ㄦ寮?operation

琛ュ厖鍘熷垯锛?
- `Core Heart` 鏄湇鍔＄鏃堕棿缂栨帓涓灑锛屼笉灞炰簬 Client 鎴?Agent transport surface
- `scheduler loop` 璐熻矗纭畾鎬х殑 claim / pre-create operation / control event
- `heartbeat reasoning loop` 璐熻矗鏍规嵁 `pending_redelivery`銆乣awaiting_completion`銆侀€炬湡 follow-up 绛夌粨鏋勫寲鐘舵€佸垽鏂槸鍚﹀瓨鍦ㄦ椂闂村帇鍔?- `/agent/ws` 涓婄殑 `agent.heartbeat` 鍙礋璐?agent 鍦ㄧ嚎鐘舵€佷笌杩愯鎸囨爣锛屼笉绛夊悓浜庝笂杩?Heart 鏃堕棿缂栨帓

### 3.9 Danxi Surface

Danxi 浜岄樁娈典粛褰掑睘 `Client API`锛屼絾浣滀负涓€缁勬湁鏄庣‘瀹夊叏杈圭晫鐨勫瓙鍩熻祫婧愬瓨鍦ㄣ€?
褰撳墠绾﹀畾锛?
- Danxi 鐧诲綍銆佷細璇濈姸鎬併€乄ebVPN cookie 鏇存柊銆佺敤鎴蜂俊鎭€佸笘瀛?妤煎眰璇诲彇銆佸洖澶嶇紪杈戝垹闄ゃ€丄I 鎽樿涓庣珯鍐呮秷鎭粺涓€鏀跺彛鍦?`/client/danxi/*`
- Danxi 鐙珛绐楀彛涓?`danxi` mode 鍔╂墜鍏变韩鍚屼竴鏈嶅姟绔?Danxi 浼氳瘽锛屼笉鍏佽鍓嶇鍜屽姪鎵嬪悇鑷淮鎶ょ嫭绔嬬櫥褰曟€佺湡鐩告簮
- 闈炴牎鍥綉璁块棶鎸夆€滃厛 1 绉掔洿杩炴帰娴嬶紝澶辫触鍚?WebVPN URL 浠ｇ悊鈥濇墽琛岋紱鏄惁璧?`webvpn` 鐢变細璇濈姸鎬佽繑鍥炵粰 UI锛岃€屼笉鏄鍓嶇鑷鐚滄祴
- `POST /client/danxi/session/login` 涓?`PATCH /client/danxi/session/webvpn-cookie` 鍙帴鍙?`encrypted_credentials`锛汦lectron main 鍦ㄦ湰鍦颁娇鐢ㄥ叡浜瘑閽ュ拰 purpose 娲剧敓 key 鍋?`aes-256-gcm` 鍔犲瘑灏佽锛孏ateway 缂哄皯瀵嗘枃瀛楁鏃剁洿鎺ユ嫆缁濊姹傦紝骞朵笖鍙湪 purpose 鍖归厤鏃惰В瀵?- 鍔犲瘑 purpose 褰撳墠鍥哄畾涓?`danxi.client.login.v1` 涓?`danxi.client.webvpn_cookie.v1`锛涘墠鍚庣涓嶅緱闅忔剰澶嶇敤鎴栨贩鐢?purpose
- Danxi JWT銆乺efresh token銆乄ebVPN cookie 涓庡繀瑕佺敤鎴疯祫鏂欎細鍦ㄦ湇鍔＄閫氳繃鍔犲瘑灏佽鍐欏叆鐘舵€佸悗绔紱鎭㈠鍚庣殑浼氳瘽鍦ㄩ娆¤鍙栨椂蹇呴』鍋氫竴娆′綆椋庨櫓鏈夋晥鎬ф牎楠岋紝鑻ョ‘璁よ繃鏈熴€佹挙閿€鎴栨崯鍧忓垯绔嬪嵆娓呯悊
- 鏃ュ織銆侀敊璇璞′笌璋冭瘯杈撳嚭涓嶅緱鏆撮湶 email銆乸assword銆乧ookie銆乼oken 绛夋槑鏂囧瓧娈碉紱娴嬭瘯涓庢枃妗ｄ篃搴旀部鐢?`encrypted_credentials` 鍙ｅ緞锛岃€屼笉鏄ず渚嬪寲鏄庢枃璺ㄨ竟鐣屼紶杈?
## 4. 璺ㄤ細璇濆崗浣?
杩欐槸 V2 鐨勬柊澧為噸鐐广€?
### 4.1 绾跨▼妯″瀷

- `thread` 鏄法 session 鐨勯€昏緫浼氳瘽
- `session` 鏄煇涓叿浣?Client 鐨勮繍琛屽疄渚?
### 4.2 鎿嶄綔妯″瀷

- `operation` 鐙珛浜庢煇涓叿浣?session
- 涓€涓?operation 鍙互琚涓?Client 瑙傚療

### 4.3 绀轰緥

鐢ㄦ埛鍦ㄩ涔﹀彂閫侊細

- 鈥滃幓妗岄潰鐢佃剳涓婃墽琛屾煇鎿嶄綔骞跺洖涓€寮犳埅鍥锯€?
Core 灏嗭細

- 鍦ㄥ綋鍓?thread 涓嬪垱寤?operation
- 鎶?operation 璺敱鍒?Desktop Agent
- 鎶婃埅鍥鹃檮浠舵寕鍒?operation
- 鎶婄粨鏋滄帹閫佺粰椋炰功鍜屾闈?UI 涓婂叧娉ㄨ thread 鐨?session

## 5. Agent API

### 5.1 鐢ㄩ€?
闈㈠悜锛?
- Desktop Agent
- Edge Agent
- Bridge Agent

### 5.2 涓昏璧勬簮

- `agent websocket registration`
- `capability snapshots`
- `capability calls`
- `agent attachment upload tickets`
- `agent attachment content`

### 5.3 寤鸿绔偣 / 閫氶亾杞粨

- `WSS /agent/ws`
- `POST /agent/attachments/upload-ticket`
- `PUT /agent/attachments/upload/{ticket_id}`
- `POST /agent/attachments/{attachment_id}/complete`
- `GET /agent/attachments/content/{attachment_id}?ticket_id=...`

褰撳墠鍙ｅ緞琛ュ厖锛?
- Agent 娉ㄥ唽閫氳繃 `agent.hello -> agent.hello.ack -> agent.capabilities.snapshot -> agent.ready` 鍦?`WSS /agent/ws` 涓婂畬鎴愶紝涓嶅瓨鍦ㄧ嫭绔?`POST /agent/register` 姝ｅ紡鍏ュ彛
- `desktop-agent` 涓?`edge-agent` 鍏辩敤鍚屼竴鏉?`WSS /agent/ws` 涓婚摼涓?`meetyou.agent.v1` envelope锛屽樊寮傞€氳繃 `agent_type` 涓?`transport_profile` 鍖哄垎
- Agent HTTP 闈㈠綋鍓嶄富瑕佺敤浜庨檮浠剁エ鎹€佷笂浼犮€佸畬鎴愪笌鍥炶锛涚绾垮洖鎵ф帴鍙ｄ粛灞炰簬鍗忚棰勭暀锛屼笉搴斿湪鏂囨。涓〃杩颁负宸茶惤鍦版寮忕鐐?- Agent 閴存潈涓?Client 閴存潈鍒嗙锛涘惎鐢ㄥ悗 Agent HTTP / WebSocket 鎺ュ彈 `Authorization: Bearer ...`銆乣X-API-Key`锛學ebSocket 涔熷吋瀹?`access_token` query

璇箟缁嗚妭瑙?`docs/agent-protocol-v1.md`銆?
## 6. Operator API

### 6.1 鐢ㄩ€?
闈㈠悜锛?
- 閮ㄧ讲涓庤繍缁?- 閰嶇疆绠＄悊
- Agent 绠＄悊
- 瀹夊叏绠＄悊

琛ュ厖鍘熷垯锛?
- `GET /operator/source-profiles` 鏄?workspace source-profile 鍋忓ソ鐨勫彈鎺х洰褰曠湡婧愶紝UI 涓嶅簲鑷鍙戞槑 profile 鍚?- `PATCH /operator/workspaces/{workspace_id}` 鍐欏叆 `preferred_source_profiles` 涓?`memory_ranking_policy` 鏃堕渶瑕佺粡杩囨湇鍔＄鏍￠獙

### 6.2 涓昏璧勬簮

- `config`
- `health`
- `agent registry`
- `background jobs`
- `tokens`
- `audit logs`

### 6.3 寤鸿绔偣杞粨

- `GET /operator/health`
- `GET /operator/config`
- `PATCH /operator/config`
- `GET /operator/source-profiles`
- `PATCH /operator/workspaces/{workspace_id}`
- `GET /operator/agents`
- `POST /operator/agents/{agent_id}/disable`
- `GET /operator/audit`

## 7. Developer API

### 7.1 鐢ㄩ€?
闈㈠悜寮€鍙戣皟璇曪紝涓嶅睘浜庨粯璁や骇鍝侀潰銆?
### 7.2 涓昏璧勬簮

- `route decisions`
- `capability sets`
- `authorization previews`
- `request diagnostics`
- `usage snapshots`
- `compression snapshots`
- `checkpoints`

### 7.3 鍘熷垯

- `/runtime/debug` 涓嶅啀瑙嗕綔鏅€氬墠绔帴鍙?- 榛樿涓?UI 涓嶅簲甯告€佷緷璧?Developer API

## 8. 瀹℃壒 API

瀹℃壒灞炰簬 Client API 鐨勯噸瑕佽祫婧愶紝浣嗘湰韬槸鐙珛棰嗗煙妯″瀷銆?
### 8.1 瀹℃壒娴?
1. Core 鍒涘缓 `approval`
2. 涓€涓垨澶氫釜 Client 鏀跺埌瀹℃壒璇锋眰
3. 鏌愪釜鍏峰鏉冮檺鐨?Client 鎻愪氦鍐崇瓥
4. Core 鍐冲畾鏀捐銆佹嫆缁濇垨瓒呮椂鍏抽棴

琛ュ厖鍘熷垯锛?
- WebSocket 涓殑 `confirm.requested` / `confirm.resolved` 鍙槸鎶曢€掍簨浠讹紝涓嶆槸鐪熺浉婧?- 鐪熺浉婧愬缁堟槸 `approval` 涓?`operation` 璧勬簮

### 8.2 鑱婂ぉ纭娴佷笌 Approval 瀵归綈

涓哄吋瀹圭幇鏈夊鎴风浜や簰锛岃亰澶╃‘璁や粛淇濈暀 `confirm.requested` / `confirm.resolved` 浜嬩欢鍗忚锛?浣嗚鍗忚涓嬬殑纭璇锋眰涓庣‘璁ゅ喅绛栧凡瑕佹眰鍏宠仈姝ｅ紡 `Approval` 璧勬簮銆?
琛ュ厖绾﹀畾锛?
- `confirm.requested` 鍙惡甯?`approval_id`銆乣approval_status`銆乣approval_type`銆乣risk_level`銆乣operation_id`
- `POST /client/sessions/{session_id}/confirm-response` 鐢ㄤ簬浠ヨ祫婧愯涔夋彁浜ょ‘璁ょ粨鏋滐紝閬垮厤浠呬緷璧?websocket 鍔ㄤ綔璇箟
- websocket `confirm_response` 浠嶄繚鐣欏吋瀹癸紝浣嗗悗缁細閫愭鏀舵暃涓鸿祫婧愯涔夊叆鍙ｄ紭鍏?- `POST /client/approvals/{approval_id}/decision` 鐜板凡鎴愪负鑱婂ぉ纭 approval 鐨勯閫夊喅绛栧叆鍙?
琛ュ厖绾﹀畾锛?
- 鍏变韩 client SDK / adapter 搴斾紭鍏堣皟鐢ㄨ祫婧愯涔夊叆鍙ｏ紝鑰屼笉鏄?websocket action
- Feishu / CIL 绛?channel adapter 涔熷簲澶嶇敤鍏变韩 client SDK 鐨勮祫婧愯涔夋柟娉?- 鏈湴鍏煎 adapter / route 濡備粛闇€妗ユ帴鍒?EventBus锛屽簲浼樺厛閫氳繃缁熶竴浜や簰鍝嶅簲鏈嶅姟锛岃€屼笉鏄洿鎺ヨ皟鐢?`EventBus.submit_*`
- 鏈湴鍏煎 adapter / route 濡傞渶璇诲彇 pending 鐘舵€侊紝涔熷簲浼樺厛閫氳繃缁熶竴浜や簰鍝嶅簲鏈嶅姟锛岃€屼笉鏄洿鎺ヨ鍙?`EventBus` 鍐呴儴瀛楁

### 8.4 Procedure Read-Only Surface And Governance Callback

- `GET /client/procedures` 杩斿洖鍙 procedure catalog 鐨勬憳瑕佸垪琛?- `GET /client/procedures/{procedure_id}` 杩斿洖 procedure 鍐呭瑙嗗浘闇€瑕佺殑瀹屾暣瀛楁锛屼緥濡?`prompt_overlay`銆乣recommended_source_profiles` 涓?routing 鍋忓ソ
- `GET /client/threads/{thread_id}/procedure-context` 杩斿洖 thread 褰撳墠鐨?`pinned_procedure`銆佹渶杩戜竴娆?`latest_inferred_procedure`銆佸綋鍓?`effective_procedure` 浠ュ強鏉ユ簮 `source`
- `PUT /client/threads/{thread_id}/pinned-procedure` 涓?`DELETE /client/threads/{thread_id}/pinned-procedure` 鐢ㄤ簬鐢ㄦ埛鏄惧紡鍥哄畾 / 鍙栨秷鍥哄畾褰撳墠 thread 鐨?procedure
- AI 鍙戣捣鐨?Procedure `create / update / delete` 浠嶉€氳繃纭鍥炶皟娌荤悊锛涘綋鍓嶅疄鐜板鐢ㄧ幇鏈?confirmation + approval 涓婚摼锛岃€屼笉鏄负 procedure 鍐嶅崟鐙紩鍏ョ浜屽纭鍗忚

### 8.3 Human Input 鎻愪氦

- `human_input.requested` / `human_input.resolved` 浜嬩欢鍗忚缁х画淇濈暀
- `POST /client/sessions/{session_id}/human-input-response` 鐜板凡鎴愪负琛ュ厖杈撳叆鐨勯閫夋彁浜ゅ叆鍙?- websocket `input_response` 浠嶄繚鐣欏吋瀹癸紝浣嗕笉鍐嶆槸棣栭€夎祫婧愬叆鍙?
琛ュ厖绾﹀畾锛?
- 鍏变韩 client SDK / adapter 搴斾紭鍏堣皟鐢?`POST /client/sessions/{session_id}/human-input-response`
- Feishu / CIL 绛?channel adapter 涔熷簲澶嶇敤鍏变韩 client SDK 鐨勮祫婧愯涔夋柟娉?- 鏈湴鍏煎 adapter / route 濡備粛闇€妗ユ帴鍒?EventBus锛屽簲浼樺厛閫氳繃缁熶竴浜や簰鍝嶅簲鏈嶅姟锛岃€屼笉鏄洿鎺ヨ皟鐢?`EventBus.submit_*`
- 鏈湴鍏煎 adapter / route 濡傞渶璇诲彇 pending 鐘舵€侊紝涔熷簲浼樺厛閫氳繃缁熶竴浜や簰鍝嶅簲鏈嶅姟锛岃€屼笉鏄洿鎺ヨ鍙?`EventBus` 鍐呴儴瀛楁

### 8.2 楂橀闄╁鎵规潵婧?
V2 鍏佽锛?
- Electron UI 瀹℃壒楂橀闄╁姩浣?- 椋炰功瀹℃壒楂橀闄╁姩浣?
鍓嶆彁鏄 Client 鍏峰楂橀闄╁鎵规潈闄愩€?
## 9. 闄勪欢 API

### 9.1 鍘熷垯

- 灏忔枃鏈彲鐩存帴璧颁富鍗忚
- 澶ч檮浠跺彧璧板璞″瓨鍌ㄩ€氶亾
- Client 涓?Agent 閮介€氳繃 Core 鐢宠瀵硅薄瀛樺偍绁ㄦ嵁

### 9.2 闄勪欢璧勬簮

- `attachment`
- `attachment_upload_ticket`
- `attachment_download_ticket`

### 9.3 寤鸿绔偣杞粨

- `GET /client/attachments?owner_type=...&owner_id=...`
- `GET /client/attachments/{attachment_id}`
- `DELETE /client/attachments/{attachment_id}`
- `POST /client/attachments/upload-ticket`
- `PUT /client/attachments/upload/{ticket_id}`
- `POST /client/attachments/{attachment_id}/complete`
- `GET /client/attachments/{attachment_id}/download-ticket`
- `GET /client/attachments/content/{attachment_id}?ticket_id=...`

褰撳墠瀹炵幇鐘舵€侊細

- `client` 渚?attachment 涓婚摼宸茶惤鍦?- `client` 渚у凡鏀寔鎸?owner 鍒楀嚭銆佽鍙?metadata銆佸垹闄?attachment锛屽苟杩斿洖 `created_at` / `updated_at` / `uploaded_at` / `completed_at` / `deleted_at` 绛夊叧閿椂闂存埑
- `agent` 渚?attachment uploader 宸茶惤鍦?- Core 宸叉妸 `list_attachments`銆乣read_attachment`銆乣delete_attachment` 浣滀负鍔╂墜宸ュ叿鏆撮湶锛涘伐鍏峰簲闈㈠悜 attachment domain锛岃€屼笉鏄洿鎺ユ搷浣?object store 璺緞
- tool / capability 浜у嚭鐨勯檮浠跺簲鍏堣繘鍏?`attachment_outputs`锛屽啀鐢?Core 褰掍竴鍖栦负缁熶竴 attachment object view锛汣lient UI 涓嶅簲鐩存帴娑堣垂 Agent 鍘熷 `local_path` 鎴栦复鏃朵笅杞介摼鎺?- Electron 鐙珛鈥滈檮浠剁鐞嗏€濋〉搴斿鐢ㄥ悓涓€濂?attachment domain API銆佹椂闂存埑瀛楁涓?download ticket 閫昏緫

### 9.4 Attachment Object View

褰撳墠鐢ㄦ埛闈㈠湪 message銆乷peration 涓庣鐞嗛〉涓簲澶嶇敤缁熶竴闄勪欢瀵硅薄瑙嗗浘锛岃€屼笉鏄緷璧?surface-specific payload銆?
寤鸿瀛楁锛?
- `attachmentId`
- `fileName`
- `kind`
- `mimeType`
- `sizeBytes`
- `downloadUrl`
- `lifecyclePolicy`

鍘熷垯锛?
- `attachment` 璧勬簮鏄湡鐩告簮锛宎ttachment object view 鏄粰 Client UI 鐨勭ǔ瀹氭姇褰辫鍥?- 鍚屼竴涓璞¤鍥惧彲琚?message銆乷peration銆佺鐞嗛〉澶嶇敤锛岄伩鍏嶆瘡涓潰鍚勮嚜鎷艰涓嬭浇閫昏緫
- 涓嬭浇浠嶅繀椤婚€氳繃 download ticket / 鏉冮檺鏍￠獙锛岃€屼笉鏄妸瀵硅薄瀛樺偍璺緞鐩存帴鏆撮湶缁?UI

## 10. 绠＄悊椤典笌鐘舵€佸弽棣?
### 10.1 绠＄悊椤佃亴璐?
褰撳墠 Electron 鐙珛鈥滃伐浣滃尯涓庤绋嬧€濈獥鍙ｅ睘浜?Client 姝ｅ紡浜у搧闈㈢殑涓€閮ㄥ垎锛屽叾鑱岃矗鍖呮嫭锛?
- 灞曠ず褰撳墠 workspace 姒傝涓庢不鐞嗗瓧娈?- 鎵挎帴鍙楁帶鐨?workspace 娌荤悊缂栬緫锛屼緥濡?source profile 鍋忓ソ涓?memory ranking policy
- 灞曠ず procedure catalog銆乨etail 涓?thread 褰撳墠 procedure context
- 鑱氬悎褰撳墠 thread / workspace 涓嬬殑杩愯涓?operation銆佸緟瀹℃壒涓庡緟琛ュ厖杈撳叆鐘舵€?
褰撳墠 Electron 鐙珛鈥滈檮浠剁鐞嗏€濋〉鍚屾牱灞炰簬 Client 姝ｅ紡浜у搧闈㈢殑涓€閮ㄥ垎锛屽叾鑱岃矗鍖呮嫭锛?
- 鎸?owner 鍒楀嚭 attachment
- 灞曠ず `created_at`銆乣uploaded_at`銆乣completed_at`銆乣deleted_at` 绛夊叧閿椂闂存埑
- 澶嶇敤 download ticket / delete attachment 涓婚摼锛岃€屼笉鏄洿鎺ユ嫾鎺ュ璞″瓨鍌ㄥ湴鍧€

鍘熷垯锛?
- 绠＄悊椤垫槸鐢ㄦ埛闈紝涓嶆槸 operator / developer 闈?- 瀹冩秷璐圭殑浠嶇劧鏄?`client/*` 涓庡繀瑕佺殑 `operator` 鍙楁帶鐩綍鎺ュ彛锛屼笉搴斿洖閫€鍒?`/runtime/debug`
- 绠＄悊椤靛睍绀虹殑鐘舵€佸繀椤讳笌涓荤獥鍙ｅ叡浜悓涓€濂?operation / approval / human input 鐪熺浉婧?
### 10.2 鐘舵€佸弽棣堟ā鍨?
褰撳墠鍓嶇鐘舵€佸弽棣堥噰鐢ㄥ弻灞傛ā鍨嬶細

- 椤跺眰鍙嶉锛歚StatusIsland` 璐熻矗灞曠ず杩炴帴鐘舵€併€佹€濊€冧腑 / 宸ュ叿璋冪敤涓瓑鍏ㄥ眬鍗虫椂鍙嶉
- 鎵ц鎬佸弽棣堬細operation 鍒楄〃璐熻矗灞曠ず `status`銆乣phase`銆乣detail`銆乣tone`銆乣summary` 涓?attachment object view
- 闄勪欢鍙嶉锛氫笂浼犳垚鍔?澶辫触绛夌灛鏃跺弽棣堢敱鐘舵€佸尯鎵挎帴锛屼笉鍐嶉粯璁ゅ悜鑱婂ぉ娴佹彃鍏モ€滀笂浼犳垚鍔熲€濈被绯荤粺娑堟伅

鍘熷垯锛?
- `StatusIsland` 鍙礋璐ｂ€滃綋鍓嶇郴缁熷ぇ鑷村湪鍋氫粈涔堚€濓紝涓嶆浛浠?operation 缁嗚妭闈?- operation 鐨?`tone/summary` 搴旀潵鑷湇鍔＄鐘舵€佸拰褰掍竴鍖栫粨鏋滐紝鑰屼笉鏄粎闈犲墠绔湰鍦扮寽娴?- 褰撻檮浠跺皻鏈畬鎴?upload / complete 鏃讹紝鍙嶉搴斿仠鐣欏湪 operation 鐘舵€佸眰锛屼笉搴旀彁鍓嶇敓鎴愬彲涓嬭浇 UI
- 鐙珛闄勪欢绠＄悊椤靛簲澶嶇敤鍚屼竴濂?attachment object view 涓庝笅杞界エ鎹€昏緫锛岃€屼笉鏄鍒跺彟涓€鏉￠檮浠舵ā鍨?
## 11. UI 瑕嗙洊鍘熷垯

涓?UI 闇€瑕佽鐩栫殑浜у搧鑳藉姏锛?
- threads / sessions / messages
- operations
- approvals
- workspaces
- tasks
- citations / attachments
- agent 鍦ㄧ嚎鐘舵€佹憳瑕?- 鐙珛绠＄悊椤典腑鐨?workspace / procedure / pending state 鑱氬悎瑙嗗浘

涓?UI 涓嶉渶瑕侀粯璁よ鐩栵細

- operator config
- developer diagnostics
- 鍘熷 capability 鐭╅樀

## 12. 瀵瑰綋鍓嶄粨搴撶殑鎸囧

- 鐜版湁 `gateway/api.py` 搴旈€愭鎷嗘垚鍥涚被 router锛岃€屼笉鏄户缁爢鍦ㄤ竴浠?API 鏂囦欢閲屻€?- 鏃?`/inputs`銆乣/controls`銆佹牴 `/ws` 绛夎縼绉婚敊璇?surface 搴斿崟鐙斁鍦?legacy 妯″潡锛屼笉搴旂户缁贩鍏ユ寮?router 瑁呴厤灞傘€?- 鍓嶇 `useMeetYou` 搴斿彧娑堣垂 Client API銆?- 閰嶇疆涓績銆乨ebug銆乺untime diagnostics 搴斾粠榛樿鑱婂ぉ璺緞涓垎绂汇€?- 闄勪欢鏄剧ず灞傚簲缁熶竴娑堣垂 attachment object view锛岃€屼笉鏄湪 message / operation / 绠＄悊椤靛悇鑷畾涔変笉鍚屼笅杞界粨鏋勩€?- 绠＄悊椤靛拰涓荤獥鍙ｇ殑鐘舵€佸弽棣堝簲澶嶇敤鍚屼竴濂?operation / approval / human input 鏁版嵁妯″瀷銆?
## 13. 寰呭喅闂

- 鏄惁瑕佹妸 `thread event stream` 鍜?`operation event stream` 鍒嗘垚涓ゆ潯 WS 璁㈤槄銆?- 椋炰功鏄惁闇€瑕佸崟鐙殑瀹℃壒鎽樿鏍煎紡锛屼互閫傞厤寮变氦浜掔晫闈€?
