# AGENTS

## 运行形态
- 仓库分为两部分：根目录的 Python service runtime，以及 `meetyou-ui/` 下的 Electron + Vite 前端。
- 当前后端正式入口是 `python main.py service`。不要再使用旧的 `python main.py gateway`；`docs/runtime-migration.md` 已确认该入口被移除。
- `python main.py` 仍会启动交互式 launcher；launcher 命令是 `start service`、`start cil`、`start ui`。

## 目录边界
- 后端运行时代码主要在 `core/`、`service_runtime/`、`gateway/`、`adapters/`、`tools/`、`sensors/`、`cil/`。
- `core/app.py` 是后端主装配点：在这里组装 EventBus、Brain、Heart、Memory、Tools、Session runtime 和 `FastAPIGateway`。
- `service_runtime/service.py` 是 `launcher` / `service` / `cil` 三种运行目标的总控入口。
- 前端入口分两层：`meetyou-ui/electron/main.ts` 负责 Electron 窗口，`meetyou-ui/src/main.tsx` 负责 renderer 路由装配。

## 本地配置与状态
- 密钥放在 `.env`，非敏感业务配置放在 `user/config.json`。
- `user/` 被视为本地运行态目录；`.gitignore` 会忽略 `user/*`，只保留 `*.example.json` 模板和 `user/README.md`。
- 默认服务地址是 `http://127.0.0.1:8000`；前端 `meetyou-ui/src/hooks/useMeetYou.ts` 默认连这个地址。
- Gateway 鉴权是可选的：未配置 access token 时，HTTP / WebSocket 不强制鉴权；配置后客户端可用 `Authorization: Bearer ...` 或 `X-API-Key`。

## 常用命令
- 后端安装：`python -m venv .venv`，然后 `.venv\Scripts\activate`，再执行 `pip install -r requirements.txt`
- 后端启动：`python main.py service`
- Launcher：`python main.py`
- CIL：`python main.py cil`
- 前端安装与开发：在 `meetyou-ui/` 下执行 `npm install`、`npm run dev`
- 前端校验：在 `meetyou-ui/` 下执行 `npm run typecheck`、`npm run test`
- 前端构建：在 `meetyou-ui/` 下执行 `npm run build`
- 后端测试：在仓库根目录执行 `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`

## 验证约定
- 后端改动优先跑对应的单个 `unittest` 测试文件；改动范围较大时再跑完整 discover。
- 前端改动至少执行 `npm run typecheck` 和 `npm run test`。
- 仓库里没有已配置好的 lint 命令、pre-commit 或 CI workflow，不要在说明里假设这些检查存在。

## 平台注意事项
- 项目整体偏 Windows：README、launcher、`.cmd` 脚本、`uiautomation`、PowerShell 拉起方式、Electron 窗口行为都默认按 Windows 使用。
- `launcher.py` 会先探测 `GET /health`，确认 service 可用后再拉起 CIL 或 UI；如果要复现 launcher 行为，先保证 service 已启动。
