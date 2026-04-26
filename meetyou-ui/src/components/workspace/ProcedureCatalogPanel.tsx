import { useCallback, useEffect, useMemo, useState } from 'react'
import { BookOpenText, Pin, PinOff, RefreshCcw, Sparkles } from 'lucide-react'
import {
  getClientProcedureDetail,
  listClientProcedures,
  pinClientThreadProcedure,
  unpinClientThreadProcedure,
} from '../../clientApi'
import type { ClientProcedure, ClientProcedureDetail, ClientThreadProcedureContext } from '../../types'
import {
  formatAssistantModeLabel,
  formatExecutionTargetLabel,
  formatResourceStatusLabel,
  formatRiskProfileLabel,
  formatRoutingPolicyLabel,
} from '../../utils/statusFormatting'
import styles from './ProcedureCatalogPanel.module.css'

interface ProcedureCatalogPanelProps {
  baseUrl: string
  threadId: string
  procedureContext: ClientThreadProcedureContext | null
  onProcedureContextChange?: (context: ClientThreadProcedureContext) => void
}

function summarizeProcedure(item: ClientProcedure | ClientProcedureDetail): string {
  return item.description || item.title || item.procedure_id
}

export default function ProcedureCatalogPanel({
  baseUrl,
  threadId,
  procedureContext,
  onProcedureContextChange,
}: ProcedureCatalogPanelProps) {
  const [procedures, setProcedures] = useState<ClientProcedure[]>([])
  const [selectedProcedureId, setSelectedProcedureId] = useState('')
  const [selectedDetail, setSelectedDetail] = useState<ClientProcedureDetail | null>(null)
  const [isLoadingList, setIsLoadingList] = useState(false)
  const [isLoadingDetail, setIsLoadingDetail] = useState(false)
  const [actionMessage, setActionMessage] = useState('')
  const [actionError, setActionError] = useState('')
  const currentPinnedProcedureId = String(procedureContext?.pinned_procedure?.procedure_id || '').trim()
  const currentEffectiveProcedureId = String(procedureContext?.effective_procedure?.procedure_id || '').trim()

  const loadProcedures = useCallback(async () => {
    if (!baseUrl) {
      return
    }
    setIsLoadingList(true)
    setActionError('')
    try {
      const items = await listClientProcedures(baseUrl)
      setProcedures(items)
      setSelectedProcedureId((current) => {
        if (current && items.some((item) => item.procedure_id === current)) {
          return current
        }
        return currentPinnedProcedureId || currentEffectiveProcedureId || items[0]?.procedure_id || ''
      })
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '加载规程目录失败')
    } finally {
      setIsLoadingList(false)
    }
  }, [baseUrl, currentEffectiveProcedureId, currentPinnedProcedureId])

  useEffect(() => {
    void loadProcedures()
  }, [loadProcedures])

  useEffect(() => {
    if (!selectedProcedureId || !baseUrl) {
      setSelectedDetail(null)
      return
    }
    let cancelled = false
    const loadDetail = async () => {
      setIsLoadingDetail(true)
      setActionError('')
      try {
        const detail = await getClientProcedureDetail(baseUrl, selectedProcedureId)
        if (!cancelled) {
          setSelectedDetail(detail)
        }
      } catch (error) {
        if (!cancelled) {
          setSelectedDetail(null)
          setActionError(error instanceof Error ? error.message : '加载规程详情失败')
        }
      } finally {
        if (!cancelled) {
          setIsLoadingDetail(false)
        }
      }
    }
    void loadDetail()
    return () => {
      cancelled = true
    }
  }, [baseUrl, selectedProcedureId])

  const selectedProcedureState = useMemo(() => {
    if (!selectedDetail) {
      return {
        isPinned: false,
        isEffective: false,
      }
    }
    return {
      isPinned: selectedDetail.procedure_id === currentPinnedProcedureId,
      isEffective: selectedDetail.procedure_id === currentEffectiveProcedureId,
    }
  }, [currentEffectiveProcedureId, currentPinnedProcedureId, selectedDetail])

  const applyPin = useCallback(async () => {
    if (!selectedDetail || !threadId) {
      return
    }
    setActionError('')
    setActionMessage('')
    try {
      const nextContext = await pinClientThreadProcedure(baseUrl, threadId, selectedDetail.procedure_id)
      onProcedureContextChange?.(nextContext)
      setActionMessage(`已将“${selectedDetail.title || selectedDetail.procedure_id}”固定到当前线程。`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '固定线程规程失败')
    }
  }, [baseUrl, onProcedureContextChange, selectedDetail, threadId])

  const applyUnpin = useCallback(async () => {
    if (!threadId) {
      return
    }
    setActionError('')
    setActionMessage('')
    try {
      const nextContext = await unpinClientThreadProcedure(baseUrl, threadId)
      onProcedureContextChange?.(nextContext)
      setActionMessage('已取消当前线程的固定规程。')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '取消固定线程规程失败')
    }
  }, [baseUrl, onProcedureContextChange, threadId])

  return (
    <section className={styles.shell}>
      <div className={styles.header}>
        <div>
          <div className={styles.kicker}>规程目录</div>
          <h2 className={styles.title}>规程目录与内容</h2>
          <p className={styles.subtitle}>在这里查看当前可用规程的目录、内容，以及当前线程的固定状态。</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={() => void loadProcedures()}>
          <RefreshCcw size={14} /> 刷新目录
        </button>
      </div>

      <div className={styles.catalogLayout}>
        <div className={styles.listCard}>
          <div className={styles.listHeader}>
            <span>可用规程</span>
            <span>{procedures.length}</span>
          </div>
          <div className={styles.listBody}>
            {isLoadingList ? <div className={styles.empty}>正在加载规程目录…</div> : null}
            {!isLoadingList && procedures.length === 0 ? <div className={styles.empty}>当前没有可用规程。</div> : null}
            {procedures.map((item) => {
              const selected = item.procedure_id === selectedProcedureId
              const pinned = item.procedure_id === currentPinnedProcedureId
              const effective = item.procedure_id === currentEffectiveProcedureId
              return (
                <button
                  key={item.procedure_id}
                  type="button"
                  className={`${styles.listItem} ${selected ? styles.listItemSelected : ''}`}
                  onClick={() => setSelectedProcedureId(item.procedure_id)}
                >
                  <div className={styles.listItemTitleRow}>
                    <strong>{item.title || item.procedure_id}</strong>
                    <span className={styles.listItemStatus}>{formatResourceStatusLabel(item.status)}</span>
                  </div>
                  <div className={styles.listItemSummary}>{summarizeProcedure(item)}</div>
                  <div className={styles.listItemFooter}>
                    {pinned ? <span className={styles.stateBadge}>已固定</span> : null}
                    {!pinned && effective ? <span className={styles.stateBadgeSecondary}>当前生效</span> : null}
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <div className={styles.detailCard}>
          {!selectedDetail && isLoadingDetail ? <div className={styles.empty}>正在加载规程详情…</div> : null}
          {!selectedDetail && !isLoadingDetail ? <div className={styles.empty}>从左侧选择一个规程以查看详细内容。</div> : null}
          {selectedDetail ? (
            <>
              <div className={styles.detailHeader}>
                <div>
                  <div className={styles.detailTitleRow}>
                    <BookOpenText size={16} />
                    <h3>{selectedDetail.title || selectedDetail.procedure_id}</h3>
                  </div>
                  <div className={styles.detailId}>{selectedDetail.procedure_id}</div>
                </div>
                <div className={styles.detailActionRow}>
                  {selectedProcedureState.isPinned ? (
                    <button type="button" className={styles.secondaryAction} onClick={() => void applyUnpin()} disabled={!threadId}>
                      <PinOff size={14} /> 取消固定
                    </button>
                  ) : (
                    <button type="button" className={styles.primaryAction} onClick={() => void applyPin()} disabled={!threadId}>
                      <Pin size={14} /> 固定到当前线程
                    </button>
                  )}
                </div>
              </div>

              <div className={styles.statusRow}>
                <span className={styles.statusChip}><Sparkles size={12} /> {formatRiskProfileLabel(selectedDetail.risk_profile)}</span>
                <span className={styles.statusChip}>{formatExecutionTargetLabel(selectedDetail.default_execution_target)}</span>
                <span className={styles.statusChip}>{formatRoutingPolicyLabel(selectedDetail.tool_target_routing_policy)}</span>
              </div>

              {selectedDetail.description ? <p className={styles.paragraph}>{selectedDetail.description}</p> : null}
              {selectedDetail.prompt_overlay ? (
                <div className={styles.overlayCard}>
                  <div className={styles.sectionLabel}>规程提示覆盖</div>
                  <p className={styles.overlayText}>{selectedDetail.prompt_overlay}</p>
                </div>
              ) : null}

              <div className={styles.section}>
                <div className={styles.sectionLabel}>适用模式</div>
                <div className={styles.tagRow}>
                  {selectedDetail.applicable_modes.map((item) => (
                    <span key={item} className={styles.tag}>{formatAssistantModeLabel(item)}</span>
                  ))}
                </div>
              </div>

              <div className={styles.section}>
                <div className={styles.sectionLabel}>推荐工具</div>
                <div className={styles.tagRow}>
                  {selectedDetail.recommended_tools.length > 0 ? (
                    selectedDetail.recommended_tools.map((item) => (
                      <span key={item} className={styles.tag}>{item}</span>
                    ))
                  ) : (
                    <span className={styles.muted}>未配置</span>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <div className={styles.sectionLabel}>推荐来源</div>
                <div className={styles.tagRow}>
                  {selectedDetail.recommended_source_profiles.length > 0 ? (
                    selectedDetail.recommended_source_profiles.map((item) => (
                      <span key={item} className={styles.tag}>{item}</span>
                    ))
                  ) : (
                    <span className={styles.muted}>未配置</span>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <div className={styles.sectionLabel}>自动推断关键词</div>
                <div className={styles.tagRow}>
                  {selectedDetail.infer_keywords.length > 0 ? (
                    selectedDetail.infer_keywords.map((item) => (
                      <span key={item} className={styles.tag}>{item}</span>
                    ))
                  ) : (
                    <span className={styles.muted}>未配置</span>
                  )}
                </div>
              </div>

              {selectedProcedureState.isPinned ? <div className={styles.notice}>当前线程已固定到该规程，后续对话会优先使用它。</div> : null}
              {!selectedProcedureState.isPinned && selectedProcedureState.isEffective ? (
                <div className={styles.noticeSecondary}>该规程当前正在生效，但还未固定到线程。</div>
              ) : null}
            </>
          ) : null}
        </div>
      </div>

      {actionMessage ? <div className={styles.success}>{actionMessage}</div> : null}
      {actionError ? <div className={styles.error}>{actionError}</div> : null}
    </section>
  )
}
