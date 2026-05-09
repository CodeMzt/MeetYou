import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, Download, FileText, Play, RefreshCw, Save, Search, X } from 'lucide-react'
import type { RuntimeResearchTask } from '../../types'
import styles from './ResearchPanel.module.css'

interface ResearchPanelProps {
  tasks: RuntimeResearchTask[]
  busy: boolean
  onCreateTask: (topic: string) => Promise<unknown>
  onApproveTask: (taskId: string) => Promise<unknown>
  onStartTask: (taskId: string) => Promise<unknown>
  onCancelTask: (taskId: string) => Promise<unknown>
  onSavePlan: (taskId: string, plan: Record<string, unknown>) => Promise<unknown>
  onDownloadArtifact: (task: RuntimeResearchTask) => Promise<unknown>
  onRefresh: () => Promise<unknown>
}

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
        title: String(step.title || step.id || `Step ${index + 1}`),
        status: String(step.status || ''),
      }
    })
    .filter((item): item is { id: string; title: string; status: string } => Boolean(item))
}

function formatPlan(plan: Record<string, unknown>): string {
  try {
    return JSON.stringify(plan || {}, null, 2)
  } catch {
    return '{}'
  }
}

export default function ResearchPanel({
  tasks,
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

  const selectedTask = useMemo(
    () => tasks.find((task) => task.research_task_id === selectedTaskId) || tasks[0] || null,
    [selectedTaskId, tasks],
  )
  const planSteps = selectedTask ? getPlanSteps(selectedTask) : []
  const editablePlan = selectedTask?.status === 'planned'

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

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextTopic = topic.trim()
    if (!nextTopic || busy) {
      return
    }
    setLocalError('')
    await onCreateTask(nextTopic)
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
        <div className={styles.empty}>暂无研究任务</div>
      )}

      {selectedTask ? (
        <div className={styles.detail} data-research-selected-task={selectedTask.research_task_id}>
          <div className={styles.detailHeader}>
            <span>{selectedTask.topic}</span>
            <span>{statusLabel(selectedTask.status)}</span>
          </div>

          {planSteps.length ? (
            <div className={styles.steps}>
              {planSteps.slice(0, 4).map((step) => (
                <div className={styles.step} key={step.id}>
                  <span>{step.title}</span>
                  <span>{step.status || 'planned'}</span>
                </div>
              ))}
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
