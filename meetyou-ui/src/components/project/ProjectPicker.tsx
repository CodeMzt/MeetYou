import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Folder, Layers3, Plus, Save, Settings, X } from 'lucide-react'
import type { RuntimeProject } from '../../types'
import styles from './ProjectPicker.module.css'

export interface ProjectSettingsPayload {
  title?: string
  description?: string
  instructions?: string
}

interface ProjectPickerProps {
  projects: RuntimeProject[]
  activeProjectId: string
  onSelectProject: (projectId: string) => unknown | Promise<unknown>
  onCreateProject: (title: string) => RuntimeProject | Promise<RuntimeProject | null> | null
  onUpdateProject?: (
    projectId: string,
    payload: ProjectSettingsPayload,
  ) => RuntimeProject | Promise<RuntimeProject | null> | null
}

function projectTitle(project: RuntimeProject): string {
  return String(project.title || project.project_id || '').trim() || '未命名项目'
}

export interface ProjectSettingsFormProps {
  title: string
  description: string
  instructions: string
  updating: boolean
  error: string
  onTitleChange: (value: string) => void
  onDescriptionChange: (value: string) => void
  onInstructionsChange: (value: string) => void
  onCancel: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}

export function ProjectSettingsForm({
  title,
  description,
  instructions,
  updating,
  error,
  onTitleChange,
  onDescriptionChange,
  onInstructionsChange,
  onCancel,
  onSubmit,
}: ProjectSettingsFormProps) {
  return (
    <form className={styles.settingsForm} onSubmit={onSubmit} data-project-settings-form="true">
      <label className={styles.field}>
        <span className={styles.fieldLabel}>项目名称</span>
        <input
          className={styles.textInput}
          value={title}
          onChange={(event) => onTitleChange(event.target.value)}
          maxLength={80}
          data-project-title-input="true"
        />
      </label>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>项目说明</span>
        <textarea
          className={styles.textarea}
          value={description}
          onChange={(event) => onDescriptionChange(event.target.value)}
          rows={2}
          maxLength={500}
          data-project-description-input="true"
        />
      </label>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>项目指令</span>
        <textarea
          className={styles.textarea}
          value={instructions}
          onChange={(event) => onInstructionsChange(event.target.value)}
          rows={4}
          maxLength={4000}
          data-project-instructions-input="true"
        />
      </label>
      {error && <div className={styles.errorText}>{error}</div>}
      <div className={styles.settingsActions}>
        <button type="button" className={styles.secondaryButton} onClick={onCancel} disabled={updating}>
          <X size={13} aria-hidden="true" />
          取消
        </button>
        <button type="submit" className={styles.primaryButton} disabled={updating || !title.trim()} data-project-settings-save="true">
          <Save size={13} aria-hidden="true" />
          {updating ? '保存中' : '保存'}
        </button>
      </div>
    </form>
  )
}

