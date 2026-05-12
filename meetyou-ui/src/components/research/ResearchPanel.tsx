import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, Download, FileText, Play, RefreshCw, Save, Search, X } from 'lucide-react'
import type { RuntimeResearchTask, RuntimeResearchTaskEvent } from '../../types'
import styles from './ResearchPanel.module.css'

interface ResearchPanelProps {
  tasks: RuntimeResearchTask[]
  taskEvents: Record<string, RuntimeResearchTaskEvent[]>
  busy: boolean
  onCreateTask: (topic: string, options?: ResearchCreateOptions) => Promise<unknown>
  onApproveTask: (taskId: string) => Promise<unknown>
  onStartTask: (taskId: string) => Promise<unknown>
  onCancelTask: (taskId: string) => Promise<unknown>
  onSavePlan: (taskId: string, plan: Record<string, unknown>) => Promise<unknown>
  onDownloadArtifact: (task: RuntimeResearchTask) => Promise<unknown>
  onRefresh: () => Promise<unknown>
}

interface ResearchCreateOptions {
  webSearch?: boolean
  webQueries?: string[]
  webUrls?: string[]
  derivedFormats?: string[]
  limit?: number
}

interface ResearchAdapterInfo {
  provider: string
  status: string
  externalRunId: string
  error: string
  message: string
  lastPollAt: string
}

const REPORT_FORMAT_OPTIONS = [
  { id: 'pdf', label: 'PDF', title: '同时生成 PDF 报告' },
  { id: 'docx', label: 'DOCX', title: '同时生成 Word 文档' },
] as const

function statusLabel(status: string): string {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'planned') return '计划中'
  if (normalized === 'approved') return '已确认'
  if (normalized === 'running') return '运行中'
  if (normalized === 'completed') return '已完成'
  if (normalized === 'cancelled') return '已取消'
  if (normalized === 'failed') return '失败'
  return status || '未知'
}

function getPlanSteps(task: RuntimeResearchTask): Array<{ id: string; title: string; status: string }> {
  const rawSteps = (task.plan as { steps?: unknown }).steps
  if (!Array.isArray(rawSteps)) {
    return []
  }
  return rawSteps
    .map((item, index) => {
      if (!item || typeof item !== 'object') {
        return null
      }
      const step = item as Record<string, unknown>
      return {
        id: String(step.id || index),
        title: String(step.title || step.id || `步骤 ${index + 1}`),
        status: String(step.status || ''),
      }
    })
    .filter((item): item is { id: string; title: string; status: string } => Boolean(item))
}

interface EvidenceAuditItem {
  id: string
  sourceId: string
  title: string
  source: string
  url: string
  rank: number | null
  qualityScore: number | null
  duplicateCount: number
  mergedSourceIds: string[]
  trust: string
  verificationStatus: string
}

function numberOrNull(value: unknown): number | null {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function getEvidenceItems(task: RuntimeResearchTask): EvidenceAuditItem[] {
  return (Array.isArray(task.evidence_ledger) ? task.evidence_ledger : [])
    .map((item, index) => {
      if (!item || typeof item !== 'object') {
        return null
      }
      const evidence = item as Record<string, unknown>
      const title = String(evidence.title || evidence.source_title || evidence.name || evidence.url || evidence.source_id || `来源 ${index + 1}`)
      const sourceId = String(evidence.source_id || evidence.evidence_id || index + 1)
      const duplicateCount = Math.max(1, Number(evidence.duplicate_count || 1) || 1)
      const mergedSourceIds = Array.isArray(evidence.merged_source_ids)
        ? evidence.merged_source_ids.map((value) => String(value || '').trim()).filter(Boolean)
        : []
      return {
        id: String(evidence.evidence_id || evidence.source_id || evidence.url || index),
        sourceId,
        title,
        source: String(evidence.source_type || evidence.adapter || evidence.kind || '来源'),
        url: String(evidence.url || evidence.href || ''),
        rank: numberOrNull(evidence.rank),
        qualityScore: numberOrNull(evidence.quality_score),
        duplicateCount,
        mergedSourceIds,
        trust: String(evidence.source_trust || evidence.trusted_for || ''),
        verificationStatus: String(evidence.verification_status || ''),
      }
    })
    .filter((item): item is EvidenceAuditItem => Boolean(item))
}

function stageLabel(stage: string): string {
  const normalized = String(stage || '').toLowerCase()
  if (normalized === 'adapter') return '外部研究服务'
  if (normalized === 'queued') return '排队'
  if (normalized === 'starting') return '启动服务'
  if (normalized === 'project_sources') return '整理项目源'
  if (normalized === 'research') return '外部研究'
  if (normalized === 'gather') return '收集证据'
  if (normalized === 'write') return '撰写报告'
  if (normalized === 'sources') return '整理来源'
  if (normalized === 'synthesize') return '综合报告'
  if (normalized === 'artifact') return '保存产物'
  if (normalized === 'completed') return '完成'
  return stage || '进度'
}

function adapterStatusLabel(status: string): string {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'unconfigured') return '未配置'
  if (normalized === 'running') return '运行中'
  if (normalized === 'completed') return '已完成'
  if (normalized === 'failed') return '失败'
  if (normalized === 'cancelled') return '已取消'
  return status || '等待'
}

