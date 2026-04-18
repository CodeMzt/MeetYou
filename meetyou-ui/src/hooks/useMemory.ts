import { useState, useEffect, useCallback } from 'react';

import { fetchWithAuth, readErrorMessage } from '../apiClient';
import { DEFAULT_BASE_URL } from '../windowBridge';

export interface MemoryRecord {
  id: string;
  type: string;
  content: string;
  label?: string;
  status: string;
  strength: number;
  importance: number;
  confidence: number;
  created_at: string;
  last_accessed_at?: string;
  last_updated_at: string;
  access_count?: number;
  tags: string[];
  entity_keys?: string[];
  source_record_ids?: string[];
  scope?: {
    user_id: string;
    session_id: string;
  };
  fact_key?: string;
  fact_value?: string;
}

export interface MemoryEdge {
  from_id?: string;
  to_id?: string;
  source?: string;
  target?: string;
  semantic_sim: number;
  same_entity: boolean;
  same_project: boolean;
  derived_from: boolean;
  contradicts: boolean;
}

export interface MemoryStats {
  record_count: number;
  edge_count: number;
  by_type: Record<string, number>;
}

export interface WorkingSummaries {
  global_summary: string;
  session_summary: string;
}

export interface MemorySnapshot {
  working_summaries: WorkingSummaries;
  records: MemoryRecord[];
  edges: MemoryEdge[];
  stats: MemoryStats;
}

export interface MemoryGraph {
  working_summaries: WorkingSummaries;
  nodes: MemoryRecord[]; // Graph node response has similar fields
  edges: MemoryEdge[];
  stats: MemoryStats;
}

export function useMemory(baseUrl: string = DEFAULT_BASE_URL) {
  const [snapshot, setSnapshot] = useState<MemorySnapshot | null>(null);
  const [graph, setGraph] = useState<MemoryGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMemory = useCallback(async (includeInvalidated = false) => {
    try {
      setLoading(true);
      const [resSnapshot, resGraph] = await Promise.all([
        fetchWithAuth(`${baseUrl}/operator/memory?include_invalidated=${includeInvalidated}`),
        fetchWithAuth(`${baseUrl}/operator/memory/graph?include_invalidated=${includeInvalidated}`),
      ]);
      if (!resSnapshot.ok) {
        const failure = await readErrorMessage(resSnapshot, 'Failed to fetch memory snapshot');
        throw new Error(failure.message);
      }
      if (!resGraph.ok) {
        const failure = await readErrorMessage(resGraph, 'Failed to fetch memory graph');
        throw new Error(failure.message);
      }
      const [dataSnapshot, dataGraph] = await Promise.all([resSnapshot.json(), resGraph.json()]);
      setSnapshot(dataSnapshot);
      setGraph(dataGraph);

      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [baseUrl]);

  useEffect(() => {
    fetchMemory();
  }, [fetchMemory]);

  return { snapshot, graph, loading, error, refresh: fetchMemory };
}
