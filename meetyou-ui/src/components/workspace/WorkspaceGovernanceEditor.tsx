import { useEffect, useMemo, useState } from 'react'
import { Save, SlidersHorizontal } from 'lucide-react'
import { listOperatorSourceProfiles, updateOperatorWorkspaceGovernance } from '../../clientApi'
import type { AssistantMode, ClientWorkspace, OperatorSourceProfile } from '../../types'
import { formatAssistantModeLabel, formatMemoryRankingPolicyLabel, formatSourceProfileLabel } from '../../utils/statusFormatting'
import styles from './WorkspaceGovernanceEditor.module.css'

const FALLBACK_SOURCE_PROFILES: OperatorSourceProfile[] = [
  { profile_name: 'workspace_local', label: 'Workspace / Local Knowledge', description: 'Prefer local files, memory, and private workspace knowledge.', official_only: false, default_freshness: 'workspace' },
  { profile_name: 'study_materials', label: 'Study Materials', description: 'Prefer local learning materials and explicit references from the user.', official_only: false, default_freshness: 'coursework' },
  { profile_name: 'tech_updates', label: 'Tech Updates', description: 'Official releases, changelogs, standards, and vendor updates.', official_only: true, default_freshness: 'high' },
  { profile_name: 'policy_cn', label: 'Policy China', description: 'Chinese government policy, regulation, and statistics.', official_only: true, default_freshness: 'high' },
  { profile_name: 'policy_global', label: 'Policy Global', description: 'Government and regulator sources outside China.', official_only: true, default_freshness: 'high' },
  { profile_name: 'finance_macro', label: 'Finance / Macro', description: 'Official filings, macro indicators, and financial disclosures.', official_only: true, default_freshness: 'high' },
  { profile_name: 'academic_biomed', label: 'Academic / Biomed', description: 'Papers, PubMed, DOI records, and biomedical literature.', official_only: true, default_freshness: 'medium' },
  { profile_name: 'cyber_threat', label: 'Cyber Threat', description: 'Official vulnerability and exploit advisories.', official_only: true, default_freshness: 'high' },
]

const BASE_MODE_OPTIONS: AssistantMode[] = ['general', 'research', 'documents', 'study', 'automation', 'danxi']

interface WorkspaceGovernanceEditorProps {
  baseUrl: string
  workspace: ClientWorkspace
  onWorkspaceSaved: (workspace: ClientWorkspace) => void
}

