import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchWithAuth, readErrorMessage } from '../apiClient'
import { buildConfigGroups, getConfigFieldSchema } from '../configSchema'
import { parseUiProtocolSchemaEnvelope } from '../protocolClient'
import { DEFAULT_BASE_URL } from '../windowBridge'
import type {
  ConfigEntry,
  ConfigFieldSchema,
  ConfigFormValue,
  ConfigPatchResult,
  ResolvedConfigField,
  UiProtocolSchema,
} from '../types'

function toFormValue(entry: ConfigEntry | null, schema: ConfigFieldSchema): ConfigFormValue {
  if (!entry) {
    return schema.input === 'boolean' ? false : ''
  }

  if (entry.is_secret) {
    return ''
  }

  if (schema.input === 'boolean') {
    return Boolean(entry.value)
  }

  if (schema.input === 'list') {
    return Array.isArray(entry.value) ? entry.value.map(String).join('\n') : ''
  }

  if (schema.input === 'json') {
    if (entry.value == null || entry.value === '') {
      return ''
    }
    if (typeof entry.value === 'string') {
      return entry.value
    }
    try {
      return JSON.stringify(entry.value, null, 2)
    } catch {
      return String(entry.value)
    }
  }

  if (schema.input === 'number') {
    return entry.value == null || entry.value === '' ? '' : String(entry.value)
  }

  return entry.value == null ? '' : String(entry.value)
}

function serializeFormValue(value: ConfigFormValue, schema: ConfigFieldSchema): unknown {
  if (schema.input === 'boolean') {
    return Boolean(value)
  }

  const text = typeof value === 'string' ? value : String(value)

  if (schema.input === 'list') {
    return text
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean)
  }

  if (schema.input === 'json') {
    const trimmed = text.trim()
    if (trimmed === '') {
      return {}
    }
    try {
      return JSON.parse(trimmed)
    } catch {
      return trimmed
    }
  }

  if (schema.input === 'number') {
    const trimmed = text.trim()
    return trimmed === '' ? '' : Number(trimmed)
  }

  return text.trim()
}

function normalizeEntryValue(entry: ConfigEntry | null, schema: ConfigFieldSchema): unknown {
  if (!entry) {
    return schema.input === 'boolean' ? false : schema.input === 'list' ? [] : ''
  }

  if (entry.is_secret) {
    return ''
  }

  if (schema.input === 'boolean') {
    return Boolean(entry.value)
  }

  if (schema.input === 'list') {
    return Array.isArray(entry.value) ? entry.value.map(String) : []
  }

  if (schema.input === 'json') {
    if (entry.value == null || entry.value === '') {
      return {}
    }
    if (typeof entry.value === 'string') {
      try {
        return JSON.parse(entry.value)
      } catch {
        return entry.value.trim()
      }
    }
    return entry.value
  }

  if (schema.input === 'number') {
    return entry.value == null || entry.value === '' ? '' : Number(entry.value)
  }

  return entry.value == null ? '' : String(entry.value).trim()
}

function validateField(key: string, value: ConfigFormValue, schema: ConfigFieldSchema): string | null {
  if (schema.input === 'number') {
    const text = typeof value === 'string' ? value.trim() : String(value)
    if (!text) {
      return null
    }
    if (!/^-?\d+$/.test(text)) {
      return '请输入整数'
    }
    const numericValue = Number(text)
    if (!Number.isFinite(numericValue)) {
      return '请输入有效数字'
    }
    if (numericValue < 0) {
      return '请输入不小于 0 的值'
    }
    if (key === 'gateway_port' && numericValue > 65535) {
      return '端口需在 0 - 65535 之间'
    }
    return null
  }

  if (schema.input === 'select') {
    const text = typeof value === 'string' ? value.trim() : String(value)
    if (!text) {
      return null
    }
    if (!schema.options?.some((option) => option.value === text)) {
      return '请选择有效选项'
    }
    return null
  }

  const text = typeof value === 'string' ? value.trim() : String(value)
  if (!text) {
    return null
  }

  if (schema.input === 'json') {
    try {
      JSON.parse(text)
    } catch {
      return '请输入有效的 JSON'
    }
    return null
  }

  if (key.endsWith('_url') || key === 'mcp_registry_url') {
    try {
      new URL(text)
    } catch {
      return '请输入有效 URL'
    }
  }

  return null
}

