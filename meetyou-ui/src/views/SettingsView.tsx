import { useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  FolderOpen,
  KeyRound,
  RefreshCcw,
  RotateCcw,
  Save,
  Search,
  X,
} from 'lucide-react'
import GlassSelect from '../components/GlassSelect'
import { useConfig } from '../hooks/useConfig'
import { fetchWithAuth, readErrorMessage } from '../apiClient'
import { fetchRuntimeBuildInfo, type RuntimeBuildInfoSnapshot } from '../buildInfo'
import type { ConfigFormValue, ResolvedConfigField, SkillDetail, SkillListItem } from '../types'
import { DEFAULT_BASE_URL } from '../windowBridge'

type SettingsTab = 'config' | 'skills'
type SkillTypeFilter = 'all' | 'mode' | 'reusable'

const SKILL_TYPE_FILTERS: Array<{ value: SkillTypeFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'mode', label: '模式' },
  { value: 'reusable', label: '可复用' },
]

function getIpcInvoke() {
  return typeof window !== 'undefined' ? window.ipcRenderer?.invoke : undefined
}

function parseListValue(value: ConfigFormValue): string[] {
  const text = typeof value === 'string' ? value : String(value)
  return text
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function formatListValue(items: string[]): string {
  return Array.from(new Set(items.map((item) => item.trim()).filter(Boolean))).join('\n')
}

function includesQuery(skill: SkillListItem, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase()
  if (!normalizedQuery) {
    return true
  }
  return [
    skill.id,
    skill.title,
    skill.summary,
    skill.skill_type,
    skill.storage_path,
    ...skill.applicable_modes,
    ...skill.scenarios,
    ...skill.recommended_tools,
  ]
    .join('\n')
    .toLowerCase()
    .includes(normalizedQuery)
}

function FieldStatus({
  field,
  onClear,
  saving,
}: {
  field: ResolvedConfigField
  onClear: (key: string) => void
  saving: boolean
}) {
  if (!field.entry?.is_secret) {
    return (
      <div className="settings-field-meta">
        <span>{field.entry?.source === 'env' ? '来源：环境变量' : field.entry?.source === 'config' ? '来源：配置文件' : '默认值'}</span>
      </div>
    )
  }

  return (
    <div className="settings-field-meta">
      <span className={`secret-badge ${field.entry?.has_value ? 'configured' : ''}`}>
        {field.entry?.has_value ? '已配置' : '未配置'}
      </span>
      {field.entry?.env_key ? <span>{field.entry.env_key}</span> : null}
      {field.entry?.has_value ? (
        <button className="field-inline-btn" onClick={() => onClear(field.key)} disabled={saving}>
          清除
        </button>
      ) : null}
    </div>
  )
}

function FieldControl({
  field,
  saving,
  onChange,
  onClearSecret,
}: {
  field: ResolvedConfigField
  saving: boolean
  onChange: (key: string, value: ConfigFormValue) => void
  onClearSecret: (key: string) => void
}) {
  const [pickerError, setPickerError] = useState('')
  const placeholder =
    field.entry?.is_secret && field.entry.has_value
      ? String(field.entry.value || '已配置')
      : field.schema.placeholder || ''

  let control = null

  const openDirectoryPicker = async () => {
    const invoke = getIpcInvoke()
    if (!invoke) {
      setPickerError('当前环境不支持系统目录选择，请手动填写路径。')
      return []
    }
    const result = await invoke('select-local-directories')
    const paths = Array.isArray(result?.paths)
      ? result.paths.map((item: unknown) => String(item || '').trim()).filter(Boolean)
      : []
    if (!result?.canceled && paths.length === 0) {
      setPickerError('未选择目录。')
    } else {
      setPickerError('')
    }
    return paths
  }

  if (field.schema.control === 'directory_list' && getIpcInvoke()) {
    const directories = parseListValue(field.value)
    control = (
      <div className="directory-list-control">
        <div className="directory-list-items">
          {directories.length > 0 ? (
            directories.map((directory) => (
              <div className="directory-list-item" key={directory}>
                <span title={directory}>{directory}</span>
                <button
                  className="directory-list-remove"
                  type="button"
                  onClick={() => onChange(field.key, formatListValue(directories.filter((item) => item !== directory)))}
                  disabled={saving}
                  title="移除目录"
                >
                  <X size={13} />
                </button>
              </div>
            ))
          ) : (
            <div className="directory-list-empty">尚未选择目录</div>
          )}
        </div>
        <button
          className="settings-secondary-btn directory-picker-btn"
          type="button"
          onClick={async () => {
            const paths = await openDirectoryPicker()
            if (paths.length) {
              onChange(field.key, formatListValue([...directories, ...paths]))
            }
          }}
          disabled={saving}
        >
          <FolderOpen size={14} />
          <span>添加目录</span>
        </button>
      </div>
    )
  } else if (field.schema.control === 'directory' && getIpcInvoke()) {
    control = (
      <div className="directory-single-control">
        <input
          className="settings-input"
          type="text"
          value={String(field.value)}
          onChange={(event) => onChange(field.key, event.target.value)}
          placeholder={placeholder}
          disabled={saving}
        />
        <button
          className="settings-secondary-btn directory-picker-btn"
          type="button"
          onClick={async () => {
            const paths = await openDirectoryPicker()
            if (paths[0]) {
              onChange(field.key, paths[0])
            }
          }}
          disabled={saving}
        >
          <FolderOpen size={14} />
          <span>选择</span>
        </button>
      </div>
    )
  } else if (field.schema.input === 'boolean') {
    control = (
      <button
        className={`settings-switch ${field.value ? 'checked' : ''}`}
        onClick={() => onChange(field.key, !field.value)}
        disabled={saving}
      >
        <span className="settings-switch-thumb" />
      </button>
    )
  } else if (field.schema.input === 'select') {
    control = (
      <GlassSelect
        wrapperClassName="glass-select-full"
        value={String(field.value)}
        onChange={(event) => onChange(field.key, event.target.value)}
        disabled={saving}
      >
        <option value="">未设置</option>
        {field.schema.options?.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </GlassSelect>
    )
  } else if (field.schema.input === 'list') {
    control = (
      <textarea
        className="settings-input settings-textarea"
        value={String(field.value)}
        onChange={(event) => onChange(field.key, event.target.value)}
        placeholder="一行一个值"
        rows={4}
        disabled={saving}
      />
    )
  } else if (field.schema.input === 'json') {
    control = (
      <textarea
        className="settings-input settings-textarea settings-json"
        value={String(field.value)}
        onChange={(event) => onChange(field.key, event.target.value)}
        placeholder="{}"
        rows={10}
        disabled={saving}
        spellCheck={false}
      />
    )
  } else {
    control = (
      <input
        className="settings-input"
        type={field.schema.input === 'password' ? 'password' : field.schema.input === 'number' ? 'number' : 'text'}
        value={String(field.value)}
        onChange={(event) => onChange(field.key, event.target.value)}
        placeholder={placeholder}
        disabled={saving}
      />
    )
  }

  return (
    <div className="settings-field">
      <div className="settings-field-head">
        <div className="settings-field-title-row">
          <label className="settings-field-title">{field.schema.title}</label>
          {field.dirty ? <span className="dirty-dot" title="有未保存修改" /> : null}
        </div>
        <div className="settings-field-description">{field.schema.description}</div>
        {field.schema.help_text ? <div className="settings-field-help">{field.schema.help_text}</div> : null}
        {field.schema.examples?.length ? (
          <div className="settings-field-examples">
            <span>示例</span>
            {field.schema.examples.map((example) => (
              <code key={example}>{example}</code>
            ))}
          </div>
        ) : null}
        <FieldStatus field={field} onClear={onClearSecret} saving={saving} />
      </div>

      <div className="settings-field-control">{control}</div>

      {pickerError ? (
        <div className="settings-field-error">
          <AlertCircle size={13} />
          <span>{pickerError}</span>
        </div>
      ) : null}

      {field.error ? (
        <div className="settings-field-error">
          <AlertCircle size={13} />
          <span>{field.error}</span>
        </div>
      ) : null}
    </div>
  )
}

function SkillsView({ baseUrl = DEFAULT_BASE_URL }: { baseUrl?: string }) {
  const [skills, setSkills] = useState<SkillListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [selectedSkill, setSelectedSkill] = useState<SkillDetail | null>(null)
  const [query, setQuery] = useState('')
  const [skillType, setSkillType] = useState<SkillTypeFilter>('all')

  const fetchSkills = async () => {
    try {
      setLoading(true)
      setError('')
      const params = new URLSearchParams({ skill_type: skillType })
      const response = await fetchWithAuth(`${baseUrl}/desktop/skills?${params.toString()}`)
      if (!response.ok) {
        const failure = await readErrorMessage(response, '获取 SKILL 列表失败')
        throw new Error(failure.message)
      }
      const data = await response.json()
      setSkills(Array.isArray(data) ? data : [])
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : '获取 SKILL 列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchSkills()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl, skillType])

  const visibleSkills = useMemo(
    () => skills.filter((skill) => includesQuery(skill, query)),
    [query, skills],
  )

  const handleOpenSkill = async (skill: SkillListItem) => {
    try {
      setDetailLoading(true)
      setDetailError('')
      const response = await fetchWithAuth(`${baseUrl}/desktop/skills/${encodeURIComponent(skill.id)}`)
      if (!response.ok) {
        const failure = await readErrorMessage(response, '获取 SKILL 详情失败')
        throw new Error(failure.message)
      }
      const data = await response.json()
      setSelectedSkill(data as SkillDetail)
    } catch (fetchError) {
      setDetailError(fetchError instanceof Error ? fetchError.message : '获取 SKILL 详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  return (
    <div className="skills-page">
      <div className="skills-toolbar">
        <label className="skills-search">
          <Search size={15} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题、场景、工具或路径"
          />
        </label>
        <GlassSelect
          wrapperClassName="skills-filter"
          value={skillType}
          onChange={(event) => setSkillType(event.target.value as SkillTypeFilter)}
          disabled={loading}
        >
          {SKILL_TYPE_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </GlassSelect>
        <button className="settings-secondary-btn" onClick={() => void fetchSkills()} disabled={loading}>
          <RefreshCcw size={14} />
          <span>刷新</span>
        </button>
      </div>

      {error ? (
        <div className="settings-banner error">
          <AlertCircle size={15} />
          <span>{error}</span>
        </div>
      ) : null}

      {detailError ? (
        <div className="settings-banner warning">
          <AlertCircle size={15} />
          <span>{detailError}</span>
        </div>
      ) : null}

      {detailLoading ? <div className="settings-loading">正在加载 SKILL 详情…</div> : null}

      {loading ? <div className="settings-loading">正在加载 SKILL…</div> : null}

      {!loading && visibleSkills.length === 0 ? (
        <div className="settings-empty-group">没有匹配的 SKILL。</div>
      ) : null}

      <div className="skill-list">
        {visibleSkills.map((skill) => (
          <button
            className="skill-list-item"
            type="button"
            key={`${skill.skill_type}:${skill.id}`}
            onClick={() => void handleOpenSkill(skill)}
          >
            <div className="skill-list-main">
              <div className="skill-list-title-row">
                <BookOpen size={15} />
                <strong>{skill.title || skill.id}</strong>
                <span className="skill-type-pill">{skill.skill_type === 'mode' ? '模式' : '可复用'}</span>
                {skill.editable ? <span className="skill-type-pill">可编辑</span> : null}
              </div>
              <p>{skill.summary || '未提供摘要。'}</p>
              <div className="skill-list-path" title={skill.storage_path}>
                {skill.storage_path}
              </div>
            </div>
            <FileText size={15} />
          </button>
        ))}
      </div>

      {selectedSkill ? (
        <div className="skill-detail-overlay" role="dialog" aria-modal="true" aria-label="SKILL 详情">
          <div className="skill-detail-panel">
            <div className="skill-detail-header">
              <div>
                <div className="settings-kicker">SKILL 详情</div>
                <h3>{selectedSkill.title || selectedSkill.id}</h3>
              </div>
              <button
                className="directory-list-remove"
                type="button"
                onClick={() => setSelectedSkill(null)}
                title="关闭"
              >
                <X size={15} />
              </button>
            </div>

            <div className="skill-detail-meta">
              <span>{selectedSkill.skill_type === 'mode' ? '模式 SKILL' : '可复用 SKILL'}</span>
              <span>{selectedSkill.editable ? '项目可编辑' : '只读'}</span>
              {selectedSkill.source ? <span>{selectedSkill.source}</span> : null}
            </div>

            <p className="skill-detail-summary">{selectedSkill.summary || '未提供摘要。'}</p>

            <div className="skill-detail-path" title={selectedSkill.storage_path}>
              {selectedSkill.storage_path}
            </div>

            <div className="skill-detail-grid">
              <div>
                <span>适用模式</span>
                <strong>{selectedSkill.applicable_modes.length ? selectedSkill.applicable_modes.join('、') : '未声明'}</strong>
              </div>
              <div>
                <span>场景</span>
                <strong>{selectedSkill.scenarios.length ? selectedSkill.scenarios.join('、') : '未声明'}</strong>
              </div>
              <div>
                <span>推荐工具</span>
                <strong>{selectedSkill.recommended_tools.length ? selectedSkill.recommended_tools.join('、') : '未声明'}</strong>
              </div>
            </div>

            <div className="skill-detail-content">
              <div className="skill-detail-content-title">内容</div>
              <pre>{selectedSkill.content || '该 SKILL 暂无内容。'}</pre>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default function SettingsView() {
  const {
    groupedFields,
    loading,
    saving,
    error,
    saveResult,
    dirtyKeys,
    hasDirtyChanges,
    updateField,
    clearSecretField,
    resetChanges,
    refresh,
    saveConfig,
  } = useConfig()

  const [activeTab, setActiveTab] = useState<SettingsTab>('config')
  const [advancedOpen, setAdvancedOpen] = useState<Record<string, boolean>>({})
  const [runtimeBuildInfo, setRuntimeBuildInfo] = useState<RuntimeBuildInfoSnapshot | null>(null)

  useEffect(() => {
    void fetchRuntimeBuildInfo(DEFAULT_BASE_URL).then((snapshot) => {
      setRuntimeBuildInfo(snapshot)
    })
  }, [])

  const appliedSummary = useMemo(() => {
    if (!saveResult) {
      return ''
    }
    return `已应用 ${saveResult.applied_keys.length} 项配置`
  }, [saveResult])

  const handleSave = async () => {
    await saveConfig()
  }

  if (loading) {
    return <div className="settings-loading">正在加载设置…</div>
  }

  return (
    <div className="settings-page">
      <div className="settings-header-card">
        <div>
          <div className="settings-kicker">设置中心</div>
          <h2 className="settings-title">系统配置中心</h2>
          <div className="settings-subtitle">常用配置直接编辑，高级配置按分组折叠展示。</div>
        </div>

        {activeTab === 'config' ? (
          <div className="settings-header-actions">
            <button className="settings-secondary-btn" onClick={() => refresh()} disabled={loading || saving}>
              <RefreshCcw size={14} />
              <span>刷新</span>
            </button>
            <button className="settings-secondary-btn" onClick={resetChanges} disabled={!hasDirtyChanges || saving}>
              <RotateCcw size={14} />
              <span>重置</span>
            </button>
            <button className="settings-primary-btn" onClick={handleSave} disabled={!hasDirtyChanges || saving}>
              <Save size={14} />
              <span>{saving ? '保存中…' : `保存更改${dirtyKeys.length ? ` (${dirtyKeys.length})` : ''}`}</span>
            </button>
          </div>
        ) : null}
      </div>

      <div className="settings-tabbar" role="tablist" aria-label="设置分类">
        <button
          className={`settings-tab ${activeTab === 'config' ? 'active' : ''}`}
          type="button"
          onClick={() => setActiveTab('config')}
        >
          配置
        </button>
        <button
          className={`settings-tab ${activeTab === 'skills' ? 'active' : ''}`}
          type="button"
          onClick={() => setActiveTab('skills')}
        >
          SKILL
        </button>
      </div>

      {runtimeBuildInfo ? (
        <div className="settings-version-card">
          <div className="settings-version-row"><strong>界面</strong><span>{runtimeBuildInfo.ui.package_version} · {runtimeBuildInfo.ui.git_commit.slice(0, 12)}</span></div>
          <div className="settings-version-row"><strong>桌面后端</strong><span>{runtimeBuildInfo.desktop_backend ? `${runtimeBuildInfo.desktop_backend.package_version} · ${runtimeBuildInfo.desktop_backend.git_commit.slice(0, 12)}` : '未读取到'}</span></div>
          <div className="settings-version-row"><strong>核心服务</strong><span>{runtimeBuildInfo.core ? `${runtimeBuildInfo.core.package_version} · ${runtimeBuildInfo.core.git_commit.slice(0, 12)}` : '未读取到'}</span></div>
        </div>
      ) : null}

      {runtimeBuildInfo?.warning ? (
        <div className="settings-banner warning">
          <AlertCircle size={15} />
          <span>{runtimeBuildInfo.warning}</span>
        </div>
      ) : null}

      {error ? (
        <div className="settings-banner error">
          <AlertCircle size={15} />
          <span>{error}</span>
        </div>
      ) : null}

      {saveResult ? (
        <div className="settings-banner success">
          <CheckCircle2 size={15} />
          <div className="settings-banner-copy">
            <span>{appliedSummary}</span>
            {saveResult.reloaded_components.length > 0 ? (
              <span>已热更新：{saveResult.reloaded_components.join(', ')}</span>
            ) : null}
            {saveResult.restart_required_keys.length > 0 ? (
              <span>需重启生效：{saveResult.restart_required_keys.join(', ')}</span>
            ) : null}
            {saveResult.warnings.length > 0 ? (
              <span>提示：{saveResult.warnings.join('；')}</span>
            ) : null}
          </div>
        </div>
      ) : null}

      {activeTab === 'skills' ? <SkillsView /> : null}

      {activeTab === 'config' ? (
      <div className="settings-group-list">
        {groupedFields.map((group) => {
          const isAdvancedOpen = Boolean(advancedOpen[group.key])

          return (
            <section key={group.key} className="settings-group-card">
              <div className="settings-group-header">
                <div>
                  <div className="settings-group-title-row">
                    {group.key === 'secrets' ? <KeyRound size={15} /> : null}
                    <h3 className="settings-group-title">{group.title}</h3>
                  </div>
                  <div className="settings-group-description">{group.description}</div>
                </div>
              </div>

              {group.commonFields.length > 0 ? (
                <div className="settings-field-grid">
                  {group.commonFields.map((field) => (
                    <FieldControl
                      key={field.key}
                      field={field}
                      saving={saving}
                      onChange={updateField}
                      onClearSecret={clearSecretField}
                    />
                  ))}
                </div>
              ) : (
                <div className="settings-empty-group">当前分组没有常用配置项。</div>
              )}

              {group.advancedFields.length > 0 ? (
                <div className="settings-advanced">
                  <button
                    className="settings-advanced-toggle"
                    onClick={() =>
                      setAdvancedOpen((prev) => ({
                        ...prev,
                        [group.key]: !prev[group.key],
                      }))
                    }
                  >
                    <div className="settings-advanced-toggle-copy">
                      {isAdvancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      <span>高级配置</span>
                    </div>
                    <span className="settings-advanced-count">{group.advancedFields.length} 项</span>
                  </button>

                  {isAdvancedOpen ? (
                    <div className="settings-field-grid advanced">
                      {group.advancedFields.map((field) => (
                        <FieldControl
                          key={field.key}
                          field={field}
                          saving={saving}
                          onChange={updateField}
                          onClearSecret={clearSecretField}
                        />
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>
          )
        })}
      </div>
      ) : null}
    </div>
  )
}