export default function WorkspaceGovernanceEditor({ baseUrl, workspace, onWorkspaceSaved }: WorkspaceGovernanceEditorProps) {
  const [baseMode, setBaseMode] = useState<AssistantMode>(workspace.base_mode || 'general')
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>(workspace.preferred_source_profiles)
  const [memoryRankingPolicy, setMemoryRankingPolicy] = useState(workspace.memory_ranking_policy || 'workspace_first')
  const [availableProfiles, setAvailableProfiles] = useState<OperatorSourceProfile[]>(FALLBACK_SOURCE_PROFILES)
  const [loadingProfiles, setLoadingProfiles] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    setBaseMode(workspace.base_mode || 'general')
    setSelectedProfiles(workspace.preferred_source_profiles)
    setMemoryRankingPolicy(workspace.memory_ranking_policy || 'workspace_first')
    setError('')
    setSuccessMessage('')
  }, [workspace])

  useEffect(() => {
    let cancelled = false
    const loadProfiles = async () => {
      try {
        setLoadingProfiles(true)
        const nextProfiles = await listOperatorSourceProfiles(baseUrl)
        if (!cancelled && nextProfiles.length > 0) {
          setAvailableProfiles(nextProfiles)
        }
      } catch {
        if (!cancelled) {
          setAvailableProfiles(FALLBACK_SOURCE_PROFILES)
        }
      } finally {
        if (!cancelled) {
          setLoadingProfiles(false)
        }
      }
    }
    void loadProfiles()
    return () => {
      cancelled = true
    }
  }, [baseUrl])

  const normalizedProfiles = useMemo(() => {
    const seen = new Set<string>()
    return selectedProfiles.filter((item) => {
      const normalized = String(item || '').trim()
      if (!normalized || seen.has(normalized)) {
        return false
      }
      seen.add(normalized)
      return true
    })
  }, [selectedProfiles])
  const hasChanges =
    baseMode !== workspace.base_mode ||
    normalizedProfiles.join('|') !== workspace.preferred_source_profiles.join('|') ||
    memoryRankingPolicy !== workspace.memory_ranking_policy

  const handleReset = () => {
    setBaseMode(workspace.base_mode || 'general')
    setSelectedProfiles(workspace.preferred_source_profiles)
    setMemoryRankingPolicy(workspace.memory_ranking_policy || 'workspace_first')
    setError('')
    setSuccessMessage('')
  }

  const toggleProfile = (profileName: string) => {
    setSelectedProfiles((current) =>
      current.includes(profileName)
        ? current.filter((item) => item !== profileName)
        : [...current, profileName],
    )
    setError('')
    setSuccessMessage('')
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      setError('')
      setSuccessMessage('')
      const updated = await updateOperatorWorkspaceGovernance(baseUrl, workspace.workspace_id, {
        base_mode: baseMode,
        preferred_source_profiles: normalizedProfiles,
        memory_ranking_policy: memoryRankingPolicy,
      })
      onWorkspaceSaved(updated)
      window.ipcRenderer?.send('workspace-governance-updated', { workspace_id: updated.workspace_id })
      setSuccessMessage('工作区治理已保存')
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '保存工作区治理失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={styles.card}>
      <div className={styles.header}>
        <div>
          <div className={styles.kicker}>治理编辑</div>
          <h3 className={styles.title}>来源偏好与记忆排序</h3>
          <p className={styles.subtitle}>用于调整当前 workspace 的默认来源偏好。Procedure 推荐来源仍优先于这里的 workspace 偏好。</p>
        </div>
      </div>

      <div className={styles.form}>
        <label className={styles.field}>
          <span className={styles.label}>Base Mode</span>
          <select
            className={styles.select}
            value={baseMode}
            onChange={(event) => {
              setBaseMode(event.target.value as AssistantMode)
              setError('')
              setSuccessMessage('')
            }}
          >
            {BASE_MODE_OPTIONS.map((mode) => (
              <option key={mode} value={mode}>
                {formatAssistantModeLabel(mode)}
              </option>
            ))}
          </select>
          <span className={styles.hint}>当前工作区默认模式。若 thread 没有更具体的偏好，会优先以这里作为公开模式入口。</span>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Preferred Source Profiles</span>
          <div className={styles.optionGrid}>
            {availableProfiles.map((profile) => {
              const selected = normalizedProfiles.includes(profile.profile_name)
              return (
                <button
                  key={profile.profile_name}
                  className={styles.optionChip}
                  data-selected={selected}
                  type="button"
                  onClick={() => toggleProfile(profile.profile_name)}
                  title={profile.description || profile.label || profile.profile_name}
                >
                  <span>{formatSourceProfileLabel(profile.profile_name)}</span>
                  <span className={styles.optionChipMeta}>
                    {profile.official_only ? <span className={styles.optionChipBadge}>官方优先</span> : null}
                    <span className={styles.optionChipBadge}>{profile.default_freshness || 'default'}</span>
                  </span>
                </button>
              )
            })}
          </div>
          <span className={styles.hint}>
            {loadingProfiles ? '正在加载 source profile 目录...' : `当前选择：${normalizedProfiles.length > 0 ? normalizedProfiles.map((item) => formatSourceProfileLabel(item)).join(' / ') : '无'}`}
          </span>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Memory Ranking Policy</span>
          <select
            className={styles.select}
            value={memoryRankingPolicy}
            onChange={(event) => {
              setMemoryRankingPolicy(event.target.value)
              setError('')
              setSuccessMessage('')
            }}
          >
            <option value="workspace_first">{formatMemoryRankingPolicyLabel('workspace_first')}</option>
          </select>
          <span className={styles.hint}>当前实现固定为 workspace-first，优先命中当前工作区相关记忆。</span>
        </label>
      </div>

      <div className={styles.actions}>
        <div className={styles.status}>
          {error ? <span className={styles.error}>{error}</span> : null}
          {!error && successMessage ? <span className={styles.success}>{successMessage}</span> : null}
          {!error && !successMessage ? <span>工作区：{workspace.title || workspace.workspace_id}</span> : null}
        </div>
        <div className={styles.buttonRow}>
          <button className={styles.secondaryButton} type="button" onClick={handleReset} disabled={saving || !hasChanges}>
            <SlidersHorizontal size={14} /> 重置
          </button>
          <button className={styles.primaryButton} type="button" onClick={handleSave} disabled={saving || !hasChanges}>
            <Save size={14} /> {saving ? '保存中...' : '保存治理'}
          </button>
        </div>
      </div>
    </section>
  )
}
