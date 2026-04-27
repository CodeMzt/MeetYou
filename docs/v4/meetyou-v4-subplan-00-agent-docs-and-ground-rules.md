# V4 细分计划 00：AGENT / Docs / Ground Rules

## 目标

在任何代码重构前，先让 Codex、本地开发者和 CI 都能读到同一套 V4 规则。V4 是一次大换血，不做 V3 兼容，因此必须先更新 AGENT.md / AGENTS.md，避免后续自动实现时回到旧的 Client-centric 架构。

---

## 范围

必须处理：

```text
AGENT.md
AGENTS.md
README.md
docs/v4/design.md
docs/v4/plan.md
docs/v4/plans/*.md
```

如果仓库已有 V3 docs，不删除也可以，但必须标注：

```text
V3 docs are legacy. V4 implementation source of truth is docs/v4 and AGENT.md / AGENTS.md.
```

---

## 任务

### 1. 查找指令文件

```bash
find . -maxdepth 4 \( -name 'AGENT.md' -o -name 'AGENTS.md' \) -print
```

处理规则：

- 有 `AGENT.md`：更新。
- 有 `AGENTS.md`：同步更新。
- 两者都有：都更新，保持内容一致或明确互相引用。
- 两者都没有：创建根目录 `AGENT.md`，并创建 `AGENTS.md` 简短引用 `AGENT.md`，防止 Codex 只读取复数版本。

### 2. 写入 V4 Architecture Rules

必须包含：

```text
Core owns Thread / Message / Run / Scheduler / Heartbeat / Delivery.
Client is only Endpoint Provider.
Core is not Client.
Core endpoint is in-process execution/delivery target.
Scheduler owns system.heartbeat as non-deletable job.
endpoint.heartbeat is keepalive only.
short_reply is removed as directed tool.
assistant.progress_notice is a RunEvent / Runtime Action.
Delivery handles transport, not response generation.
ToolRouter resolves ExecutionTarget.
Permissions live on Actor / Workspace / RunPolicy.
Capabilities live on EndpointCapability.
No V3 compatibility.
No /client/ws.
No source_client_id / target_client_id in new runtime code.
```

### 3. 写入测试阶梯规则

必须包含：

```text
Do not stop after unit tests.
Do not stop after local tests.
After base tests, run real local Core + Desktop tests.
Then commit, push, merge to main.
Wait for GitHub Actions CI and Deploy.
Only after both pass, remote Core is considered updated.
Then start local Desktop against remote Core and run real tests.
Feishu and WeChatBot tests are last.
For Feishu / WeChatBot, send real unique messages and use the human question tool to ask whether the human received them.
Never assume external message delivery succeeded without human confirmation.
```

### 4. 创建 docs/v4

建议结构：

```text
docs/v4/design.md
docs/v4/plan.md
docs/v4/plans/00-agent-docs-and-ground-rules.md
docs/v4/plans/01-domain-schema-migration.md
docs/v4/plans/02-endpoint-protocol.md
docs/v4/plans/03-run-message-delivery-streaming.md
docs/v4/plans/04-tool-router-execution-target.md
docs/v4/plans/05-scheduler-heartbeat.md
docs/v4/plans/06-desktop-edge-ui.md
docs/v4/plans/07-real-testing-ci-deploy.md
```

---

## 测试

### 文档存在性

```bash
test -f AGENT.md || test -f AGENTS.md
test -f docs/v4/design.md
test -f docs/v4/plan.md
```

### 关键规则检查

```bash
grep -R "Core owns Thread" AGENT.md AGENTS.md docs/v4 README.md || true
grep -R "Client is only Endpoint Provider" AGENT.md AGENTS.md docs/v4 README.md || true
grep -R "assistant.progress_notice" AGENT.md AGENTS.md docs/v4 README.md || true
grep -R "Do not stop after unit tests" AGENT.md AGENTS.md docs/v4 README.md || true
```

### 禁止旧概念作为新规则出现

```bash
grep -R "Use /client/ws\|source_client_id as origin\|target_client_id as execution" AGENT.md AGENTS.md docs/v4 README.md || true
```

如果有输出，必须检查并改掉。

---

## 验收

- [ ] AGENT.md / AGENTS.md 更新或创建。
- [ ] docs/v4 创建。
- [ ] README 指向 V4 docs。
- [ ] 明确 V3 docs 是 legacy。
- [ ] 写入“基础测试后必须真实测试、CI/Deploy 后远程 Core 真实测试、Feishu/WeChatBot 最后用人类提问工具确认”的规则。
