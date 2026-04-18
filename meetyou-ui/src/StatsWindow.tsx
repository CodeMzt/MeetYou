import { useEffect, useState } from 'react'
import { Gauge } from 'lucide-react'
import './dashboard.css'
import { fetchWithAuth } from './apiClient'
import { parseRuntimeDebugEnvelope } from './protocolClient'
import { RuntimeDebugSnapshot, RuntimeErrorPayload } from './types'
import styles from './StatsWindow.module.css'
import SubWindow from './components/layout/SubWindow'
import { DEFAULT_BASE_URL, WINDOW_SYNC_CHANNEL } from './windowBridge'

type DevtoolsPayload = {
  sessionId?: string
  baseUrl?: string
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function toRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function formatBooleanLabel(value: unknown, truthy: string, falsy: string): string {
  return value ? truthy : falsy
}

function renderErrorSummary(lastFailure: RuntimeErrorPayload | null): string {
  if (!lastFailure) {
    return '暂无失败记录'
  }
  return `${lastFailure.code} / ${lastFailure.category} / ${lastFailure.retryable ? '可重试' : '不可重试'}`
}

export default function RuntimeDebugWindow() {
  const [runtimeDebugSnapshot, setRuntimeDebugSnapshot] = useState<RuntimeDebugSnapshot | null>(null)
  const [sessionId, setSessionId] = useState('')
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL)

  useEffect(() => {
    if (!sessionId) {
      setRuntimeDebugSnapshot(null)
      return
    }

    let cancelled = false

    const loadDebug = async () => {
      try {
        const response = await fetchWithAuth(
          `${baseUrl}/developer/runtime/debug?session_id=${encodeURIComponent(sessionId)}`,
        )
        if (!response.ok) {
          return
        }
        const snapshot = parseRuntimeDebugEnvelope(await response.json())
        if (!cancelled) {
          setRuntimeDebugSnapshot(snapshot)
        }
      } catch (error) {
        if (!cancelled) {
          console.error('Failed to load runtime debug snapshot:', error)
        }
      }
    }

    void loadDebug()
    const timer = window.setInterval(() => {
      void loadDebug()
    }, 2000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [baseUrl, sessionId])

  useEffect(() => {
    const handleRuntimeDebugUpdated = (_event: unknown, data: DevtoolsPayload | null) => {
      setSessionId(data?.sessionId || '')
      setBaseUrl(data?.baseUrl || DEFAULT_BASE_URL)
    }

    window.ipcRenderer?.on(WINDOW_SYNC_CHANNEL.runtimeDebug.update, handleRuntimeDebugUpdated)

    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.runtimeDebug.request)

    return () => {
      window.ipcRenderer?.off(WINDOW_SYNC_CHANNEL.runtimeDebug.update, handleRuntimeDebugUpdated)
    }
  }, [])

  const route = toRecord(runtimeDebugSnapshot?.route)
  const authorization = toRecord(runtimeDebugSnapshot?.authorization)
  const routePreview = toRecord(authorization.route_preview)
  const confirmation = toRecord(authorization.confirmation)
  const contextPlan = toRecord(runtimeDebugSnapshot?.context_plan)
  const lengthPolicy = toRecord(contextPlan.length_policy)
  const layers = toRecord(contextPlan.layers)
  const memoryScope = toRecord(runtimeDebugSnapshot?.memory_scope)
  const taskState = toRecord(runtimeDebugSnapshot?.task_state)
  const backgroundState = toRecord(taskState.background)
  const scheduleState = toRecord(backgroundState.schedule)
  const executionState = toRecord(backgroundState.execution)
  const request = runtimeDebugSnapshot?.request
  const compression = runtimeDebugSnapshot?.compression
  const objectOperations = Array.isArray(runtimeDebugSnapshot?.object_operations)
    ? runtimeDebugSnapshot?.object_operations.slice(0, 3)
    : []
  const routeHistory = Array.isArray(runtimeDebugSnapshot?.route_history)
    ? runtimeDebugSnapshot?.route_history.slice(-4)
    : []
  const authTrace = (window.__meetyouAuthTrace?.entries || []).slice(-8).reverse()

  return (
    <SubWindow title="运行调试" icon={<Gauge size={16} />} contentStyle={{ padding: '20px', display: 'flex', flexDirection: 'column' }}>
      <div className={styles.hero}>
        <div>
          <div className={styles.kicker}>Runtime Debug</div>
          <h2 className={styles.title}>仅展示 `/developer/runtime/debug` 独有信息</h2>
          <p className={styles.description}>这里用于排查路由决策、请求预算、授权预览、压缩状态和最近失败，不再重复“上下文与用量”窗口里的 token 统计。</p>
        </div>
        <div className={styles.metaCard}>
          <span className={styles.metaLabel}>Session</span>
          <strong className={styles.metaValue}>{sessionId || '未绑定'}</strong>
          <span className={styles.metaLabel}>更新时间</span>
          <strong className={styles.metaValue}>{runtimeDebugSnapshot?.updated_at || '未同步'}</strong>
        </div>
      </div>

      {!runtimeDebugSnapshot ? (
        <div className={styles.empty}>当前会话还没有可用的 runtime debug 快照。</div>
      ) : (
        <>
          <section className={styles.section}>
            <div className={styles.sectionHeader}>路由决策</div>
            <div className={styles.grid}>
              <div className={styles.card}>
                <span className={styles.cardLabel}>当前模式</span>
                <strong className={styles.cardValue}>{String(route.current_mode || 'unknown')}</strong>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>请求模式</span>
                <strong className={styles.cardValue}>{String(route.requested_mode || 'unknown')}</strong>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>Source Profile</span>
                <strong className={styles.cardValue}>{String(route.source_profile || 'unknown')}</strong>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>上下文预载</span>
                <strong className={styles.cardValue}>{formatBooleanLabel(route.should_preload_context, '启用', '关闭')}</strong>
              </div>
            </div>
            <div className={styles.blockText}>{String(route.route_reason || '无路由原因')}</div>
            <div className={styles.tagRow}>
              {toStringArray(route.tool_bundle).map((item) => <span key={item} className={styles.tag}>{item}</span>)}
              {toStringArray(route.signals).map((item) => <span key={item} className={styles.tag}>{item}</span>)}
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>请求诊断</div>
            {request ? (
              <>
                <div className={styles.grid}>
                  <div className={styles.card}><span className={styles.cardLabel}>Provider</span><strong className={styles.cardValue}>{request.provider_name || 'unknown'}</strong></div>
                  <div className={styles.card}><span className={styles.cardLabel}>Model</span><strong className={styles.cardValue}>{request.model || 'unknown'}</strong></div>
                  <div className={styles.card}><span className={styles.cardLabel}>Transport</span><strong className={styles.cardValue}>{request.transport_mode || 'unknown'}</strong></div>
                  <div className={styles.card}><span className={styles.cardLabel}>Target Host</span><strong className={styles.cardValue}>{request.api_target.host || 'unknown'}</strong></div>
                  <div className={styles.card}><span className={styles.cardLabel}>消息数</span><strong className={styles.cardValue}>{request.message_count}</strong></div>
                  <div className={styles.card}><span className={styles.cardLabel}>工具数</span><strong className={styles.cardValue}>{request.tool_count}</strong></div>
                </div>
                <div className={styles.inlineMeta}>
                  <span>请求 tokens 估算：{request.request_tokens_estimated}</span>
                  <span>压力：{Math.round(request.pressure_ratio * 100)}%</span>
                  <span>{request.near_limit ? '接近上限' : '未接近上限'}</span>
                  <span>历史消息：{request.layers.history_message_count}</span>
                </div>
              </>
            ) : (
              <div className={styles.empty}>暂无请求诊断快照。</div>
            )}
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>预算与压缩</div>
            <div className={styles.inlineMeta}>
              <span>目标输入：{String(lengthPolicy.target_input_tokens || 'unknown')}</span>
              <span>保留输出：{String(lengthPolicy.reserved_response_tokens || 'unknown')}</span>
              <span>预留比例：{String(lengthPolicy.reserve_ratio || 'unknown')}</span>
              <span>摘要层：{formatBooleanLabel(layers.conversation_summary, '启用', '关闭')}</span>
              <span>记忆召回：{formatBooleanLabel(layers.memory_recall, '启用', '关闭')}</span>
            </div>
            {compression ? (
              <div className={styles.grid}>
                <div className={styles.card}><span className={styles.cardLabel}>压缩状态</span><strong className={styles.cardValue}>{compression.triggered ? '已触发' : '未触发'}</strong></div>
                <div className={styles.card}><span className={styles.cardLabel}>压缩级别</span><strong className={styles.cardValue}>{compression.level || 'none'}</strong></div>
                <div className={styles.card}><span className={styles.cardLabel}>修剪消息</span><strong className={styles.cardValue}>{compression.trimmed_messages}</strong></div>
                <div className={styles.card}><span className={styles.cardLabel}>摘要 tokens</span><strong className={styles.cardValue}>{compression.summary_tokens}</strong></div>
              </div>
            ) : (
              <div className={styles.empty}>本轮没有压缩信息。</div>
            )}
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>授权与执行边界</div>
            <div className={styles.inlineMeta}>
              <span>可见工具：{toStringArray(routePreview.visible_tools).length}</span>
              <span>候选工具：{toStringArray(routePreview.candidate_tools).length}</span>
              <span>确认挂起：{formatBooleanLabel(confirmation.pending, '是', '否')}</span>
              <span>记忆预取：{formatBooleanLabel(memoryScope.prefetched, '是', '否')}</span>
              <span>记忆命中：{formatBooleanLabel(memoryScope.found, '是', '否')}</span>
            </div>
            <div className={styles.tagRow}>
              {toStringArray(routePreview.visible_tools).map((item) => <span key={item} className={styles.tag}>{item}</span>)}
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>运行背景</div>
            <div className={styles.inlineMeta}>
              <span>待执行任务：{String(scheduleState.due_task_count || 0)}</span>
              <span>待完成执行：{String(executionState.awaiting_completion_count || 0)}</span>
              <span>最近失败：{renderErrorSummary(runtimeDebugSnapshot.last_failure)}</span>
            </div>
            {objectOperations.length > 0 ? (
              <div className={styles.list}>
                {objectOperations.map((item, index) => (
                  <div key={`${String(item.action || 'op')}-${index}`} className={styles.listItem}>
                    <strong>{String(item.action || 'action')}</strong>
                    <span>{String(item.object_type || 'object')}</span>
                    <span>{String(item.status || 'status')}</span>
                    <span>{String(item.summary || '')}</span>
                  </div>
                ))}
              </div>
            ) : null}
            {routeHistory.length > 0 ? (
              <div className={styles.list}>
                {routeHistory.map((item, index) => (
                  <div key={`route-history-${index}`} className={styles.listItem}>
                    <strong>Round {String(item.round ?? index)}</strong>
                    <span>{String(item.mode || 'unknown')}</span>
                  </div>
                ))}
              </div>
            ) : null}
            {runtimeDebugSnapshot.last_failure ? (
              <div className={styles.blockText}>{runtimeDebugSnapshot.last_failure.message}</div>
            ) : null}
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>前端到本地后端鉴权轨迹</div>
            <div className={styles.inlineMeta}>
              <span>Renderer baseUrl: {window.__meetyouAuthTrace?.baseUrl || baseUrl}</span>
              <span>最近记录: {authTrace.length}</span>
            </div>
            {authTrace.length > 0 ? (
              <div className={styles.list}>
                {authTrace.map((entry, index) => (
                  <div key={`${entry.ts}-${entry.method}-${index}`} className={styles.listItem}>
                    <strong>{entry.method}</strong>
                    <span>{entry.host}</span>
                    <span>{entry.status ? `HTTP ${entry.status}` : entry.error || '-'}</span>
                    <span>{entry.attachAuth ? `auth:${entry.tokenSource}` : 'auth:none'}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className={styles.empty}>暂无前端鉴权轨迹，先回主窗口触发一次请求。</div>
            )}
          </section>
        </>
      )}
    </SubWindow>
  )
}
