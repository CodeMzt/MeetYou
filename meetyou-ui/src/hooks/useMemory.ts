import { useState, useEffect, useCallback } from 'react'

import { clearDesktopMemory, deleteDesktopMemoryRecord, updateDesktopMemoryRecordStatus } from '../runtimeApi'
import { fetchWithAuth, readErrorMessage } from '../apiClient'
import { DEFAULT_BASE_URL } from '../windowBridge'

export interface MemoryRecord {
  id: string
  type: string
  content: string
  label?: string
  status: string
  strength: number
  importance: number
  confidence: number
  created_at: string
  last_accessed_at?: string
  last_updated_at: string
  access_count?: number
  tags: string[]
  entity_keys?: string[]
  source_record_ids?: string[]
  scope?: {
    user_id: string
    session_id: string
  }
  fact_key?: string
  fact_value?: string
}

export interface MemoryEdge {
  from_id?: string
  to_id?: string
  source?: string
  target?: string
  semantic_sim: number
  same_entity: boolean
  same_project: boolean
  derived_from: boolean
  contradicts: boolean
}

export interface MemoryStats {
  record_count: number
  edge_count: number
  by_type: Record<string, number>
}

export interface WorkingSummaries {
  global_summary: string
  session_summary: string
}

export interface MemorySnapshot {
  working_summaries: WorkingSummaries
  records: MemoryRecord[]
  edges: MemoryEdge[]
  stats: MemoryStats
}

export interface MemoryGraph {
  working_summaries: WorkingSummaries
  nodes: MemoryRecord[]
  edges: MemoryEdge[]
  stats: MemoryStats
}

export interface MemoryClearFeedback {
  ok: boolean
  message: string
  updatedAt: string
  clearedRecordCount: number
  clearedEdgeCount: number
  clearedSessionSummaryCount: number
  clearedGlobalSummary: boolean
  clearedSessionCount: number
  activeSessionCount: number
}

export function useMemory(baseUrl: string = DEFAULT_BASE_URL) {
  const [snapshot, setSnapshot] = useState<MemorySnapshot | null>(null)
  const [graph, setGraph] = useState<MemoryGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [clearing, setClearing] = useState(false)
  const [mutatingRecordIds, setMutatingRecordIds] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [clearFeedback, setClearFeedback] = useState<MemoryClearFeedback | null>(null)

  const fetchMemory = useCallback(async (includeInvalidated = false) => {
    try {
      setLoading(true)
      const [resSnapshot, resGraph] = await Promise.all([
        fetchWithAuth(`${baseUrl}/desktop/memory?include_invalidated=${includeInvalidated}`),
        fetchWithAuth(`${baseUrl}/desktop/memory/graph?include_invalidated=${includeInvalidated}`),
      ])
      if (!resSnapshot.ok) {
        const failure = await readErrorMessage(resSnapshot, '读取记忆快照失败')
        throw new Error(failure.message)
      }
      if (!resGraph.ok) {
        const failure = await readErrorMessage(resGraph, '读取记忆图谱失败')
        throw new Error(failure.message)
      }
      const [dataSnapshot, dataGraph] = await Promise.all([resSnapshot.json(), resGraph.json()])
      setSnapshot(dataSnapshot)
      setGraph(dataGraph)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [baseUrl])

  const clearMemory = useCallback(async () => {
    try {
      setClearing(true)
      setError(null)
      const result = await clearDesktopMemory(baseUrl)
      setClearFeedback({
        ok: result.ok,
        message: `已清理 ${result.cleared_record_count} 条记忆、${result.cleared_edge_count} 条关系和 ${result.cleared_session_summary_count} 条会话摘要。`,
        updatedAt: result.updated_at,
        clearedRecordCount: result.cleared_record_count,
        clearedEdgeCount: result.cleared_edge_count,
        clearedSessionSummaryCount: result.cleared_session_summary_count,
        clearedGlobalSummary: result.cleared_global_summary,
        clearedSessionCount: result.cleared_session_count,
        activeSessionCount: result.active_session_count,
      })
      await fetchMemory()
      return result
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      throw err
    } finally {
      setClearing(false)
    }
  }, [baseUrl, fetchMemory])

  const markRecordMutation = useCallback((memoryId: string, mutating: boolean) => {
    setMutatingRecordIds((current) => {
      const next = new Set(current)
      if (mutating) {
        next.add(memoryId)
      } else {
        next.delete(memoryId)
      }
      return next
    })
  }, [])

  const updateRecordStatus = useCallback(async (memoryId: string, status: 'active' | 'invalidated') => {
    try {
      markRecordMutation(memoryId, true)
      setError(null)
      const result = await updateDesktopMemoryRecordStatus(baseUrl, memoryId, status)
      await fetchMemory(true)
      return result
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      throw err
    } finally {
      markRecordMutation(memoryId, false)
    }
  }, [baseUrl, fetchMemory, markRecordMutation])

  const deleteRecord = useCallback(async (memoryId: string) => {
    try {
      markRecordMutation(memoryId, true)
      setError(null)
      const result = await deleteDesktopMemoryRecord(baseUrl, memoryId)
      await fetchMemory(true)
      return result
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      throw err
    } finally {
      markRecordMutation(memoryId, false)
    }
  }, [baseUrl, fetchMemory, markRecordMutation])

  useEffect(() => {
    fetchMemory()
  }, [fetchMemory])

  return {
    snapshot,
    graph,
    loading,
    clearing,
    mutatingRecordIds,
    error,
    clearFeedback,
    refresh: fetchMemory,
    clearMemory,
    updateRecordStatus,
    deleteRecord,
  }
}
