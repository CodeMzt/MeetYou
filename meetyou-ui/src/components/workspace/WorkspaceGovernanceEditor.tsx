import { useEffect, useMemo, useState } from 'react'
import { Save, SlidersHorizontal } from 'lucide-react'
import { listOperatorSourceProfiles, updateOperatorWorkspaceGovernance } from '../../runtimeApi'
import type { AssistantMode, RuntimeWorkspace, OperatorSourceProfile } from '../../types'
import {
  formatAssistantModeLabel,
  formatCapabilityPolicyLabel,
  formatExecutionTargetLabel,
  formatMemoryRankingPolicyLabel,
  formatRoutingPolicyLabel,
  formatSourceProfileLabel,
} from '../../utils/statusFormatting'
import styles from './WorkspaceGovernanceEditor.module.css'

const FALLBACK_SOURCE_PROFILES: OperatorSourceProfile[] = [
  { profile_name: 'workspace_local', label: '本地工作区知识', description: '优先使用本地文件、记忆和私有工作区知识。', official_only: false, default_freshness: 'workspace' },
  { profile_name: 'study_materials', label: '学习材料', description: '优先使用本地学习材料和用户明确提供的引用。', official_only: false, default_freshness: 'coursework' },
  { profile_name: 'tech_updates', label: '技术更新', description: '官方发布、更新日志、标准和厂商变更。', official_only: true, default_freshness: 'high' },
  { profile_name: 'policy_cn', label: '中国政策', description: '中国政府政策、法规和统计数据。', official_only: true, default_freshness: 'high' },
  { profile_name: 'policy_global', label: '全球政策', description: '中国以外的政府和监管机构来源。', official_only: true, default_freshness: 'high' },
  { profile_name: 'finance_macro', label: '金融与宏观', description: '官方披露、宏观指标和财务公告。', official_only: true, default_freshness: 'high' },
  { profile_name: 'academic_biomed', label: '学术与生医', description: '论文、PubMed、DOI 记录和生物医学文献。', official_only: true, default_freshness: 'medium' },
  { profile_name: 'cyber_threat', label: '安全威胁', description: '官方漏洞和利用通告。', official_only: true, default_freshness: 'high' },
]

const BASE_MODE_OPTIONS: AssistantMode[] = ['general', 'automation', 'danxi']
const EXECUTION_TARGET_OPTIONS = ['core.local', 'workspace_any_endpoint', 'prefer_endpoint_fallback_core']
const TOOL_POLICY_OPTIONS = ['allow_all', 'allowlist']
const ROUTING_POLICY_OPTIONS = ['balanced', 'prefer_origin_endpoint', 'strict_preferred_endpoint']

function normalizeTextList(value: string): string[] {
  const seen = new Set<string>()
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter((item) => {
      if (!item || seen.has(item)) {
        return false
      }
      seen.add(item)
      return true
    })
}

function stringifyRoutingOverrides(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return '{}'
  }
  return JSON.stringify(value, null, 2)
}

function parseRoutingOverrides(value: string): {
  error: string
  normalizedText: string
  overrides: Record<string, unknown>
} {
  const trimmed = value.trim()
  if (!trimmed) {
    return { error: '', normalizedText: '{}', overrides: {} }
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { error: '工具路由覆盖必须是 JSON 对象', normalizedText: trimmed, overrides: {} }
    }
    return {
      error: '',
      normalizedText: stringifyRoutingOverrides(parsed),
      overrides: parsed as Record<string, unknown>,
    }
  } catch {
    return { error: '工具路由覆盖 JSON 格式无效', normalizedText: trimmed, overrides: {} }
  }
}

interface WorkspaceGovernanceEditorProps {
  baseUrl: string
  workspace: RuntimeWorkspace
  onWorkspaceSaved: (workspace: RuntimeWorkspace) => void
}

