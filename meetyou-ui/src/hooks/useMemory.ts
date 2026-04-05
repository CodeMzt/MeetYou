import { useState, useEffect, useCallback } from 'react';

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

export function useMemory(baseUrl: string = 'http://127.0.0.1:8000') {
  const [snapshot, setSnapshot] = useState<MemorySnapshot | null>(null);
  const [graph, setGraph] = useState<MemoryGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMemory = useCallback(async (includeInvalidated = false) => {
    try {
      setLoading(true);
      // Fetch snapshot
      const resSnapshot = await fetch(`${baseUrl}/memory?include_invalidated=${includeInvalidated}`);
      if (!resSnapshot.ok) throw new Error('Failed to fetch memory snapshot');
      const dataSnapshot = await resSnapshot.json();
      setSnapshot(dataSnapshot);

      // Fetch graph
      const resGraph = await fetch(`${baseUrl}/memory/graph?include_invalidated=${includeInvalidated}`);
      if (!resGraph.ok) throw new Error('Failed to fetch memory graph');
      const dataGraph = await resGraph.json();
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
