# Service Runtime Migration

## 鐮村潖鎬у彉鏇?

- 杩愯鍏ュ彛缁熶竴涓?`python main.py service`
- Launcher 鍛戒护鏀逛负 `start service`
- `enable_gateway` 宸插垹闄わ紝鏈嶅姟杩愯鏃跺缁堟墭绠?HTTP / WebSocket 缃戝叧
- `source_profiles` 宸插垹闄わ紝鐮旂┒鏉ユ簮鍙粠 `source_catalog_path` 鎸囧悜鐨勭洰褰曟枃浠惰鍙?
- 浠诲姟绯荤粺涓嶅啀浠?`memory_graph.json` 瀵煎叆 legacy `task` 璁板綍锛屾棫浠诲姟璁板綍浼氬湪璁板繂灞傚垵濮嬪寲鏃舵竻鐞?
- 涓昏矾寰勫伐鍏烽敊璇粺涓€涓虹粨鏋勫寲 `ToolCallResult.error`锛屼笉鍐嶄緷璧?`"Error: ..."` 瀛楃涓插绾?

## 鍗囩骇姝ラ

1. 灏嗘墍鏈夊惎鍔ㄨ剼鏈噷鐨?`python main.py gateway` 鏀逛负 `python main.py service`
2. 灏?Launcher 鑷姩鍖栬剼鏈噷鐨?`start gateway` 鏀逛负 `start service`
3. 浠?`user/config.json` 鍜岀幆澧冩ā鏉夸腑鍒犻櫎 `enable_gateway`
4. 灏嗘棫鐨?`source_profiles` 閰嶇疆杩佺Щ鍒?`user/source_catalog.json` 鐨?`default_source_profiles`
5. 濡傛灉鏈夎嚜瀹氫箟瀹㈡埛绔洿鎺ヨВ鏋愬伐鍏疯繑鍥炲€奸噷鐨?`"Error: ..."`, 鏀逛负璇诲彇缁撴瀯鍖栭敊璇璞￠噷鐨?`code`銆乣category`銆乣message`

## 鍏煎鎬ц鏄?

- `gateway_host`銆乣gateway_port`銆乣gateway_access_token` 缁х画淇濈暀锛屽畠浠弿杩扮殑鏄湇鍔″唴缃綉鍏抽€傞厤灞傜殑鐩戝惉涓庨壌鏉冮厤缃?
- 姝ｅ紡瀹㈡埛绔叆鍙ｄ粛鏄?`POST /thread/run/delivery APIs` 涓?`GET /endpoint/ws`
- 鏍硅矾寰勫吋瀹?surface 浠呬繚鐣欒縼绉婚敊璇垨杩囨浮鎬у彧璇昏兘鍔涳紝鍚庣画浼氱户缁敹缂?

## Core 鍚姩鑱岃矗

- `core/app.py` 鐨?`App.setup()` 鍦?Core 瀹屾垚渚濊禆瑁呴厤銆佺綉鍏冲惎鍔ㄥ苟杩涘叆 idle 鍚庯紝浼氫富鍔ㄥ悜 `EventBus.inbound_queue` 娉ㄥ叆涓€娆?`system:boot` 鍚姩娑堟伅
- 杩欐潯鍚姩娑堟伅浣跨敤 `start` prompt 鏋勯€狅紝鐩爣涓?broadcast锛屽苟鏍囪涓?transient boot event锛岀敤浜庤Е鍙?Core 鍚姩鍚庣殑棣栬疆鍞ら啋
- Launcher銆乻ervice 鍏ュ彛涓庡閮ㄥ鎴风鍙礋璐ｆ媺璧?Core锛沚oot 娑堟伅娉ㄥ叆鐨勮矗浠绘槑纭綊灞?Core 鍚姩闃舵鏈韩