function adapterErrorMessage(status: string, error: string): string {
  const normalizedStatus = String(status || '').toLowerCase()
  const normalizedError = String(error || '').toLowerCase()
  if (normalizedStatus === 'unconfigured' || normalizedError.includes('unconfigured')) {
    return '外部研究服务未配置：请启动 research_adapter，并在 Core 设置 MEETYOU_RESEARCH_ADAPTER_BASE_URL 与 token。'
  }
  if (normalizedError.includes('external_sources_missing')) {
    return '外部研究服务没有返回可引用来源，Core 已拒绝生成无引用报告。'
  }
  if (normalizedError.includes('timeout') || normalizedError.includes('request_failed') || normalizedError.includes('poll')) {
    return '外部研究服务暂时无响应：任务不会因为固定总时长自动失败，请检查 adapter 日志或稍后刷新。'
  }
  return error ? `外部研究服务失败：${error}` : ''
}

function getResearchAdapterInfo(task: RuntimeResearchTask): ResearchAdapterInfo | null {
  const metadata = (task.metadata || {}) as Record<string, unknown>
  const runner = String(metadata.runner || '')
  const provider = String(metadata.research_provider || metadata.provider || '')
  const status = String(metadata.adapter_status || '')
  const externalRunId = String(metadata.external_run_id || '')
  const error = String(metadata.adapter_error || metadata.runner_error || '')
  const lastPollAt = String(metadata.last_adapter_poll_at || '')
  if (!provider && !status && !externalRunId && !error && runner !== 'research_adapter.v1') {
    return null
  }
  return {
    provider: provider || 'gpt_researcher',
    status: status || (task.status === 'running' ? 'running' : ''),
    externalRunId,
    error,
    message: adapterErrorMessage(status, error),
    lastPollAt,
  }
}

function eventLabel(type: string): string {
  const normalized = String(type || '').toLowerCase()
  if (normalized === 'research.started') return '已开始'
  if (normalized === 'research.progress') return '进度'
  if (normalized === 'research.completed') return '已完成'
  if (normalized === 'research.failed') return '失败'
  if (normalized === 'research.cancelled') return '已取消'
  return type || '事件'
}

function eventDetail(event: RuntimeResearchTaskEvent): string {
  const payload = event.payload || {}
  const stage = String(payload.stage || '')
  const status = String(payload.status || '')
  const message = String(payload.message || '')
  const detail = [stage ? stageLabel(stage) : '', status ? statusLabel(status) : '', message]
    .filter(Boolean)
    .join(' / ')
  return detail || eventLabel(event.type)
}

function shortId(value: string): string {
  const text = String(value || '').trim()
  return text ? text.slice(-8) : ''
}

