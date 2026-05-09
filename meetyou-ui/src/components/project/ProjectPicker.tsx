import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Folder, Layers3, Plus } from 'lucide-react'
import type { RuntimeProject } from '../../types'
import styles from './ProjectPicker.module.css'

interface ProjectPickerProps {
  projects: RuntimeProject[]
  activeProjectId: string
  onSelectProject: (projectId: string) => unknown | Promise<unknown>
  onCreateProject: (title: string) => RuntimeProject | Promise<RuntimeProject | null> | null
}

function projectTitle(project: RuntimeProject): string {
  return String(project.title || project.project_id || '').trim() || 'Untitled Project'
}

export default function ProjectPicker({
  projects,
  activeProjectId,
  onSelectProject,
  onCreateProject,
}: ProjectPickerProps) {
  const [open, setOpen] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [creating, setCreating] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const activeProject = useMemo(
    () => projects.find((project) => project.project_id === activeProjectId) ?? null,
    [activeProjectId, projects],
  )
  const triggerTitle = activeProject ? projectTitle(activeProject) : 'All Threads'

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
      setOpen(false)
    } finally {
      setCreating(false)
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
          aria-label="Select project"
        >
          <form className={styles.createForm} onSubmit={handleCreate}>
            <input
              className={styles.createInput}
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              placeholder="New project"
              maxLength={80}
            />
            <button type="submit" className={styles.iconButton} title="Create project" disabled={creating || !draftTitle.trim()}>
              <Plus size={14} aria-hidden="true" />
            </button>
          </form>
          <button
            type="button"
            className={`${styles.menuItem} ${activeProjectId ? '' : styles.active}`}
            role="option"
            aria-selected={!activeProjectId}
            onClick={() => handleSelect('')}
          >
            <span className={styles.itemText}>
              <span className={styles.itemTitle}>All Threads</span>
              <span className={styles.itemDetail}>Workspace threads</span>
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
