import { useMemo, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  KeyRound,
  RefreshCcw,
  RotateCcw,
  Save,
} from 'lucide-react'
import GlassSelect from '../components/GlassSelect'
import { useConfig } from '../hooks/useConfig'
import type { ConfigFormValue, ResolvedConfigField } from '../types'

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
        <span>{field.entry?.source === 'env' ? '来源 env' : field.entry?.source === 'config' ? '来源 config' : '默认值'}</span>
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
  const placeholder =
    field.entry?.is_secret && field.entry.has_value
      ? String(field.entry.value || '已配置')
      : field.schema.placeholder || ''

  let control = null

  if (field.schema.input === 'boolean') {
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
        <FieldStatus field={field} onClear={onClearSecret} saving={saving} />
      </div>

      <div className="settings-field-control">{control}</div>

      {field.error ? (
        <div className="settings-field-error">
          <AlertCircle size={13} />
          <span>{field.error}</span>
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

  const [advancedOpen, setAdvancedOpen] = useState<Record<string, boolean>>({})

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
          <div className="settings-kicker">Settings</div>
          <h2 className="settings-title">系统配置中心</h2>
          <div className="settings-subtitle">常用配置直接编辑，高级配置按分组折叠展示。</div>
        </div>

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
      </div>

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
    </div>
  )
}