function getResearchProgress(task: RuntimeResearchTask): { stage: string; status: string; message: string; at: string; errorCount: number } | null {
  const metadata = (task.metadata || {}) as Record<string, unknown>
  const rawProgress = metadata.progress
  const progress = rawProgress && typeof rawProgress === 'object' ? rawProgress as Record<string, unknown> : {}
  const gatherErrors = Array.isArray(metadata.gather_errors) ? metadata.gather_errors : []
  const errorCountRaw = progress.gather_error_count ?? gatherErrors.length
  const errorCount = Number.isFinite(Number(errorCountRaw)) ? Math.max(0, Number(errorCountRaw)) : 0
  if (!Object.keys(progress).length && !errorCount) {
    return null
  }
  return {
    stage: String(progress.stage || ''),
    status: String(progress.status || task.status || ''),
    message: String(progress.message || ''),
    at: String(progress.at || task.updated_at || ''),
    errorCount,
  }
}

function formatProgressTime(value: string): string {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value.slice(0, 16)
  }
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatElapsedSince(value: string): string {
  if (!value) {
    return ''
  }
  const startedAt = new Date(value).getTime()
  if (!Number.isFinite(startedAt)) {
    return ''
  }
  const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
  if (seconds < 60) {
    return `${seconds} 秒`
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return `${minutes} 分 ${seconds % 60} 秒`
  }
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时 ${minutes % 60} 分`
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0 B'
  }
  if (value < 1024) {
    return `${value} B`
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function formatQualityScore(value: number | null): string {
  if (value === null) {
    return ''
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function formatPlan(plan: Record<string, unknown>): string {
  try {
    return JSON.stringify(plan || {}, null, 2)
  } catch {
    return '{}'
  }
}

function parseQueryList(value: string): string[] {
  return String(value || '')
    .split(/\r?\n|[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 4)
}

export default function ResearchPanel({
  tasks,
  taskEvents,
  busy,
  onCreateTask,
  onApproveTask,
  onStartTask,
  onCancelTask,
  onSavePlan,
  onDownloadArtifact,
  onRefresh,
}: ResearchPanelProps) {
  const [topic, setTopic] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [planText, setPlanText] = useState('')
  const [localError, setLocalError] = useState('')
  const [webSearchEnabled, setWebSearchEnabled] = useState(true)
  const [webQueryText, setWebQueryText] = useState('')
  const [webUrlText, setWebUrlText] = useState('')
  const [derivedFormats, setDerivedFormats] = useState<string[]>([])
  const [sourceLimit, setSourceLimit] = useState('3')
  const webSearchInputRef = useRef<HTMLInputElement | null>(null)
  const webQueryInputRef = useRef<HTMLInputElement | null>(null)
  const webUrlInputRef = useRef<HTMLInputElement | null>(null)
  const formatInputRefs = useRef<Record<string, HTMLInputElement | null>>({})
  const sourceLimitRef = useRef<HTMLSelectElement | null>(null)

  const selectedTask = useMemo(
    () => tasks.find((task) => task.research_task_id === selectedTaskId) || tasks[0] || null,
    [selectedTaskId, tasks],
  )
  const planSteps = selectedTask ? getPlanSteps(selectedTask) : []
  const evidenceItems = selectedTask ? getEvidenceItems(selectedTask) : []
  const researchProgress = selectedTask ? getResearchProgress(selectedTask) : null
  const adapterInfo = selectedTask ? getResearchAdapterInfo(selectedTask) : null
  const editablePlan = selectedTask?.status === 'planned'
  const showPlanSteps = selectedTask ? ['planned', 'approved'].includes(String(selectedTask.status || '').toLowerCase()) : false
  const selectedDerivedArtifacts = selectedTask?.derived_artifacts || []
  const selectedEvents = selectedTask ? taskEvents[selectedTask.research_task_id] || [] : []
  const latestEvent = selectedEvents[selectedEvents.length - 1] || null
  const runningElapsed = selectedTask?.status === 'running' ? formatElapsedSince(selectedTask.created_at) : ''

  useEffect(() => {
    if (selectedTask) {
      setPlanText(formatPlan(selectedTask.plan))
    }
  }, [selectedTask?.research_task_id])

  const selectTask = (task: RuntimeResearchTask) => {
    setSelectedTaskId(task.research_task_id)
    setPlanText(formatPlan(task.plan))
    setLocalError('')
  }

  const updateDerivedFormat = (format: string, checked: boolean) => {
    setDerivedFormats((current) => {
      const next = checked
        ? Array.from(new Set([...current, format]))
        : current.filter((item) => item !== format)
      return REPORT_FORMAT_OPTIONS
        .map((option) => option.id)
        .filter((item) => next.includes(item))
    })
  }

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextTopic = topic.trim()
    if (!nextTopic || busy) {
      return
    }
    const currentWebSearchEnabled = webSearchInputRef.current?.checked ?? webSearchEnabled
    const currentWebQueryText = webQueryInputRef.current?.value ?? webQueryText
    const currentWebUrlText = webUrlInputRef.current?.value ?? webUrlText
    const currentDerivedFormats = REPORT_FORMAT_OPTIONS
      .filter((option) => formatInputRefs.current[option.id]?.checked ?? derivedFormats.includes(option.id))
      .map((option) => option.id)
    const currentLimit = Number(sourceLimitRef.current?.value || sourceLimit || 3)
    setLocalError('')
    await onCreateTask(nextTopic, {
      webSearch: currentWebSearchEnabled,
      webQueries: parseQueryList(currentWebQueryText),
      webUrls: parseQueryList(currentWebUrlText),
      derivedFormats: currentDerivedFormats,
      limit: Number.isFinite(currentLimit) ? currentLimit : 3,
    })
    setTopic('')
  }

  const savePlan = async () => {
    if (!selectedTask || !editablePlan || busy) {
      return
    }
    try {
      const parsed = JSON.parse(planText || '{}') as Record<string, unknown>
      setLocalError('')
      await onSavePlan(selectedTask.research_task_id, parsed)
    } catch {
      setLocalError('计划 JSON 无效')
    }
  }

  return (
    <section className={styles.panel} data-research-panel="true">
      <div className={styles.header}>
        <div className={styles.title}>
          <Search size={14} aria-hidden="true" />
          <span>深度研究</span>
        </div>
        <button type="button" className={styles.iconButton} title="刷新研究任务" onClick={() => void onRefresh()} disabled={busy} data-research-refresh="true">
          <RefreshCw size={14} aria-hidden="true" />
        </button>
      </div>

      <form className={styles.composer} onSubmit={submitCreate}>
        <input
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="研究主题"
          disabled={busy}
          data-research-topic-input="true"
        />
        <button type="submit" disabled={busy || !topic.trim()} title="创建研究计划" data-research-create="true">
          <FileText size={14} aria-hidden="true" />
        </button>
      </form>

      <div className={styles.searchOptions}>
        <label className={styles.searchToggle}>
          <input
            ref={webSearchInputRef}
            type="checkbox"
            checked={webSearchEnabled}
            onChange={(event) => setWebSearchEnabled(event.target.checked)}
            disabled={busy}
            data-research-web-search-toggle="true"
          />
          <span>联网搜索</span>
        </label>
        <input
          ref={webQueryInputRef}
          type="text"
          value={webQueryText}
          onChange={(event) => setWebQueryText(event.target.value)}
          placeholder="搜索查询，留空使用主题"
          disabled={busy || !webSearchEnabled}
          data-research-web-query-input="true"
        />
      </div>

      <input
        ref={webUrlInputRef}
        type="text"
        className={styles.urlInput}
        value={webUrlText}
        onChange={(event) => setWebUrlText(event.target.value)}
        placeholder="网页 URL，可逗号分隔"
        disabled={busy}
        data-research-web-url-input="true"
      />

      <div className={styles.sourceScope} data-research-source-scope="true">
        <span className={styles.scopeLabel}>来源上限</span>
        <select
          ref={sourceLimitRef}
          value={sourceLimit}
          onChange={(event) => setSourceLimit(event.target.value)}
          disabled={busy}
          aria-label="来源数量"
          data-research-source-limit="true"
        >
          <option value="1">1 条</option>
          <option value="3">3 条</option>
          <option value="5">5 条</option>
          <option value="8">8 条</option>
        </select>
      </div>

      <div className={styles.exportScope} data-research-export-scope="true">
        <span className={styles.scopeLabel}>导出</span>
        <div className={styles.formatScroller}>
          {REPORT_FORMAT_OPTIONS.map((option) => (
            <label className={styles.formatChip} key={option.id} title={option.title}>
              <input
                ref={(element) => {
                  formatInputRefs.current[option.id] = element
                }}
                type="checkbox"
                checked={derivedFormats.includes(option.id)}
                onChange={(event) => updateDerivedFormat(option.id, event.target.checked)}
                disabled={busy}
                data-research-derived-format={option.id}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      </div>

      {localError ? <div className={styles.error}>{localError}</div> : null}

      {tasks.length > 0 ? (
        <div className={styles.taskList}>
          {tasks.slice(0, 5).map((task) => (
            <button
              type="button"
              key={task.research_task_id}
              className={`${styles.taskItem} ${selectedTask?.research_task_id === task.research_task_id ? styles.activeTask : ''}`}
              onClick={() => selectTask(task)}
              data-research-task-id={task.research_task_id}
            >
              <span>{task.topic}</span>
              <span>{statusLabel(task.status)}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className={styles.empty}>此会话暂无研究任务</div>
      )}

      {selectedTask ? (
        <div className={styles.detail} data-research-selected-task={selectedTask.research_task_id}>
          <div className={styles.detailHeader}>
            <span>{selectedTask.topic}</span>
            <span>{statusLabel(selectedTask.status)}</span>
          </div>

          {showPlanSteps && planSteps.length ? (
            <div className={styles.steps} data-research-plan-steps="true">
              <div className={styles.sectionLabel}>计划草案</div>
              {planSteps.slice(0, 4).map((step, index) => (
                <div className={styles.step} key={step.id}>
                  <span>{step.title}</span>
                  <span>步骤 {index + 1}</span>
                </div>
              ))}
            </div>
          ) : null}

          <div className={styles.progressRow} data-research-progress="true">
            <span>来源 {evidenceItems.length}</span>
            <span>格式 {selectedTask.output_format || 'markdown'}</span>
            {adapterInfo ? <span data-research-adapter-provider="true">外部 {adapterInfo.provider}</span> : null}
            {adapterInfo ? <span data-research-adapter-status="true">{adapterStatusLabel(adapterInfo.status)}</span> : null}
            {adapterInfo?.externalRunId ? <span data-research-external-run-id="true">外部 {shortId(adapterInfo.externalRunId)}</span> : null}
            {adapterInfo?.lastPollAt ? <span data-research-last-poll="true">轮询 {formatProgressTime(adapterInfo.lastPollAt)}</span> : null}
            {runningElapsed ? <span data-research-elapsed="true">已运行 {runningElapsed}</span> : null}
            {selectedTask.status === 'running' ? <span data-research-auto-refresh="true">自动刷新</span> : null}
            {selectedTask.run_id ? <span data-research-run-id="true">运行 {shortId(selectedTask.run_id)}</span> : null}
            {selectedEvents.length ? <span data-research-event-count="true">事件 {selectedEvents.length}</span> : null}
            {selectedDerivedArtifacts.length ? <span data-research-derived-count="true">导出 {selectedDerivedArtifacts.length}</span> : null}
            {researchProgress?.errorCount ? <span data-research-progress-errors="true">错误 {researchProgress.errorCount}</span> : null}
            {selectedTask.artifact ? <span>{formatBytes(selectedTask.artifact.byte_size)}</span> : null}
          </div>

          {researchProgress ? (
            <div className={styles.stageProgress} data-research-progress-stage="true">
              <div>
                <span>{stageLabel(researchProgress.stage)}</span>
                <small>{statusLabel(researchProgress.status)}</small>
              </div>
              {researchProgress.message ? <p data-research-progress-message="true">{researchProgress.message}</p> : null}
              {researchProgress.at ? <small>更新 {formatProgressTime(researchProgress.at)}</small> : null}
            </div>
          ) : null}

          {adapterInfo?.message ? (
            <div className={styles.adapterNotice} data-research-adapter-error="true">
              {adapterInfo.message}
            </div>
          ) : null}

          {selectedEvents.length ? (
            <div className={styles.eventStream} data-research-event-stream="true">
              <div className={styles.sectionLabel}>
                <span>事件流</span>
                {latestEvent ? <small data-research-latest-event="true">最新 {eventLabel(latestEvent.type)}</small> : null}
              </div>
              {selectedEvents.slice(-4).map((event) => (
                <div className={styles.eventItem} key={event.event_id || `${event.run_id}-${event.seq}`}>
                  <span>{event.seq}. {eventLabel(event.type)}</span>
                  <small>{eventDetail(event)}</small>
                </div>
              ))}
            </div>
          ) : null}

          {selectedTask.summary ? (
            <div className={styles.summary} data-research-summary="true">{selectedTask.summary}</div>
          ) : null}

          {evidenceItems.length ? (
            <div className={styles.evidenceList} data-research-evidence-list="true">
              <div className={styles.sectionLabel}>来源</div>
              {evidenceItems.slice(0, 5).map((item) => (
                <div className={styles.evidenceItem} key={item.id} data-research-evidence-id={item.sourceId}>
                  <div className={styles.evidenceTitleRow}>
                    <span data-research-evidence-rank="true">{item.rank ? `#${item.rank}` : `[${item.sourceId}]`}</span>
                    <strong>{item.title}</strong>
                  </div>
                  <small>{item.source}{item.url ? ` · ${item.url}` : ''}</small>
                  <div className={styles.evidenceBadges}>
                    {item.qualityScore !== null ? <span data-research-evidence-quality="true">质量 {formatQualityScore(item.qualityScore)}</span> : null}
                    {item.duplicateCount > 1 ? <span data-research-evidence-duplicates="true">合并 {item.duplicateCount}</span> : null}
                    {item.verificationStatus ? <span data-research-evidence-status="true">{item.verificationStatus}</span> : null}
                    {item.trust ? <span data-research-evidence-trust="true">{item.trust}</span> : null}
                    {item.mergedSourceIds.length > 1 ? <span data-research-evidence-merged="true">源 {item.mergedSourceIds.join(',')}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          {selectedTask.artifact ? (
            <div className={styles.artifactMeta} data-research-artifact-meta="true">
              <FileText size={13} aria-hidden="true" />
              <span>{selectedTask.artifact.filename}</span>
            </div>
          ) : null}

          {selectedDerivedArtifacts.length ? (
            <div className={styles.artifactMeta} data-research-derived-artifacts="true">
              <FileText size={13} aria-hidden="true" />
              <span>导出 {selectedDerivedArtifacts.map((artifact) => artifact.filename || artifact.artifact_id).join(' / ')}</span>
            </div>
          ) : null}

          {editablePlan ? (
            <div className={styles.planEditor}>
              <textarea
                value={planText || formatPlan(selectedTask.plan)}
                onChange={(event) => setPlanText(event.target.value)}
                spellCheck={false}
                data-research-plan-editor="true"
              />
              <button type="button" onClick={() => void savePlan()} disabled={busy} title="保存研究计划" data-research-save-plan="true">
                <Save size={14} aria-hidden="true" />
                <span>保存计划</span>
              </button>
            </div>
          ) : null}

          <div className={styles.actions}>
            {selectedTask.status === 'planned' ? (
              <button type="button" onClick={() => void onApproveTask(selectedTask.research_task_id)} disabled={busy} data-research-approve="true">
                <Check size={14} aria-hidden="true" />
                <span>确认</span>
              </button>
            ) : null}
            {selectedTask.status === 'planned' || selectedTask.status === 'approved' ? (
              <button type="button" onClick={() => void onStartTask(selectedTask.research_task_id)} disabled={busy} data-research-start="true">
                <Play size={14} aria-hidden="true" />
                <span>开始</span>
              </button>
            ) : null}
            {selectedTask.status === 'running' ? (
              <button type="button" onClick={() => void onCancelTask(selectedTask.research_task_id)} disabled={busy} data-research-cancel="true">
                <X size={14} aria-hidden="true" />
                <span>取消</span>
              </button>
            ) : null}
            {selectedTask.artifact ? (
              <button type="button" onClick={() => void onDownloadArtifact(selectedTask)} disabled={busy} data-research-download="true">
                <Download size={14} aria-hidden="true" />
                <span>下载</span>
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}
