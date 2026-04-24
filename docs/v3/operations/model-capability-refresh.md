# Model Capability Refresh（模型能力刷新）

## 背景

模型 context window / max output token 不再依赖 `adapters/base.py` 的硬编码字典作为唯一来源。运行时改为 `ModelCapabilityResolver` 分层解析，避免新模型被静默误判为默认 8192。

## 来源优先级

1. **Provider API 优先**
   - Gemini: `models.get/list` 的 `inputTokenLimit`、`outputTokenLimit`。
   - Anthropic: Models API 的 `max_input_tokens` / `max_tokens`（若可用）。
   - Ollama: `/api/show` 的 `model_info` / `parameters(num_ctx)`。
2. **Provider 特例文档兜底**
   - DeepSeek: `/models` 不含 token limits，改走官方文档与版本化 registry。
   - OpenAI: `/models` 字段不稳定，优先官方 compare 页面与项目 versioned registry。
3. **最后默认值兜底**
   - 返回 `context_window=8192` 前必须附带 diagnostic warning（禁止静默）。

## 版本化 Registry

默认 registry 位于 `core/model_capabilities/default_registry.json`，字段包含：
- `provider`
- `model_pattern`
- `context_window`
- `max_output_tokens`
- `source_url`
- `source_checked_at`
- `confidence`
- `notes`

当前内置 DeepSeek v4 和 OpenAI gpt-5.4 家族基线映射。

## 运行态缓存

- 缓存路径：`user/model_capabilities_cache.json`（不纳入 Git 追踪）。
- 默认 TTL：24h。
- 支持手动刷新指定 provider/model，写入缓存并返回 old/new diff。

## 失败降级策略

- API/文档刷新失败：回退到 registry。
- registry 未命中：使用默认值并打 warning + low confidence + manual confirmation。
- 禁止采信“模型在对话中自报 token 上限”的结果作为可信来源。

## 手动刷新入口

内部服务方法：`App.refresh_model_capabilities(provider, model, ...)`。
返回值至少包括：
- `source`
- `old`
- `new`
- `is_trusted`
- `needs_manual_confirmation`
