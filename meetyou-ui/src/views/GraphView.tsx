import type { CSSProperties } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Crosshair, RefreshCcw, ScanSearch, X } from 'lucide-react'
import { DataSet } from 'vis-data'
import {
  Network as VisNetwork,
  type Edge,
  type Node,
  type Options,
  type Position,
} from 'vis-network'
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

type GraphNodeDisplay = {
  id: string
  label: string
  preview: string
  type: string
  typeLabel: string
  importance: number
  confidence: number
  strength: number
  tone: GraphNodeTone
  record: MemoryRecord
}

type GraphEdgeDisplay = {
  id: string
  from: string
  to: string
  kind: GraphRelationKind
  label: string
  color: string
  width: number
  dashes: boolean | number[]
  roundness: number
  length: number
  semanticSim: number
}

type GraphModel = {
  nodeList: GraphNodeDisplay[]
  nodeMap: Map<string, GraphNodeDisplay>
  edgeList: GraphEdgeDisplay[]
  neighborMap: Map<string, Set<string>>
  edgeIdsByNode: Map<string, Set<string>>
  relationCountsByNode: Map<string, Map<GraphRelationKind, number>>
}

const RELATION_ORDER: GraphRelationKind[] = [
  'same_entity',
  'derived_from',
  'same_project',
  'semantic',
  'contradicts',
]

const CAMERA_ANIMATION = {
  duration: 560,
  easingFunction: 'easeInOutQuad' as const,
}

