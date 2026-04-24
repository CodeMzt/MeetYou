import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import UsagePanel from './UsagePanel'

describe('UsagePanel', () => {
  it('renders compact token and context summary for the main window', () => {
    const markup = renderToStaticMarkup(
      <UsagePanel
        variant="compact"
        runtimeDebugSnapshot={null}
        usageSnapshot={{
          session_id: 'sess_1',
          usage_ready: false,
          context_limit_tokens: 128000,
          context_limit_source: 'config_override',
          context_limit_model: 'gpt-5.4',
          context_limit_confidence: 'high',
          current_context_tokens_estimated: 4096,
          context_breakdown: {
            system: 256,
            history: 2048,
            tool_history: 128,
            context_pool: 256,
            memory_context: 512,
            policy: 64,
            current_input: 1024,
            proprioception: 64,
            total: 4096,
          },
          last_turn_usage: {
            prompt_tokens: 0,
            completion_tokens: 0,
            reasoning_tokens: 0,
            total_tokens: 0,
          },
          session_totals: {
            prompt_tokens: 0,
            completion_tokens: 0,
            reasoning_tokens: 0,
            total_tokens: 0,
            turn_count: 0,
          },
          usage_source: 'estimated',
          updated_at: '2026-04-09T00:00:00Z',
        }}
      />,
    )

    expect(markup).toContain('主窗口模型用量 / 上下文')
    expect(markup).toContain('上下文上限')
    expect(markup).toContain('128.0k')
    expect(markup).toContain('Token 统计将在首轮模型交互后显示，上下文上限已初始化。')
    expect(markup).toContain('gpt-5.4')
  })
})