export default function WorkspaceGovernanceEditor({ baseUrl, workspace, onWorkspaceSaved }: WorkspaceGovernanceEditorProps) {
  const [baseMode, setBaseMode] = useState<AssistantMode>(workspace.base_mode || 'general')
  const [defaultExecutionTarget, setDefaultExecutionTarget] = useState(workspace.default_execution_target || 'core.local')
  const [toolPolicy, setToolPolicy] = useState(workspace.tool_policy || 'allow_all')
  const [allowedToolIdsText, setAllowedToolIdsText] = useState(workspace.allowed_tool_ids.join('\n'))
  const [preferredEndpointIdsText, setPreferredEndpointIdsText] = useState(workspace.preferred_target_endpoint_ids.join('\n'))
  const [preferredProviderTypesText, setPreferredProviderTypesText] = useState(workspace.preferred_endpoint_provider_types.join('\n'))
  const [toolTargetRoutingPolicy, setToolTargetRoutingPolicy] = useState(workspace.tool_target_routing_policy || 'balanced')
  const [routingOverridesText, setRoutingOverridesText] = useState(() => stringifyRoutingOverrides(workspace.tool_routing_overrides))
  const [selectedProfiles, setSelectedProfiles] = useState<string[]>(workspace.preferred_source_profiles)
  const [memoryRankingPolicy, setMemoryRankingPolicy] = useState(workspace.memory_ranking_policy || 'workspace_first')
  const [availableProfiles, setAvailableProfiles] = useState<OperatorSourceProfile[]>(FALLBACK_SOURCE_PROFILES)
  const [loadingProfiles, setLoadingProfiles] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  useEffect(() => {
    setBaseMode(workspace.base_mode || 'general')
    setDefaultExecutionTarget(workspace.default_execution_target || 'core.local')
    setToolPolicy(workspace.tool_policy || 'allow_all')
    setAllowedToolIdsText(workspace.allowed_tool_ids.join('\n'))
    setPreferredEndpointIdsText(workspace.preferred_target_endpoint_ids.join('\n'))
    setPreferredProviderTypesText(workspace.preferred_endpoint_provider_types.join('\n'))
    setToolTargetRoutingPolicy(workspace.tool_target_routing_policy || 'balanced')
    setRoutingOverridesText(stringifyRoutingOverrides(workspace.tool_routing_overrides))
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
  const normalizedAllowedToolIds = useMemo(() => normalizeTextList(allowedToolIdsText), [allowedToolIdsText])
  const normalizedPreferredEndpointIds = useMemo(() => normalizeTextList(preferredEndpointIdsText), [preferredEndpointIdsText])
  const normalizedPreferredProviderTypes = useMemo(() => normalizeTextList(preferredProviderTypesText), [preferredProviderTypesText])
  const parsedRoutingOverrides = useMemo(() => parseRoutingOverrides(routingOverridesText), [routingOverridesText])
  const workspaceRoutingOverridesText = useMemo(
    () => stringifyRoutingOverrides(workspace.tool_routing_overrides),
    [workspace.tool_routing_overrides],
  )

  const hasChanges =
    baseMode !== workspace.base_mode ||
    defaultExecutionTarget !== workspace.default_execution_target ||
    toolPolicy !== workspace.tool_policy ||
    normalizedAllowedToolIds.join('|') !== workspace.allowed_tool_ids.join('|') ||
    normalizedPreferredEndpointIds.join('|') !== workspace.preferred_target_endpoint_ids.join('|') ||
    normalizedPreferredProviderTypes.join('|') !== workspace.preferred_endpoint_provider_types.join('|') ||
    toolTargetRoutingPolicy !== workspace.tool_target_routing_policy ||
    parsedRoutingOverrides.normalizedText !== workspaceRoutingOverridesText ||
    normalizedProfiles.join('|') !== workspace.preferred_source_profiles.join('|') ||
    memoryRankingPolicy !== workspace.memory_ranking_policy

  const handleReset = () => {
    setBaseMode(workspace.base_mode || 'general')
    setDefaultExecutionTarget(workspace.default_execution_target || 'core.local')
    setToolPolicy(workspace.tool_policy || 'allow_all')
    setAllowedToolIdsText(workspace.allowed_tool_ids.join('\n'))
    setPreferredEndpointIdsText(workspace.preferred_target_endpoint_ids.join('\n'))
    setPreferredProviderTypesText(workspace.preferred_endpoint_provider_types.join('\n'))
    setToolTargetRoutingPolicy(workspace.tool_target_routing_policy || 'balanced')
    setRoutingOverridesText(stringifyRoutingOverrides(workspace.tool_routing_overrides))
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
      if (parsedRoutingOverrides.error) {
        setError(parsedRoutingOverrides.error)
        return
      }
      const updated = await updateOperatorWorkspaceGovernance(baseUrl, workspace.workspace_id, {
        base_mode: baseMode,
        default_execution_target: defaultExecutionTarget,
        tool_policy: toolPolicy,
        allowed_tool_ids: normalizedAllowedToolIds,
        preferred_target_endpoint_ids: normalizedPreferredEndpointIds,
        preferred_endpoint_provider_types: normalizedPreferredProviderTypes,
        tool_target_routing_policy: toolTargetRoutingPolicy,
        preferred_source_profiles: normalizedProfiles,
        memory_ranking_policy: memoryRankingPolicy,
        tool_routing_overrides: parsedRoutingOverrides.overrides,
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
          <h3 className={styles.title}>运行治理与路由偏好</h3>
          <p className={styles.subtitle}>调整当前工作区的默认模式、执行目标、工具边界、端点偏好、来源偏好和记忆命中策略。</p>
        </div>
      </div>

      <div className={styles.form}>
        <label className={styles.field}>
          <span className={styles.label}>默认模式</span>
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
          <span className={styles.hint}>当前工作区的默认公开模式。线程没有更具体偏好时，会优先使用这里的设置。</span>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>默认执行目标</span>
          <select
            className={styles.select}
            value={defaultExecutionTarget}
            onChange={(event) => {
              setDefaultExecutionTarget(event.target.value)
              setError('')
              setSuccessMessage('')
            }}
          >
            {EXECUTION_TARGET_OPTIONS.map((target) => (
              <option key={target} value={target}>
                {formatExecutionTargetLabel(target)}
              </option>
            ))}
          </select>
          <span className={styles.hint}>当前选择：{formatExecutionTargetLabel(defaultExecutionTarget)}</span>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>路由策略</span>
          <select
            className={styles.select}
            value={toolTargetRoutingPolicy}
            onChange={(event) => {
              setToolTargetRoutingPolicy(event.target.value)
              setError('')
              setSuccessMessage('')
            }}
          >
            {ROUTING_POLICY_OPTIONS.map((policy) => (
              <option key={policy} value={policy}>
                {formatRoutingPolicyLabel(policy)}
              </option>
            ))}
          </select>
          <span className={styles.hint}>当前策略：{formatRoutingPolicyLabel(toolTargetRoutingPolicy)}</span>
        </label>

        <div className={styles.splitGrid}>
          <label className={styles.field}>
            <span className={styles.label}>工具策略</span>
            <select
              className={styles.select}
              value={toolPolicy}
              onChange={(event) => {
                setToolPolicy(event.target.value)
                setError('')
                setSuccessMessage('')
              }}
            >
              {TOOL_POLICY_OPTIONS.map((policy) => (
                <option key={policy} value={policy}>
                  {formatCapabilityPolicyLabel(policy)}
                </option>
              ))}
            </select>
            <span className={styles.hint}>当前策略：{formatCapabilityPolicyLabel(toolPolicy)}</span>
          </label>

          <label className={styles.field}>
            <span className={styles.label}>允许工具</span>
            <textarea
              className={styles.textarea}
              rows={3}
              value={allowedToolIdsText}
              onChange={(event) => {
                setAllowedToolIdsText(event.target.value)
                setError('')
                setSuccessMessage('')
              }}
            />
            <span className={styles.hint}>已设置 {normalizedAllowedToolIds.length} 个工具。</span>
          </label>
        </div>

        <div className={styles.splitGrid}>
          <label className={styles.field}>
            <span className={styles.label}>偏好端点</span>
            <textarea
              className={styles.textarea}
              rows={3}
              value={preferredEndpointIdsText}
              onChange={(event) => {
                setPreferredEndpointIdsText(event.target.value)
                setError('')
                setSuccessMessage('')
              }}
            />
            <span className={styles.hint}>已设置 {normalizedPreferredEndpointIds.length} 个端点。</span>
          </label>

          <label className={styles.field}>
            <span className={styles.label}>Provider 偏好</span>
            <textarea
              className={styles.textarea}
              rows={3}
              value={preferredProviderTypesText}
              onChange={(event) => {
                setPreferredProviderTypesText(event.target.value)
                setError('')
                setSuccessMessage('')
              }}
            />
            <span className={styles.hint}>已设置 {normalizedPreferredProviderTypes.length} 个 Provider 类型。</span>
          </label>
        </div>

        <label className={styles.field}>
          <span className={styles.label}>工具路由覆盖</span>
          <textarea
            className={styles.textarea}
            rows={5}
            value={routingOverridesText}
            onChange={(event) => {
              setRoutingOverridesText(event.target.value)
              setError('')
              setSuccessMessage('')
            }}
          />
          <span className={parsedRoutingOverrides.error ? styles.error : styles.hint}>
            {parsedRoutingOverrides.error || `已设置 ${Object.keys(parsedRoutingOverrides.overrides).length} 条工具覆盖。`}
          </span>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>偏好来源</span>
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
                    <span className={styles.optionChipBadge}>{profile.default_freshness || '默认'}</span>
                  </span>
                </button>
              )
            })}
          </div>
          <span className={styles.hint}>
            {loadingProfiles
              ? '正在加载来源档案目录...'
              : `当前选择：${normalizedProfiles.length > 0 ? normalizedProfiles.map((item) => formatSourceProfileLabel(item)).join(' / ') : '无'}`}
          </span>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>记忆排序</span>
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
          <span className={styles.hint}>当前固定为“当前工作区优先”，优先命中当前工作区相关记忆。</span>
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
          <button className={styles.primaryButton} type="button" onClick={handleSave} disabled={saving || !hasChanges || Boolean(parsedRoutingOverrides.error)}>
            <Save size={14} /> {saving ? '保存中...' : '保存治理'}
          </button>
        </div>
      </div>
    </section>
  )
}