export default function ProjectPicker({
  projects,
  activeProjectId,
  onSelectProject,
  onCreateProject,
  onUpdateProject,
}: ProjectPickerProps) {
  const [open, setOpen] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [creating, setCreating] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editInstructions, setEditInstructions] = useState('')
  const [updating, setUpdating] = useState(false)
  const [settingsError, setSettingsError] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const activeProject = useMemo(
    () => projects.find((project) => project.project_id === activeProjectId) ?? null,
    [activeProjectId, projects],
  )
  const triggerTitle = activeProject ? projectTitle(activeProject) : '全部会话'

  useEffect(() => {
    if (!open) {
      setSettingsOpen(false)
      setSettingsError('')
      return
    }
    if (!activeProject) {
      setEditTitle('')
      setEditDescription('')
      setEditInstructions('')
      setSettingsOpen(false)
      setSettingsError('')
      return
    }
    setEditTitle(projectTitle(activeProject))
    setEditDescription(String(activeProject.description || ''))
    setEditInstructions(String(activeProject.instructions || ''))
    setSettingsError('')
  }, [
    activeProject?.project_id,
    activeProject?.title,
    activeProject?.description,
    activeProject?.instructions,
    open,
  ])

  useEffect(() => {
    if (!open) {
      return
    }
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false)
      }
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  useLayoutEffect(() => {
    if (!open) {
      return
    }
    const updateMenuPosition = () => {
      const trigger = triggerRef.current
      if (!trigger) {
        return
      }
      const rect = trigger.getBoundingClientRect()
      const gutter = 12
      const width = Math.max(0, Math.min(320, window.innerWidth - gutter * 2))
      setMenuStyle({
        left: Math.min(Math.max(gutter, rect.left), Math.max(gutter, window.innerWidth - width - gutter)),
        top: Math.min(rect.bottom + 10, Math.max(gutter, window.innerHeight - 112)),
        width,
        maxHeight: Math.max(180, window.innerHeight - rect.bottom - 22),
      })
    }
    updateMenuPosition()
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      window.removeEventListener('scroll', updateMenuPosition, true)
    }
  }, [open])

  const handleSelect = (projectId: string) => {
    setOpen(false)
    setSettingsOpen(false)
    if (projectId !== activeProjectId) {
      void onSelectProject(projectId)
    }
  }

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const title = draftTitle.trim()
    if (!title || creating) {
      return
    }
    setCreating(true)
    try {
      const project = await onCreateProject(title)
      if (project?.project_id) {
        await onSelectProject(project.project_id)
      }
      setDraftTitle('')
      setSettingsOpen(false)
      setOpen(false)
    } finally {
      setCreating(false)
    }
  }

  const handleSettingsSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!activeProject || !onUpdateProject || updating) {
      return
    }
    const title = editTitle.trim()
    if (!title) {
      setSettingsError('项目名称不能为空')
      return
    }
    setUpdating(true)
    setSettingsError('')
    try {
      const project = await onUpdateProject(activeProject.project_id, {
        title,
        description: editDescription.trim(),
        instructions: editInstructions.trim(),
      })
      if (project) {
        setEditTitle(projectTitle(project))
        setEditDescription(String(project.description || ''))
        setEditInstructions(String(project.instructions || ''))
      }
      setSettingsOpen(false)
    } catch (error) {
      setSettingsError(error instanceof Error ? error.message : '保存项目设置失败')
    } finally {
      setUpdating(false)
    }
  }

  return (
    <div className={styles.projectPicker} ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`${styles.trigger} ${open ? styles.open : ''}`}
        onClick={() => setOpen((current) => !current)}
        title={triggerTitle}
        aria-haspopup="listbox"
        aria-expanded={open}
        data-project-picker-trigger="true"
      >
        {activeProject ? <Folder size={14} aria-hidden="true" /> : <Layers3 size={14} aria-hidden="true" />}
        <span className={styles.triggerTitle}>{triggerTitle}</span>
        <ChevronDown size={14} className={styles.chevron} aria-hidden="true" />
      </button>

      {open && typeof document !== 'undefined' && createPortal(
        <div
          className={styles.menu}
          ref={menuRef}
          style={menuStyle}
          role="listbox"
          aria-label="选择项目"
        >
          <form className={styles.createForm} onSubmit={handleCreate}>
            <input
              className={styles.createInput}
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              placeholder="新项目"
              maxLength={80}
            />
            <button type="submit" className={styles.iconButton} title="创建项目" disabled={creating || !draftTitle.trim()}>
              <Plus size={14} aria-hidden="true" />
            </button>
          </form>
          {activeProject && onUpdateProject && (
            <div className={styles.settingsPanel} data-project-settings-panel="true">
              <button
                type="button"
                className={`${styles.settingsToggle} ${settingsOpen ? styles.active : ''}`}
                onClick={() => setSettingsOpen((current) => !current)}
                data-project-settings-toggle="true"
              >
                <Settings size={14} aria-hidden="true" />
                <span className={styles.settingsToggleText}>
                  <span>项目设置</span>
                  <span>{projectTitle(activeProject)}</span>
                </span>
                <ChevronDown size={14} className={styles.chevron} aria-hidden="true" />
              </button>
              {settingsOpen && (
                <ProjectSettingsForm
                  title={editTitle}
                  description={editDescription}
                  instructions={editInstructions}
                  updating={updating}
                  error={settingsError}
                  onTitleChange={setEditTitle}
                  onDescriptionChange={setEditDescription}
                  onInstructionsChange={setEditInstructions}
                  onCancel={() => {
                    setSettingsOpen(false)
                    setSettingsError('')
                  }}
                  onSubmit={handleSettingsSubmit}
                />
              )}
            </div>
          )}
          <button
            type="button"
            className={`${styles.menuItem} ${activeProjectId ? '' : styles.active}`}
            role="option"
            aria-selected={!activeProjectId}
            onClick={() => handleSelect('')}
          >
            <span className={styles.itemText}>
              <span className={styles.itemTitle}>全部会话</span>
              <span className={styles.itemDetail}>工作区会话</span>
            </span>
            {!activeProjectId && <Check size={14} className={styles.checkIcon} aria-hidden="true" />}
          </button>
          {projects.map((project) => {
            const active = project.project_id === activeProjectId
            return (
              <button
                key={project.project_id}
                type="button"
                className={`${styles.menuItem} ${active ? styles.active : ''}`}
                role="option"
                aria-selected={active}
                onClick={() => handleSelect(project.project_id)}
                title={projectTitle(project)}
              >
                <span className={styles.itemText}>
                  <span className={styles.itemTitle}>{projectTitle(project)}</span>
                  <span className={styles.itemDetail}>{project.project_id.slice(-8)}</span>
                </span>
                {active && <Check size={14} className={styles.checkIcon} aria-hidden="true" />}
              </button>
            )
          })}
        </div>,
        document.body,
      )}
    </div>
  )
}