function valuesEqual(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function sortFields(fields: ResolvedConfigField[]): ResolvedConfigField[] {
  return [...fields].sort((left, right) => {
    if (left.schema.advanced !== right.schema.advanced) {
      return left.schema.advanced ? 1 : -1
    }
    return left.schema.title.localeCompare(right.schema.title, 'zh-CN')
  })
}

export function useConfig(baseUrl: string = DEFAULT_BASE_URL) {
  const [config, setConfig] = useState<Record<string, ConfigEntry>>({})
  const [uiSchema, setUiSchema] = useState<UiProtocolSchema | null>(null)
  const [formValues, setFormValues] = useState<Record<string, ConfigFormValue>>({})
  const [touchedFields, setTouchedFields] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveResult, setSaveResult] = useState<ConfigPatchResult | null>(null)

  const fetchConfig = useCallback(
    async (preserveSaveResult = false) => {
      try {
        setLoading(true)
        const [schemaResponse, configResponse] = await Promise.all([
          fetchWithAuth(`${baseUrl}/desktop/config/schema`),
          fetchWithAuth(`${baseUrl}/desktop/config`),
        ])

        if (!schemaResponse.ok) {
          const failure = await readErrorMessage(schemaResponse, '获取协议定义失败')
          throw new Error(failure.message)
        }
        if (!configResponse.ok) {
          const failure = await readErrorMessage(configResponse, '获取配置失败')
          throw new Error(failure.message)
        }

        const schemaPayload = parseUiProtocolSchemaEnvelope(await schemaResponse.json())
        if (!schemaPayload) {
          throw new Error('解析协议定义失败')
        }

        const data = await configResponse.json()
        const nextConfig: Record<string, ConfigEntry> = data.items ?? {}
        const nextFormValues: Record<string, ConfigFormValue> = {}

        Object.keys(nextConfig).forEach((key) => {
          const entry = nextConfig[key]
          const schema = getConfigFieldSchema(key, entry, schemaPayload)
          nextFormValues[key] = toFormValue(entry, schema)
        })

        setUiSchema(schemaPayload)
        setConfig(nextConfig)
        setFormValues(nextFormValues)
        setTouchedFields({})
        setError(null)
        if (!preserveSaveResult) {
          setSaveResult(null)
        }
      } catch (fetchError) {
        setError(fetchError instanceof Error ? fetchError.message : '获取配置失败')
      } finally {
        setLoading(false)
      }
    },
    [baseUrl],
  )

  useEffect(() => {
    void fetchConfig()
  }, [fetchConfig])

  const resolvedFields = useMemo(() => {
    const keys = Object.keys(config).sort((left, right) => left.localeCompare(right, 'en'))
    const fields = keys.map((key) => {
      const entry = config[key] ?? null
      const schema = getConfigFieldSchema(key, entry, uiSchema)
      const formValue = formValues[key] ?? toFormValue(entry, schema)
      const serializedValue = serializeFormValue(formValue, schema)
      const normalizedValue = normalizeEntryValue(entry, schema)
      const dirty = entry?.is_secret ? Boolean(touchedFields[key]) : !valuesEqual(serializedValue, normalizedValue)
      const validationError = validateField(key, formValue, schema)

      return {
        key,
        schema,
        entry,
        value: formValue,
        dirty,
        error: validationError,
      }
    })

    return sortFields(fields)
  }, [config, formValues, touchedFields, uiSchema])

  const groupedFields = useMemo(() => buildConfigGroups(resolvedFields, uiSchema), [resolvedFields, uiSchema])

  const dirtyKeys = useMemo(
    () => resolvedFields.filter((field) => field.dirty).map((field) => field.key),
    [resolvedFields],
  )

  const validationErrors = useMemo(() => {
    const nextErrors: Record<string, string> = {}
    resolvedFields.forEach((field) => {
      if (field.error) {
        nextErrors[field.key] = field.error
      }
    })
    return nextErrors
  }, [resolvedFields])

  const updateField = useCallback((key: string, value: ConfigFormValue) => {
    setFormValues((prev) => ({ ...prev, [key]: value }))
    setTouchedFields((prev) => ({ ...prev, [key]: true }))
    setSaveResult(null)
  }, [])

  const clearSecretField = useCallback((key: string) => {
    setFormValues((prev) => ({ ...prev, [key]: '' }))
    setTouchedFields((prev) => ({ ...prev, [key]: true }))
    setSaveResult(null)
  }, [])

  const resetChanges = useCallback(() => {
    const nextValues: Record<string, ConfigFormValue> = {}
    Object.keys(config).forEach((key) => {
      const entry = config[key]
      const schema = getConfigFieldSchema(key, entry, uiSchema)
      nextValues[key] = toFormValue(entry, schema)
    })
    setFormValues(nextValues)
    setTouchedFields({})
    setSaveResult(null)
    setError(null)
  }, [config, uiSchema])

  const saveConfig = useCallback(async () => {
    const dirtyFields = resolvedFields.filter((field) => field.dirty)
    if (dirtyFields.length === 0) {
      return false
    }

    const invalidDirtyField = dirtyFields.find((field) => field.error)
    if (invalidDirtyField) {
      setError('请先修正校验错误后再保存')
      return false
    }

    const updates: Record<string, unknown> = {}
    dirtyFields.forEach((field) => {
      updates[field.key] = serializeFormValue(field.value, field.schema)
    })

    try {
      setSaving(true)
      setError(null)

      const response = await fetchWithAuth(`${baseUrl}/desktop/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates }),
      })

      if (!response.ok) {
        const failure = await readErrorMessage(response, '更新配置失败')
        throw new Error(failure.message)
      }

      const result: ConfigPatchResult = await response.json()
      await fetchConfig(true)
      setSaveResult(result)
      return true
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '更新配置失败')
      return false
    } finally {
      setSaving(false)
    }
  }, [baseUrl, fetchConfig, resolvedFields])

  return {
    config,
    uiSchema,
    groupedFields,
    resolvedFields,
    loading,
    saving,
    error,
    saveResult,
    dirtyKeys,
    validationErrors,
    hasDirtyChanges: dirtyKeys.length > 0,
    updateField,
    clearSecretField,
    resetChanges,
    refresh: fetchConfig,
    saveConfig,
  }
}
