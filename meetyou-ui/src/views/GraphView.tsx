import { useEffect, useRef, useState } from 'react';
import { Network } from 'vis-network';
import { MemoryGraph, MemoryRecord } from '../hooks/useMemory';

export default function GraphView({ graph }: { graph: MemoryGraph | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const [selectedNode, setSelectedNode] = useState<MemoryRecord | null>(null);

  useEffect(() => {
    if (!graph || !containerRef.current) return;

    // Reset selection when graph changes
    setSelectedNode(null);

    const nodes = graph.nodes.map(n => ({
      id: n.id,
      label: n.type === 'profile_fact' ? (n.fact_key || n.content.substring(0, 15)) : 
             n.type === 'task' ? (n.task_key || n.content.substring(0, 15)) : 
             n.content.substring(0, 15),
      group: n.type,
      title: n.content,
      value: n.importance * 10,
    }));

    const edges = graph.edges.map(e => ({
      from: e.source,
      to: e.target,
      value: e.semantic_sim,
      title: `相似度: ${e.semantic_sim.toFixed(2)}`,
      color: e.contradicts ? { color: '#ff3b30' } : undefined,
      dashes: e.contradicts,
    }));

    const data = { nodes, edges };
    const options: any = {
      nodes: {
        shape: 'dot',
        scaling: { min: 10, max: 30 },
        font: { size: 12, face: 'Inter', color: 'var(--text-primary)', strokeWidth: 3, strokeColor: 'var(--bg-color)' },
      },
      edges: {
        color: { inherit: 'both', opacity: 0.4 },
        smooth: { type: 'continuous' },
      },
      groups: {
        profile_fact: { color: { background: '#0a84ff', border: '#0066cc' } },
        task: { color: { background: '#34c759', border: '#248a3d' } },
        episode: { color: { background: '#8e8e93', border: '#636366' } },
      },
      physics: {
        forceAtlas2Based: {
          gravitationalConstant: -26,
          centralGravity: 0.005,
          springLength: 230,
          springConstant: 0.18,
        },
        maxVelocity: 146,
        solver: 'forceAtlas2Based',
        timestep: 0.35,
        stabilization: { iterations: 150 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
      }
    };

    networkRef.current = new Network(containerRef.current, data, options);

    networkRef.current.on('selectNode', (params) => {
      const nodeId = params.nodes[0];
      const nodeData = graph.nodes.find(n => n.id === nodeId);
      if (nodeData) {
        setSelectedNode(nodeData);
      }
    });

    networkRef.current.on('deselectNode', () => {
      setSelectedNode(null);
    });

    return () => {
      networkRef.current?.destroy();
      networkRef.current = null;
    };
  }, [graph]);

  if (!graph) return <div>正在加载图谱...</div>;

  return (
    <div style={{ display: 'flex', height: '100%', gap: 16 }}>
      <div className="card" style={{ flex: 1, padding: 0, overflow: 'hidden', position: 'relative' }}>
        <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
      </div>
      
      {selectedNode && (
        <div className="card" style={{ width: 300, display: 'flex', flexDirection: 'column', gap: 12, overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--glass-border)', paddingBottom: 8 }}>
            <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>节点详情</h3>
            <span style={{ fontSize: 11, background: 'var(--accent-color)', color: 'white', padding: '2px 6px', borderRadius: 4, textTransform: 'uppercase' }}>
              {selectedNode.type}
            </span>
          </div>
          
          <div style={{ fontSize: 13, lineHeight: 1.5 }}>
            <div style={{ color: 'var(--text-secondary)', marginBottom: 4, fontSize: 12 }}>内容：</div>
            {selectedNode.content}
          </div>
          
          <div style={{ height: 1, background: 'var(--glass-border)', margin: '4px 0' }} />
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>ID</span>
              <span style={{ fontFamily: 'monospace' }}>{selectedNode.id.substring(0, 12)}...</span>
            </div>
            
            {selectedNode.type === 'profile_fact' && selectedNode.fact_key && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>键名</span>
                <span>{selectedNode.fact_key}</span>
              </div>
            )}
            
            {selectedNode.type === 'task' && selectedNode.task_key && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>任务键名</span>
                <span>{selectedNode.task_key}</span>
              </div>
            )}
            
            {selectedNode.type === 'task' && selectedNode.task_status && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>状态</span>
                <span>{selectedNode.task_status}</span>
              </div>
            )}
            
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>重要度</span>
              <span>{(selectedNode.importance * 100).toFixed(0)}%</span>
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>置信度</span>
              <span>{(selectedNode.confidence * 100).toFixed(0)}%</span>
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>创建时间</span>
              <span>{new Date(selectedNode.created_at).toLocaleString()}</span>
            </div>
          </div>
          
          {selectedNode.tags && selectedNode.tags.length > 0 && (
            <>
              <div style={{ height: 1, background: 'var(--glass-border)', margin: '4px 0' }} />
              <div>
                <div style={{ color: 'var(--text-secondary)', marginBottom: 8, fontSize: 12 }}>标签：</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {selectedNode.tags.map(t => (
                    <span key={t} style={{ fontSize: 11, background: 'rgba(128,128,128,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                      #{t}
                    </span>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
