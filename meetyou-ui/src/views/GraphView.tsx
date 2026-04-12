
import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { Crosshair, RefreshCcw, ScanSearch } from 'lucide-react'
import ForceGraph2D from 'react-force-graph-2d'
import * as d3 from 'd3-force'
import type { MemoryEdge, MemoryGraph, MemoryRecord } from '../hooks/useMemory'

type GraphRelationKind = 'semantic' | 'same_entity' | 'derived_from' | 'same_project' | 'contradicts'

type GraphNodeTone = {
  bg: string
  border: string
  text: string
  shadow: string
}

type GraphTheme = {
  textStrong: string
  textSoft: string
  canvasBg: string
  canvasFog: string
  surface: string
  surfaceBorder: string
  panelChip: string
  panelChipBorder: string
  mutedSurface: string
  mutedText: string
  mutedEdge: string
  grid: string
  statTrack: string
  profile: GraphNodeTone
  task: GraphNodeTone
  episode: GraphNodeTone
  edges: Record<GraphRelationKind, string>
}


const LIGHT_THEME: GraphTheme = {
  textStrong: '#15233a',
  textSoft: 'rgba(58, 68, 84, 0.82)',
  canvasBg: 'rgba(248, 251, 255, 0.9)',
  canvasFog: 'rgba(255, 255, 255, 0.78)',
  surface: 'rgba(255, 255, 255, 0.7)',
  surfaceBorder: 'rgba(255, 255, 255, 0.48)',
  panelChip: 'rgba(255, 255, 255, 0.6)',
  panelChipBorder: 'rgba(255, 255, 255, 0.46)',
  mutedSurface: 'rgba(255, 255, 255, 0.24)',
  mutedText: 'rgba(21, 35, 58, 0.34)',
  mutedEdge: 'rgba(21, 35, 58, 0.08)',
  grid: 'rgba(15, 23, 42, 0.05)',
  statTrack: 'rgba(21, 35, 58, 0.08)',
  profile: { bg: '#edf5ff', border: '#0a84ff', text: '#0c4f8d', shadow: 'rgba(10, 132, 255, 0.22)' },
  task: { bg: '#effaf2', border: '#34c759', text: '#24733d', shadow: 'rgba(52, 199, 89, 0.2)' },
  episode: { bg: '#f3f4f7', border: '#8e8e93', text: '#4e5561', shadow: 'rgba(113, 118, 130, 0.16)' },
  edges: {
    semantic: 'rgba(21, 35, 58, 0.18)',
    same_entity: 'rgba(0, 102, 204, 0.54)',
    derived_from: 'rgba(255, 159, 10, 0.56)',
    same_project: 'rgba(107, 118, 136, 0.34)',
    contradicts: 'rgba(255, 59, 48, 0.88)',
  },
}