const PANEL_TRANSITION = {
  duration: 0.3,
  ease: [0.22, 1, 0.36, 1] as const,
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
  if (!text) {
    return ''
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text
}

function formatPercent(value: number): string {
  return `${Math.round(clamp(value, 0, 1) * 100)}%`
}

function formatDateTime(value?: string): string {
  if (!value) {
    return '暂无'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString()
}

function readDarkMode(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function getTheme(isDarkMode: boolean): GraphTheme {
  return isDarkMode ? DARK_THEME : LIGHT_THEME
}

function getTypeLabel(type: string): string {
  if (type === 'profile_fact') return '用户画像'
  if (type === 'task') return '任务'
  if (type === 'episode') return '事件'
  return '记录'
}

function getToneByType(type: string, theme: GraphTheme): GraphNodeTone {
  if (type === 'profile_fact') return theme.profile
  if (type === 'task') return theme.task
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

function buildNodeDisplay(record: MemoryRecord, theme: GraphTheme): GraphNodeDisplay {
  const labelSource =
    record.type === 'profile_fact'
      ? record.fact_key || record.fact_value || record.content
      : record.type === 'task'
        ? record.task_key || record.content
        : record.content

  const previewSource =
    record.type === 'profile_fact'
      ? record.fact_value || record.content
      : record.type === 'task'
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
  }
}

function buildEdgeDisplay(edge: MemoryEdge, index: number, theme: GraphTheme): GraphEdgeDisplay | null {
  const from = edge.source ?? edge.from_id
  const to = edge.target ?? edge.to_id

  if (!from || !to) {
    return null
  }

  const kind = detectRelationKind(edge)
  const semanticSim = clamp(edge.semantic_sim || 0, 0, 1)

  return {
    id: `${String(from)}::${String(to)}::${index}`,
    from: String(from),
    to: String(to),
    kind,
    label: getRelationLabel(kind),
    color: theme.edges[kind],
    width:
      kind === 'contradicts'
        ? 2.2 + semanticSim * 1.5
        : kind === 'same_entity'
          ? 1.6 + semanticSim * 1.1
          : 1.1 + semanticSim * 0.8,
    dashes: kind === 'contradicts' ? [10, 7] : kind === 'derived_from' ? [6, 7] : false,
    roundness: kind === 'contradicts' ? 0.28 : kind === 'derived_from' ? 0.2 : 0.14,
    length:
      kind === 'same_entity'
        ? 130
        : kind === 'same_project'
          ? 145
          : kind === 'derived_from'
            ? 170
            : kind === 'contradicts'
              ? 185
              : 160,
    semanticSim,
  }
}

function buildGraphModel(graph: MemoryGraph, theme: GraphTheme): GraphModel {
  const nodeList = graph.nodes.map((record) => buildNodeDisplay(record, theme))
  const nodeMap = new Map(nodeList.map((node) => [node.id, node]))
  const edgeList = graph.edges
    .map((edge, index) => buildEdgeDisplay(edge, index, theme))
    .filter((edge): edge is GraphEdgeDisplay => Boolean(edge && nodeMap.has(edge.from) && nodeMap.has(edge.to)))

  const neighborMap = new Map<string, Set<string>>()
  const edgeIdsByNode = new Map<string, Set<string>>()
  const relationCountsByNode = new Map<string, Map<GraphRelationKind, number>>()

  for (const node of nodeList) {
    neighborMap.set(node.id, new Set())
    edgeIdsByNode.set(node.id, new Set())
    relationCountsByNode.set(node.id, new Map())
  }

  for (const edge of edgeList) {
    neighborMap.get(edge.from)?.add(edge.to)
    neighborMap.get(edge.to)?.add(edge.from)
    edgeIdsByNode.get(edge.from)?.add(edge.id)
    edgeIdsByNode.get(edge.to)?.add(edge.id)

    const leftCounts = relationCountsByNode.get(edge.from)
    const rightCounts = relationCountsByNode.get(edge.to)
    leftCounts?.set(edge.kind, (leftCounts.get(edge.kind) ?? 0) + 1)
    rightCounts?.set(edge.kind, (rightCounts.get(edge.kind) ?? 0) + 1)
  }

  return {
    nodeList,
    nodeMap,
    edgeList,
    neighborMap,
    edgeIdsByNode,
    relationCountsByNode,
  }
}

function buildNetworkNodes(
  model: GraphModel,
  theme: GraphTheme,
  selectedNodeId: string | null,
  hoveredNodeId: string | null,
): Node[] {
  const relatedNodeIds = selectedNodeId ? model.neighborMap.get(selectedNodeId) ?? new Set<string>() : null

  return model.nodeList.map((node) => {
    const emphasis = node.importance * 0.58 + node.confidence * 0.24 + node.strength * 0.18
    const padding = Math.round(9 + emphasis * 4)
    const fontSize = 12 + emphasis * 2.2
    const isSelected = selectedNodeId === node.id
    const isHovered = hoveredNodeId === node.id
    const isNeighbor = Boolean(selectedNodeId && !isSelected && relatedNodeIds?.has(node.id))
    const isDimmed = Boolean(selectedNodeId && !isSelected && !isNeighbor)

    const background = isDimmed ? theme.mutedSurface : node.tone.bg
    const border = isSelected ? node.tone.border : isHovered ? node.tone.border : isDimmed ? theme.mutedEdge : node.tone.border
    const fontColor = isDimmed ? theme.mutedText : isSelected ? node.tone.text : theme.textStrong

    return {
      id: node.id,
      label: node.label,
      title: undefined,
      chosen: false,
      labelHighlightBold: false,
      shape: 'box',
      shapeProperties: {
        borderRadius: 14,
      },
      widthConstraint: {
        maximum: 176,
      },
      margin: {
        top: padding,
        right: padding + 2,
        bottom: padding,
        left: padding + 2,
      },
      font: {
        face: 'Inter',
        size: fontSize,
        color: fontColor,
        strokeWidth: 0,
      },
      borderWidth: isSelected ? 2.4 : isHovered ? 1.9 : 1.3,
      opacity: isDimmed ? 0.24 : isNeighbor ? 0.94 : 1,
      color: {
        background,
        border,
        highlight: { background, border },
        hover: { background, border },
      },
      shadow: {
        enabled: !isDimmed,
        color: isSelected ? node.tone.shadow : isHovered ? node.tone.shadow : 'rgba(0, 0, 0, 0.08)',
        size: isSelected ? 22 : isHovered ? 16 : 10,
        x: 0,
        y: isSelected ? 10 : 6,
      },
      mass: 1.1 + emphasis * 2,
      physics: true,
    }
  })
}

function buildNetworkEdges(model: GraphModel, theme: GraphTheme, selectedNodeId: string | null): Edge[] {
  const selectedEdgeIds = selectedNodeId ? model.edgeIdsByNode.get(selectedNodeId) ?? new Set<string>() : null

  return model.edgeList.map((edge) => {
    const isRelated = !selectedNodeId || selectedEdgeIds?.has(edge.id)
    const isConflict = edge.kind === 'contradicts'

    return {
      id: edge.id,
      from: edge.from,
      to: edge.to,
      title: undefined,
      chosen: false,
      color: isRelated ? edge.color : theme.mutedEdge,
      width: isRelated ? edge.width : 0.8,
      dashes: edge.dashes,
      length: edge.length,
      smooth: {
        enabled: true,
        type: isConflict ? 'curvedCW' : edge.kind === 'derived_from' ? 'curvedCCW' : 'continuous',
        roundness: edge.roundness,
      },
      opacity: isRelated ? 1 : 0.15,
      shadow: isConflict
        ? {
            enabled: true,
            color: 'rgba(255, 59, 48, 0.18)',
            size: 8,
            x: 0,
            y: 0,
          }
        : false,
    }
  })
}

function createNetworkOptions(theme: GraphTheme): Options {
  return {
    autoResize: true,
    layout: {
      improvedLayout: true,
      randomSeed: 18,
    },
    nodes: {
      chosen: false,
    },
    edges: {
      chosen: false,
      color: theme.edges.semantic,
      smooth: {
        enabled: true,
        type: 'continuous',
        roundness: 0.14,
      },
    },
    interaction: {
      hover: true,
      hoverConnectedEdges: false,
      tooltipDelay: 0,
      multiselect: false,
      navigationButtons: false,
      zoomView: true,
      dragView: true,
      selectable: true,
    },
    physics: {
      enabled: true,
      solver: 'forceAtlas2Based',
      stabilization: {
        enabled: true,
        iterations: 220,
        fit: false,
      },
      forceAtlas2Based: {
        gravitationalConstant: -38,
        centralGravity: 0.012,
        springLength: 180,
        springConstant: 0.045,
        damping: 0.72,
        avoidOverlap: 0.92,
      },
      minVelocity: 0.6,
      timestep: 0.35,
      adaptiveTimestep: true,
    },
  }
}

function getInspectorMetaRows(node: GraphNodeDisplay): Array<{ label: string; value: string }> {
  const { record } = node

  return [
    record.type === 'profile_fact' && record.fact_key ? { label: '画像键', value: record.fact_key } : null,
    record.type === 'profile_fact' && record.fact_value ? { label: '画像值', value: record.fact_value } : null,
    record.type === 'task' && record.task_key ? { label: '任务键', value: record.task_key } : null,
    record.type === 'task' && record.task_status ? { label: '任务状态', value: record.task_status } : null,
    record.project ? { label: '项目', value: record.project } : null,
    record.deadline ? { label: '截止时间', value: formatDateTime(record.deadline) } : null,
    record.status ? { label: '记录状态', value: record.status } : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item))
}

function getRelationTone(kind: GraphRelationKind, theme: GraphTheme): string {
  return theme.edges[kind]
}

export default function GraphView({ graph }: { graph: MemoryGraph | null }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const networkRef = useRef<VisNetwork | null>(null)
  const nodesRef = useRef<DataSet<Node, 'id'> | null>(null)
  const edgesRef = useRef<DataSet<Edge, 'id'> | null>(null)
  const hoveredNodeRef = useRef<string | null>(null)

  const [isDarkMode, setIsDarkMode] = useState(readDarkMode)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [hoverPosition, setHoverPosition] = useState<Position | null>(null)

  const theme = useMemo(() => getTheme(isDarkMode), [isDarkMode])
  const model = useMemo(() => (graph ? buildGraphModel(graph, theme) : null), [graph, theme])

  const selectedNode = selectedNodeId && model ? model.nodeMap.get(selectedNodeId) ?? null : null
  const hoveredNode = hoveredNodeId && model ? model.nodeMap.get(hoveredNodeId) ?? null : null
  const selectedEdgeCount = selectedNodeId && model ? model.edgeIdsByNode.get(selectedNodeId)?.size ?? 0 : 0
  const selectedNeighborCount = selectedNodeId && model ? model.neighborMap.get(selectedNodeId)?.size ?? 0 : 0

  const relationSummary = useMemo(() => {
    if (!selectedNodeId || !model) {
      return []
    }

    const counts = model.relationCountsByNode.get(selectedNodeId)
    if (!counts) {
      return []
    }

    return RELATION_ORDER.map((kind) => ({
      kind,
      label: getRelationLabel(kind),
      count: counts.get(kind) ?? 0,
    })).filter((item) => item.count > 0)
  }, [model, selectedNodeId])

  const graphStyle = useMemo<CSSProperties>(
    () =>
      ({
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
      }) as CSSProperties,
    [theme],
  )

  const clearSelection = () => {
    hoveredNodeRef.current = null
    setHoveredNodeId(null)
    setHoverPosition(null)
    setSelectedNodeId(null)
    networkRef.current?.releaseNode()
    networkRef.current?.unselectAll()
  }

  const updateHoverPreviewPosition = (nodeId: string | null) => {
    if (!nodeId || !networkRef.current || !containerRef.current) {
      setHoverPosition(null)
      return
    }

    try {
      const canvasPosition = networkRef.current.getPosition(nodeId)
      const domPosition = networkRef.current.canvasToDOM(canvasPosition)
      const bounds = containerRef.current.getBoundingClientRect()
      const left = clamp(domPosition.x + 18, 14, Math.max(14, bounds.width - 234))
      const top = clamp(domPosition.y - 14, 14, Math.max(14, bounds.height - 136))

      setHoverPosition({ x: left, y: top })
    } catch {
      setHoverPosition(null)
    }
  }

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined
    }

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = (event: MediaQueryListEvent) => setIsDarkMode(event.matches)

    setIsDarkMode(mediaQuery.matches)

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleChange)
      return () => mediaQuery.removeEventListener('change', handleChange)
    }

    mediaQuery.addListener(handleChange)
    return () => mediaQuery.removeListener(handleChange)
  }, [])

  useEffect(() => {
    if (!model || !containerRef.current) {
      return undefined
    }

    setSelectedNodeId(null)
    setHoveredNodeId(null)
    setHoverPosition(null)
    hoveredNodeRef.current = null

    const nodeData = new DataSet<Node, 'id'>(buildNetworkNodes(model, theme, null, null))
    const edgeData = new DataSet<Edge, 'id'>(buildNetworkEdges(model, theme, null))

    nodesRef.current = nodeData
    edgesRef.current = edgeData

    const network = new VisNetwork(
      containerRef.current,
      {
        nodes: nodeData,
        edges: edgeData,
      },
      createNetworkOptions(theme),
    )

    networkRef.current = network

    const handleSelectNode = (params?: { nodes?: Array<string | number> }) => {
      const nodeId = params?.nodes?.[0]
      if (nodeId == null) {
        return
      }
      setSelectedNodeId(String(nodeId))
    }

    const handleClearSelection = () => {
      setSelectedNodeId(null)
      network.unselectAll()
    }

    const handleClick = (params?: { nodes?: Array<string | number> }) => {
      if (params?.nodes?.length) {
        return
      }
      handleClearSelection()
    }

    const handleHoverNode = (params?: { node?: string | number }) => {
      if (params?.node == null) {
        return
      }
      const nodeId = String(params.node)
      hoveredNodeRef.current = nodeId
      setHoveredNodeId(nodeId)
      updateHoverPreviewPosition(nodeId)
    }

    const handleBlurNode = () => {
      hoveredNodeRef.current = null
      setHoveredNodeId(null)
      setHoverPosition(null)
    }

    const refreshHoverPosition = () => {
      if (hoveredNodeRef.current) {
        updateHoverPreviewPosition(hoveredNodeRef.current)
      }
    }

    const fitOnStable = () => {
      network.setOptions({
        physics: {
          enabled: false,
        },
      })
      network.fit({
        animation: CAMERA_ANIMATION,
      })
    }

    network.on('selectNode', handleSelectNode)
    network.on('click', handleClick)
    network.on('hoverNode', handleHoverNode)
    network.on('blurNode', handleBlurNode)
    network.on('dragging', refreshHoverPosition)
    network.on('zoom', refreshHoverPosition)
    network.on('animationFinished', refreshHoverPosition)
    network.once('stabilized', fitOnStable)

    return () => {
      network.off('selectNode', handleSelectNode)
      network.off('click', handleClick)
      network.off('hoverNode', handleHoverNode)
      network.off('blurNode', handleBlurNode)
      network.off('dragging', refreshHoverPosition)
      network.off('zoom', refreshHoverPosition)
      network.off('animationFinished', refreshHoverPosition)
      network.destroy()
      networkRef.current = null
      nodesRef.current = null
      edgesRef.current = null
    }
  }, [model, theme])

  useEffect(() => {
    if (!model || !nodesRef.current || !edgesRef.current) {
      return
    }

    nodesRef.current.update(buildNetworkNodes(model, theme, selectedNodeId, hoveredNodeId))
    edgesRef.current.update(buildNetworkEdges(model, theme, selectedNodeId))

    if (selectedNodeId) {
      networkRef.current?.selectNodes([selectedNodeId], false)
    } else {
      networkRef.current?.unselectAll()
    }

    if (hoveredNodeId) {
      updateHoverPreviewPosition(hoveredNodeId)
    }
  }, [hoveredNodeId, model, selectedNodeId, theme])

  const handleRelayout = () => {
    if (!networkRef.current) {
      return
    }

    const network = networkRef.current
    const finish = () => {
      network.setOptions({
        physics: {
          enabled: false,
        },
      })
      network.fit({
        animation: {
          duration: 760,
          easingFunction: 'easeInOutQuad',
        },
      })
    }

    network.setOptions({
      physics: {
        enabled: true,
      },
    })
    network.once('stabilized', finish)
    network.stabilize(220)
  }

  const handleFitView = () => {
    networkRef.current?.fit({
      animation: CAMERA_ANIMATION,
    })
  }

  const handleResetSelection = () => {
    clearSelection()
  }

  if (!graph || !model) {
    return <div className="card graph-loading">正在加载图谱视图…</div>
  }

  return (
    <div className="graph-shell" style={graphStyle}>
      <div className="graph-main">
        <div className="card graph-toolbar">
          <div className="graph-toolbar-copy">
            <div className="graph-toolbar-kicker">Memory Graph</div>
            <div className="graph-toolbar-head">
              <h3 className="graph-toolbar-title">关系图谱</h3>
              <span className="graph-toolbar-badge">{graph.stats.record_count} 个节点</span>
              <span className="graph-toolbar-badge subtle">{graph.stats.edge_count} 条连接</span>
            </div>
            <div className="graph-toolbar-subtitle">轻量标签节点配合关系语义线条，点击节点可查看内容、强度和时间信息。</div>
          </div>

          <div className="graph-toolbar-side">
            <div className="graph-toolbar-actions">
              <button className="graph-toolbar-btn" onClick={handleRelayout}>
                <RefreshCcw size={14} />
                <span>重新布局</span>
              </button>
              <button className="graph-toolbar-btn" onClick={handleFitView}>
                <ScanSearch size={14} />
                <span>适配视图</span>
              </button>
              <button className="graph-toolbar-btn" onClick={handleResetSelection}>
                <Crosshair size={14} />
                <span>重置选中</span>
              </button>
            </div>
          </div>
        </div>

        <div className="card graph-canvas-card">
          <div className="graph-canvas-shell">
            <div ref={containerRef} className="graph-canvas-surface" />

            <div className="graph-canvas-legend" aria-label="graph legend">
              <div className="graph-legend">
                {[
                  model.nodeList.find((item) => item.type === 'profile_fact'),
                  model.nodeList.find((item) => item.type === 'task'),
                  model.nodeList.find((item) => item.type === 'episode'),
                ]
                  .filter((item): item is GraphNodeDisplay => Boolean(item))
                  .map((item) => (
                    <span key={item.type} className="graph-legend-chip">
                      <span className="graph-legend-dot" style={{ background: item.tone.border }} />
                      <span>{item.typeLabel}</span>
                    </span>
                  ))}

                {RELATION_ORDER.map((kind) => (
                  <span key={kind} className="graph-legend-chip edge">
                    <span
                      className={`graph-edge-swatch ${kind === 'contradicts' || kind === 'derived_from' ? 'dashed' : ''}`}
                      style={{ borderTopColor: getRelationTone(kind, theme) }}
                    />
                    <span>{getRelationLabel(kind)}</span>
                  </span>
                ))}
              </div>
            </div>

            <AnimatePresence initial={false}>
              {hoveredNode && hoverPosition ? (
                <motion.div
                  className="graph-hover-card"
                  initial={{ opacity: 0, y: 10, scale: 0.96, left: hoverPosition.x, top: hoverPosition.y }}
                  animate={{ opacity: 1, y: 0, scale: 1, left: hoverPosition.x, top: hoverPosition.y }}
                  exit={{ opacity: 0, y: 8, scale: 0.98 }}
                  transition={{
                    opacity: { duration: 0.18, ease: 'easeOut' },
                    scale: PANEL_TRANSITION,
                    y: PANEL_TRANSITION,
                    left: { duration: 0.22, ease: 'easeOut' },
                    top: { duration: 0.22, ease: 'easeOut' },
                  }}
                >
                  <div className="graph-hover-topline">
                    <span
                      className="graph-hover-type"
                      style={{
                        background: hoveredNode.tone.bg,
                        color: hoveredNode.tone.text,
                        borderColor: hoveredNode.tone.border,
                      }}
                    >
                      {hoveredNode.typeLabel}
                    </span>
                    <span className="graph-hover-label">{hoveredNode.label}</span>
                  </div>
                  <div className="graph-hover-copy">{hoveredNode.preview}</div>
                  <div className="graph-hover-metrics">
                    <span>重要性 {formatPercent(hoveredNode.importance)}</span>
                    <span>置信度 {formatPercent(hoveredNode.confidence)}</span>
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>
          </div>
        </div>
      </div>

      <AnimatePresence initial={false}>
        {selectedNode ? (
          <motion.aside
            className="graph-inspector"
            initial={{ opacity: 0, x: 26, scale: 0.985 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 18, scale: 0.99 }}
            transition={PANEL_TRANSITION}
          >
            <div className="card graph-inspector-card scroll-surface">
              <AnimatePresence initial={false}>
                <motion.div
                  key={selectedNode.id}
                  className="graph-inspector-content"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={PANEL_TRANSITION}
                >
                  <div className="graph-inspector-header">
                    <span
                      className="graph-inspector-type"
                      style={{
                        background: selectedNode.tone.bg,
                        color: selectedNode.tone.text,
                        borderColor: selectedNode.tone.border,
                      }}
                    >
                      {selectedNode.typeLabel}
                    </span>
                    <button className="graph-inspector-close" onClick={handleResetSelection} title="关闭详情">
                      <X size={14} />
                    </button>
                  </div>

                  <div className="graph-inspector-title">{selectedNode.label}</div>
                  <div className="graph-inspector-body">{selectedNode.record.content}</div>

                  <div className="graph-metric-grid">
                    {[
                      { label: '重要性', value: selectedNode.importance, tone: selectedNode.tone.border },
                      { label: '置信度', value: selectedNode.confidence, tone: selectedNode.tone.border },
                      { label: '强度', value: selectedNode.strength, tone: selectedNode.tone.border },
                    ].map((metric) => (
                      <div key={metric.label} className="graph-metric-card">
                        <div className="graph-metric-topline">
                          <span>{metric.label}</span>
                          <strong>{formatPercent(metric.value)}</strong>
                        </div>
                        <div className="graph-metric-track">
                          <span className="graph-metric-fill" style={{ width: formatPercent(metric.value), background: metric.tone }} />
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="graph-section">
                    <div className="graph-section-title">关联概览</div>
                    <div className="graph-summary-grid">
                      <div className="graph-summary-card">
                        <strong>{selectedNeighborCount}</strong>
                        <span>关联节点</span>
                      </div>
                      <div className="graph-summary-card">
                        <strong>{selectedEdgeCount}</strong>
                        <span>关联边</span>
                      </div>
                    </div>

                    {relationSummary.length > 0 ? (
                      <div className="graph-chip-row">
                        {relationSummary.map((item) => (
                          <span key={item.kind} className="graph-data-chip">
                            <span className="graph-data-chip-dot" style={{ background: getRelationTone(item.kind, theme) }} />
                            <span>{item.label}</span>
                            <strong>{item.count}</strong>
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="graph-section-empty">当前节点没有可展示的关系摘要。</div>
                    )}
                  </div>

                  {getInspectorMetaRows(selectedNode).length > 0 ? (
                    <div className="graph-section">
                      <div className="graph-section-title">元信息</div>
                      <div className="graph-meta-list">
                        {getInspectorMetaRows(selectedNode).map((item) => (
                          <div key={item.label} className="graph-meta-row">
                            <span>{item.label}</span>
                            <strong>{item.value}</strong>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {selectedNode.record.tags.length > 0 ? (
                    <div className="graph-section">
                      <div className="graph-section-title">标签</div>
                      <div className="graph-chip-row">
                        {selectedNode.record.tags.map((tag) => (
                          <span key={tag} className="graph-tag-chip">
                            #{tag}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div className="graph-section">
                    <div className="graph-section-title">时间</div>
                    <div className="graph-meta-list">
                      <div className="graph-meta-row">
                        <span>创建时间</span>
                        <strong>{formatDateTime(selectedNode.record.created_at)}</strong>
                      </div>
                      <div className="graph-meta-row">
                        <span>最近更新</span>
                        <strong>{formatDateTime(selectedNode.record.last_updated_at)}</strong>
                      </div>
                    </div>
                  </div>
                </motion.div>
              </AnimatePresence>
            </div>
          </motion.aside>
        ) : null}
      </AnimatePresence>
    </div>
  )
}
