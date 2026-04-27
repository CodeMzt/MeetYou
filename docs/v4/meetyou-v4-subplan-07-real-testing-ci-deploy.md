# V4 细分计划 07：真实测试 / CI / Deploy / Feishu / WeChatBot

## 目标

确保 V4 不只是在单元测试中可用，而是在真实本地环境、真实远程 Core、真实 Desktop、真实外部通知渠道中可用。此计划必须在所有功能基本完成后执行，且不能在中途停止。

---

## 测试阶梯

必须按顺序执行：

```text
1. 本地基础测试
2. 本地真实 Core + Desktop 测试
3. 提交、推送、合并 main
4. GitHub Actions CI 通过
5. GitHub Actions Deploy 通过
6. 远程 Core 健康检查和版本确认
7. 本地 Desktop 连接远程 Core 真实测试
8. Feishu 真实投递 + 人类确认
9. WeChatBot 真实投递 + 人类确认
10. 写测试报告
```

---

## 1. 本地基础测试

运行后端测试：

```bash
python -m pytest -q
```

按仓库实际情况补充：

```bash
python -m pytest tests/core tests/gateway tests/desktop_client tests/edge_client -q
```

前端如果存在：

```bash
npm test
npm run typecheck
npm run build
```

如脚本不存在，不能直接跳过；应检查 package.json / pyproject / README，找到正确脚本或补齐必要脚本。

---

## 2. 本地真实测试

启动真实组件：

```text
PostgreSQL / test DB
Core service
Desktop backend
UI
optional Edge
```

必须测试：

```text
/endpoint/ws connect
endpoint capabilities registration
Thread create/list
user message -> Run
streaming delta
assistant.progress_notice
final assistant message
core.local tool
Desktop executor file/shell tool
Operation update
system.heartbeat trigger
enable/disable heartbeat
modify heartbeat interval
user scheduled job create/edit/delete/trigger
Desktop disconnect/reconnect continue Thread
```

记录日志和结果。

---

## 3. 提交、推送、合并 main

完成本地基础 + 真实测试后：

```bash
git status
git add ...
git commit -m "refactor: implement MeetYou V4 endpoint runtime"
git push
```

然后创建 PR 或按项目流程合并到 main。

不得在未合并 main 前声称远程 Core 已更新。

---

## 4. GitHub Actions CI + Deploy

合并到 main 后会触发 GitHub Actions。

要求：

```text
CI job success
Deploy job success
```

两者都通过后，才能认为远程 Core 已成功更新代码。

如果 CI 失败：

```text
查看日志 -> 修复 -> push -> 等待重新跑 -> 直到通过
```

如果 Deploy 失败：

```text
查看日志 -> 修复部署或代码 -> push -> 等待重新跑 -> 直到通过
```

不能停在 CI 通过但 Deploy 失败。

---

## 5. 远程 Core 验证

Deploy 通过后，测试：

```text
/health
/version or build sha endpoint if available
/endpoint/ws connectivity
system.heartbeat job exists
```

如果没有 version endpoint，建议实现：

```text
GET /version
returns git_sha, build_time, protocol_version
```

---

## 6. 本地 Desktop 连接远程 Core 真实测试

本地 Desktop 配置指向远程 Core。

必须测试：

```text
Desktop endpoint.hello
UI endpoint subscription
创建 Thread
真实对话
streaming
progress_notice
file.read / shell policy test
system.heartbeat delivery
user scheduled job delivery
断线重连继续 Thread
```

这一步通过后，才能认为 V4 主链可用。

---

## 7. Feishu / WeChatBot 最后测试

### 7.1 为什么放最后

Feishu 和 WeChatBot 依赖外部凭证、外部服务和人类确认。它们不能替代核心架构测试，但最终验收必须真实通过。

### 7.2 Feishu 真实消息

发送唯一标识：

```text
[V4-REAL-TEST-FEISHU <timestamp> <random_suffix>] MeetYou V4 Feishu delivery test.
```

发送后必须使用人类提问工具：

```text
我刚才通过 MeetYou V4 发送了一条 Feishu 测试消息，唯一标识是 [V4-REAL-TEST-FEISHU ...]。请确认你是否收到；如果收到，请回复完整唯一标识或截图里的文本。
```

只有人类确认收到，才算通过。

### 7.3 WeChatBot 真实消息

发送唯一标识：

```text
[V4-REAL-TEST-WECHATBOT <timestamp> <random_suffix>] MeetYou V4 WeChatBot delivery test.
```

发送后必须使用人类提问工具：

```text
我刚才通过 MeetYou V4 发送了一条 WeChatBot 测试消息，唯一标识是 [V4-REAL-TEST-WECHATBOT ...]。请确认你是否收到；如果收到，请回复完整唯一标识或截图里的文本。
```

只有人类确认收到，才算通过。

### 7.4 凭证缺失处理

如果缺少凭证：

1. 使用人类提问工具请求凭证或请求是否允许暂时跳过。
2. 如果人类允许跳过，测试报告中明确标记为 human-approved skip。
3. 如果人类提供凭证，继续真实测试。
4. 不能在未提问的情况下自行跳过。

---

## 8. 测试报告

必须写入：

```text
docs/v4/test-report.md
```

内容：

```text
commit sha
CI run link/status
Deploy run link/status
remote Core health result
local Desktop -> remote Core result
Thread reconnect result
Scheduler / heartbeat result
ToolRouter result
Delivery / streaming result
Feishu result + human feedback
WeChatBot result + human feedback
known issues
```

---

## 9. 不能停止规则

不能停止在：

```text
基础测试通过
本地真实测试通过
push 完成
CI 通过
Deploy 通过但未测远程 Desktop
Feishu / WeChatBot 未确认
```

只有完成测试报告，才算结束。

---

## 验收

- [ ] 本地基础测试通过。
- [ ] 本地真实 Core + Desktop 测试通过。
- [ ] 已提交推送合并 main。
- [ ] GitHub Actions CI 通过。
- [ ] GitHub Actions Deploy 通过。
- [ ] 远程 Core 已确认更新。
- [ ] 本地 Desktop 指向远程 Core 真实测试通过。
- [ ] Feishu 真实投递并人类确认。
- [ ] WeChatBot 真实投递并人类确认。
- [ ] docs/v4/test-report.md 完成。