const DARK_THEME: GraphTheme = {
  textStrong: '#f3f6fb',
  textSoft: 'rgba(222, 229, 238, 0.78)',
  canvasBg: 'rgba(26, 29, 34, 0.9)',
  canvasFog: 'rgba(9, 12, 18, 0.56)',
  surface: 'rgba(34, 38, 45, 0.78)',
  surfaceBorder: 'rgba(255, 255, 255, 0.08)',
  panelChip: 'rgba(255, 255, 255, 0.04)',
  panelChipBorder: 'rgba(255, 255, 255, 0.08)',
  mutedSurface: 'rgba(255, 255, 255, 0.03)',
  mutedText: 'rgba(243, 246, 251, 0.3)',
  mutedEdge: 'rgba(243, 246, 251, 0.08)',
  grid: 'rgba(255, 255, 255, 0.05)',
  statTrack: 'rgba(255, 255, 255, 0.08)',
  profile: { bg: '#12304f', border: '#4ea3ff', text: '#d8ecff', shadow: 'rgba(78, 163, 255, 0.22)' },
  task: { bg: '#123726', border: '#56db7b', text: '#d7f8e2', shadow: 'rgba(86, 219, 123, 0.22)' },
  episode: { bg: '#2d3137', border: '#a0a7b3', text: '#eef1f4', shadow: 'rgba(174, 181, 191, 0.18)' },
  edges: {
    semantic: 'rgba(243, 246, 251, 0.18)',
    same_entity: 'rgba(78, 163, 255, 0.58)',
    derived_from: 'rgba(255, 184, 76, 0.6)',
    same_project: 'rgba(174, 181, 191, 0.32)',
    contradicts: 'rgba(255, 105, 97, 0.9)',
  },
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function truncateText(text: string | undefined, maxLength: number): string {
  if (!text) return ''
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text
}

function readDarkMode(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function getTheme(isDarkMode: boolean): GraphTheme {
  return isDarkMode ? DARK_THEME : LIGHT_THEME
}

function getTypeLabel(type: string): string {
  if (type === 'profile') return '用户画像'
  if (type === 'fact') return '长期事实'
  if (type === 'episode') return '事件'
  return '记录'
}

function getToneByType(type: string, theme: GraphTheme): GraphNodeTone {
  if (type === 'profile') return theme.profile
  if (type === 'fact') return theme.task
  return theme.episode
}

function detectRelationKind(edge: MemoryEdge): GraphRelationKind {
  if (edge.contradicts) return 'contradicts'
  if (edge.same_entity) return 'same_entity'
  if (edge.derived_from) return 'derived_from'
  if (edge.same_project) return 'same_project'
  return 'semantic'
}

function getRelationLabel(kind: GraphRelationKind): string {
  if (kind === 'same_entity') return '同一实体'
  if (kind === 'derived_from') return '来源推导'
  if (kind === 'same_project') return '同项目'
  if (kind === 'contradicts') return '冲突'
  return '语义接近'
}

function buildNodeDisplay(record: MemoryRecord, theme: GraphTheme): any {
  const labelSource =
    record.type === 'profile'
      ? record.fact_key || record.fact_value || record.content
      : record.type === 'fact'
        ? record.fact_key || record.content
        : record.content

  const previewSource =
    record.type === 'profile'
      ? record.fact_value || record.content
      : record.type === 'fact'
        ? record.content
        : record.content

  return {
    id: record.id,
    label: truncateText(labelSource, 18),
    preview: truncateText(previewSource, 56),
    type: record.type,
    typeLabel: getTypeLabel(record.type),
    importance: clamp(record.importance || 0, 0, 1),
    confidence: clamp(record.confidence || 0, 0, 1),
    strength: clamp(record.strength || 0, 0, 1),
    tone: getToneByType(record.type, theme),
    record,
    val: 1.1 + clamp(record.importance || 0, 0, 1) * 2
  }
}

function buildEdgeDisplay(edge: MemoryEdge, index: number, theme: GraphTheme): any {
  const from = edge.source ?? edge.from_id
  const to = edge.target ?? edge.to_id

  if (!from || !to) return null

  const kind = detectRelationKind(edge)
  const semanticSim = clamp(edge.semantic_sim || 0, 0, 1)

  return {
    id: `${String(from)}::${String(to)}::${index}`,
    source: String(from),
    target: String(to),
    kind,
    label: getRelationLabel(kind),
    color: theme.edges[kind],
    width: kind === 'contradicts' ? 2.0 : kind === 'same_entity' ? 1.5 : 1.0,
    dashes: kind === 'contradicts' ? [10, 7] : kind === 'derived_from' ? [6, 7] : null,
    semanticSim,
  }
}

export default function GraphView({ graph }: { graph: MemoryGraph | null }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<any>(null)
  
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const [isDarkMode, setIsDarkMode] = useState(readDarkMode)
  const [hoverNode, setHoverNode] = useState<any | null>(null)
  const [selectedNode, setSelectedNode] = useState<any | null>(null)
  
  // Physics controls
  const [chargeStrength, setChargeStrength] = useState(-160)
  const [linkDistance, setLinkDistance] = useState(60)
  const [centerGravity, setCenterGravity] = useState(0.04)

  const theme = useMemo(() => getTheme(isDarkMode), [isDarkMode])

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setDimensions({ width: e.contentRect.width, height: e.contentRect.height })
      }
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = (e: MediaQueryListEvent) => setIsDarkMode(e.matches)
    setIsDarkMode(mediaQuery.matches)
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [])

  useEffect(() => {
    if (fgRef.current) {
      fgRef.current.d3Force('charge').strength(chargeStrength)
      fgRef.current.d3Force('link').distance(linkDistance)
      fgRef.current.d3Force('x', d3.forceX().strength(centerGravity))
      fgRef.current.d3Force('y', d3.forceY().strength(centerGravity))
      fgRef.current.d3ReheatSimulation()
    }
  }, [chargeStrength, linkDistance, centerGravity])

  const graphData = useMemo(() => {
    if (!graph) return { nodes: [], links: [] }
    const nodes = graph.nodes.map(record => buildNodeDisplay(record, theme))
    const links = graph.edges.map((edge, index) => buildEdgeDisplay(edge, index, theme)).filter(Boolean)
    
    nodes.forEach((node: any) => {
      node.neighbors = new Set()
      node.links = new Set()
    })
    
    // Cross-link nodes for fast lookup
    const nodeById = new Map(nodes.map((n: any) => [n.id, n]))
    links.forEach((link: any) => {
      const a = nodeById.get(link.source)
      const b = nodeById.get(link.target)
      if (a && b) {
        a.neighbors.add(b)
        b.neighbors.add(a)
        a.links.add(link)
        b.links.add(link)
      }
    })
    
    return { nodes, links }
  }, [graph, theme])

  const paintNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const isHovered = node === hoverNode
    const isSelected = node === selectedNode
    const isNeighbor = hoverNode && hoverNode.neighbors.has(node)
    const isSelectedNeighbor = selectedNode && selectedNode.neighbors.has(node)
    
    // Dim logic: if something is hovered, dim rest. If something is selected, dim rest.
    let isDimmed = false
    if (hoverNode && !isHovered && !isNeighbor) isDimmed = true
    if (selectedNode && !isSelected && !isSelectedNeighbor) isDimmed = true

    const radius = 6 + (node.importance || 0) * 4
    
    ctx.globalAlpha = isDimmed ? 0.2 : 1
    
    // Glow effect
    if (isSelected || isHovered) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 4, 0, 2 * Math.PI, false)
      ctx.fillStyle = node.tone.shadow
      ctx.fill()
    }

    // Node body
    ctx.beginPath()
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false)
    ctx.fillStyle = isDimmed ? theme.mutedSurface : node.tone.bg
    ctx.fill()
    
    // Border
    ctx.lineWidth = isSelected ? 2 : 1.5
    ctx.strokeStyle = isSelected || isHovered ? node.tone.border : isDimmed ? theme.mutedEdge : node.tone.border
    ctx.stroke()

    // Label
    const importance = node.importance || 0
    if (!isDimmed && (isSelected || isHovered || globalScale >= 1.2 || importance > 0.6)) {
      const isFocus = isHovered || isSelected
      const fontSize = (isFocus ? 13 : 11) / globalScale
      ctx.font = `${Math.round(fontSize)}px Inter, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      
      const label = node.label
      const textWidth = ctx.measureText(label).width
      const bgWidth = textWidth + fontSize * 1.5
      const bgHeight = fontSize + fontSize * 0.6
      const labelY = node.y + radius + bgHeight / 2 + 4 / globalScale
      
      if (isFocus || importance > 0.8) {
        ctx.fillStyle = isDarkMode ? 'rgba(20, 25, 30, 0.82)' : 'rgba(255, 255, 255, 0.82)'
        if (ctx.roundRect) {
            ctx.beginPath()
            ctx.roundRect(node.x - bgWidth / 2, labelY - bgHeight / 2, bgWidth, bgHeight, fontSize * 0.25)
            ctx.fill()
        } else {
            ctx.fillRect(node.x - bgWidth / 2, labelY - bgHeight / 2, bgWidth, bgHeight)
        }
      }
      
      ctx.fillStyle = isFocus ? node.tone.text : theme.textStrong
      ctx.fillText(label, node.x, labelY)
    }
    
    ctx.globalAlpha = 1
  }, [theme, hoverNode, selectedNode, isDarkMode])

  const paintLink = useCallback((link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const start = link.source
    const end = link.target
    
    let isDimmed = false
    if (hoverNode && hoverNode !== start && hoverNode !== end) isDimmed = true
    if (selectedNode && selectedNode !== start && selectedNode !== end) isDimmed = true

    ctx.globalAlpha = isDimmed ? 0.1 : 0.8
    ctx.beginPath()
    ctx.moveTo(start.x, start.y)
    ctx.lineTo(end.x, end.y)
    
    if (link.dashes) {
      ctx.setLineDash(link.dashes)
    } else {
      ctx.setLineDash([])
    }
    
    ctx.strokeStyle = isDimmed ? theme.mutedEdge : link.color
    ctx.lineWidth = link.width / Math.max(1, globalScale / 2)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.globalAlpha = 1
  }, [theme, hoverNode, selectedNode])

  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node)
    
    if (fgRef.current) {
      // Zoom in on center
      fgRef.current.centerAt(node.x, node.y, 600)
      fgRef.current.zoom(2.5, 600)
    }
  }, [])

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null)
  }, [])

  const handleRelayout = () => {
    fgRef.current?.d3ReheatSimulation()
  }

  const handleFitView = () => {
    fgRef.current?.zoomToFit(600, 40)
  }

  if (!graph || graphData.nodes.length === 0) {
    return <div className="card graph-loading">暂无图谱数据…</div>
  }

  return (
    <div className="graph-shell" style={{
        '--graph-canvas-bg': theme.canvasBg,
        '--graph-canvas-fog': theme.canvasFog,
        '--graph-surface': theme.surface,
        '--graph-surface-border': theme.surfaceBorder,
        '--graph-chip-bg': theme.panelChip,
        '--graph-chip-border': theme.panelChipBorder,
        '--graph-text-strong': theme.textStrong,
        '--graph-text-soft': theme.textSoft,
        '--graph-grid': theme.grid,
        '--graph-track': theme.statTrack,
    } as any}>
      <div className="graph-main">
        <div className="card graph-toolbar">
          <div className="graph-toolbar-copy">
            <div className="graph-toolbar-kicker">Memory Force Graph</div>
            <div className="graph-toolbar-head">
              <h3 className="graph-toolbar-title">动态引力图谱</h3>
              <span className="graph-toolbar-badge">{graph.nodes.length} 节点</span>
              <span className="graph-toolbar-badge subtle">{graph.edges.length} 连接</span>
            </div>
            <div className="graph-toolbar-subtitle">利用 Canvas 与 d3-force 底层的高性能引力引擎渲染，支持 60FPS 流畅缩放与物理碰撞。</div>
          </div>
          <div className="graph-toolbar-side">
            <div className="graph-toolbar-actions">
              <button className="graph-toolbar-btn" onClick={handleRelayout}>
                <RefreshCcw size={14} />
                <span>重新激活引力</span>
              </button>
              <button className="graph-toolbar-btn" onClick={handleFitView}>
                <ScanSearch size={14} />
                <span>全局缩放</span>
              </button>
              <button className="graph-toolbar-btn" onClick={() => setSelectedNode(null)}>
                <Crosshair size={14} />
                <span>清除选定</span>
              </button>
            </div>
          </div>
        </div>

        <div className="card graph-canvas-card">
          <div className="graph-canvas-shell" ref={containerRef}>
            {dimensions.width > 0 && dimensions.height > 0 && (
              <div style={{ position: 'absolute', inset: 0, zIndex: 1 }}>
                <ForceGraph2D
                  ref={fgRef}
                  width={dimensions.width}
                  height={dimensions.height}
                  graphData={graphData}
                  nodeCanvasObject={paintNode}
                  linkCanvasObject={paintLink}
                  nodeLabel="preview"
                  onNodeHover={setHoverNode}
                  onNodeClick={handleNodeClick}
                  onBackgroundClick={handleBackgroundClick}
                  cooldownTicks={120}
                  d3AlphaDecay={0.06}
                  d3VelocityDecay={0.3}
                />
              </div>
            )}
            
            <div className="graph-physics-controls" style={{
              position: 'absolute',
              left: 14,
              top: 14,
              background: 'color-mix(in srgb, var(--graph-surface) 82%, transparent)',
              backdropFilter: 'blur(16px)',
              WebkitBackdropFilter: 'blur(16px)',
              padding: '12px 14px',
              borderRadius: 'var(--radius-md)',
              zIndex: 10,
              border: '1px solid var(--graph-surface-border)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
              width: 180,
              boxShadow: 'var(--shadow-md)'
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: theme.textStrong }}>物理引擎参数</div>
              <label style={{ fontSize: 11, color: theme.textSoft, display: 'flex', flexDirection: 'column', gap: 6 }}>
                斥力强度 ({Math.abs(chargeStrength)})
                <input type="range" min="-500" max="-10" step="10" value={chargeStrength} onChange={e => setChargeStrength(Number(e.target.value))} />
              </label>
              <label style={{ fontSize: 11, color: theme.textSoft, display: 'flex', flexDirection: 'column', gap: 6 }}>
                线条张力 ({linkDistance})
                <input type="range" min="10" max="250" step="5" value={linkDistance} onChange={e => setLinkDistance(Number(e.target.value))} />
              </label>
              <label style={{ fontSize: 11, color: theme.textSoft, display: 'flex', flexDirection: 'column', gap: 6 }}>
                向心全局引力 ({Math.round(centerGravity * 100)}%)
                <input type="range" min="0" max="0.3" step="0.01" value={centerGravity} onChange={e => setCenterGravity(Number(e.target.value))} />
              </label>
            </div>
            
            <div className="graph-canvas-legend">
              <div className="graph-legend">
                <div className="graph-legend-chip"><div className="graph-legend-dot" style={{background: theme.profile.bg, border: `1px solid ${theme.profile.border}`}}/>画像</div>
                <div className="graph-legend-chip"><div className="graph-legend-dot" style={{background: theme.task.bg, border: `1px solid ${theme.task.border}`}}/>长期事实</div>
                <div className="graph-legend-chip"><div className="graph-legend-dot" style={{background: theme.episode.bg, border: `1px solid ${theme.episode.border}`}}/>事件</div>
              </div>
            </div>
            
            {/* Inspector Overlay */}
            {selectedNode && (
              <div className="graph-inspector-overlay">
                <h4>{selectedNode.typeLabel}</h4>
                <p>{selectedNode.preview}</p>
                <div style={{ fontSize: 11, color: theme.textSoft, marginTop: 4 }}>
                  置信度: {Math.round(selectedNode.confidence * 100)}% | 热度: {Math.round(selectedNode.importance * 100)}%
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
