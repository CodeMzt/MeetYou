import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, BookOpenText, ChevronDown, MessageSquareReply, Pencil, Send, Sparkles, Trash2 } from 'lucide-react'
import type { DanxiListResponse, DanxiSummaryResponse, DanxiUserProfileResponse } from '../../types'
import { canManageFloor, formatTime, getFloorAuthor, getFloorContent, getFloorId, getPostSummary } from '../../utils/danxiUtils'
import styles from './DanxiPostDetail.module.css'

interface DanxiPostDetailProps {
  selectedHoleId: number | null
  selectedPost: Record<string, unknown> | null
  floors: DanxiListResponse
  summary: DanxiSummaryResponse | null
  profile: DanxiUserProfileResponse | null
  replyDraft: string
  setReplyDraft: (val: string) => void
  editingDraft: string
  setEditingDraft: (val: string) => void
  editingFloorId: number | null
  setEditingFloorId: (id: number | null) => void
  actionBusy: boolean
  summaryBusy: boolean
  onBack: () => void
  onPublishReply: () => void
  onUpdateReply: () => void
  onDeleteReply: (floorId: number) => void
  onSummarize: () => void
}

export default function DanxiPostDetail({
  selectedHoleId,
  selectedPost,
  floors,
  summary,
  profile,
  replyDraft,
  setReplyDraft,
  editingDraft,
  setEditingDraft,
  editingFloorId,
  setEditingFloorId,
  actionBusy,
  summaryBusy,
  onBack,
  onPublishReply,
  onUpdateReply,
  onDeleteReply,
  onSummarize,
}: DanxiPostDetailProps) {
  const [summaryExpanded, setSummaryExpanded] = useState(true)

  if (!selectedHoleId || !selectedPost) {
    return (
      <div className={styles.detailPanel}>
        <div className={styles.emptyState}>
          <BookOpenText size={48} className={styles.emptyIcon} />
          <span className={styles.emptyTitle}>Danxi 工作台</span>
          <span className={styles.emptyDesc}>请在左侧选择一个帖子以查看、回复、编辑、删除和获取 AI 摘要。</span>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.detailPanel}>
      <div className={styles.detailHeader}>
        <div className={styles.headerLeading}>
          <button className={styles.backBtn} onClick={onBack}>
            <ArrowLeft size={14} />
            返回帖子流
          </button>
          <div className={styles.detailTitleBlock}>
            <span className={styles.detailTitle}>帖子 #{selectedHoleId}</span>
            <div className={styles.pillRow}>
              {selectedPost.division_id !== undefined && selectedPost.division_id !== null && (
                <span className={styles.statusPill}>分区 {String(selectedPost.division_id)}</span>
              )}
              {selectedPost.reply !== undefined && selectedPost.reply !== null && (
                <span className={styles.statusPill}>{String(selectedPost.reply)} 回复</span>
              )}
              {selectedPost.view !== undefined && selectedPost.view !== null && (
                <span className={styles.statusPill}>{String(selectedPost.view)} 浏览</span>
              )}
            </div>
          </div>
        </div>
        <div className={styles.headerActions}>
          <button className={styles.aiBtn} onClick={onSummarize} disabled={summaryBusy || actionBusy}>
            <Sparkles size={14} />
            {summaryBusy ? '生成中...' : 'AI 摘要'}
          </button>
        </div>
      </div>

      <div className={styles.detailScroll}>
        <div className={styles.opCard}>
          <div className={styles.opMeta}>
            <div className={styles.opAuthor}>
              <div className={styles.opAvatar}>楼主</div>
              <span className={styles.opName}>{selectedPost.anonyname ? String(selectedPost.anonyname) : '匿名'}</span>
            </div>
            <span className={styles.opTime}>{formatTime(selectedPost.time_created) || '未知时间'}</span>
          </div>
          <div className={styles.threadIntro}>原帖内容</div>
          <div className={styles.markdownContent}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{getPostSummary(selectedPost)}</ReactMarkdown>
          </div>
        </div>

        {summary && (
          <div className={styles.summaryCard}>
            <button className={styles.summaryHeader} onClick={() => setSummaryExpanded((value) => !value)}>
              <div className={styles.summaryHeading}>
                <Sparkles size={16} className={styles.summaryIcon} />
                <span className={styles.summaryTitle}>AI 摘要</span>
              </div>
              <ChevronDown size={16} className={`${styles.summaryToggle} ${summaryExpanded ? styles.summaryToggleExpanded : ''}`} />
            </button>
            {summaryExpanded ? (
              <div className={styles.summaryContent}>{(summary as any).summary_text || summary.summary || '摘要生成为空。'}</div>
            ) : null}
            <div className={styles.summaryMeta}>
              生成于 {new Date().toLocaleTimeString()}
            </div>
          </div>
        )}

        <div className={styles.replyComposer}>
          <div className={styles.composerHeader}>
            <MessageSquareReply size={16} className={styles.composerIcon} />
            <span>{editingFloorId === null ? '写回复' : '编辑回复'}</span>
          </div>
          <textarea
            className={styles.textarea}
            placeholder={editingFloorId === null ? '写下你的回复…' : '修改你的回复…'}
            value={editingFloorId === null ? replyDraft : editingDraft}
            onChange={(e) => {
              if (editingFloorId === null) {
                setReplyDraft(e.target.value)
              } else {
                setEditingDraft(e.target.value)
              }
            }}
            disabled={actionBusy}
          />
          <div className={styles.composerFooter}>
            {editingFloorId !== null ? (
              <button
                className={styles.secondaryBtn}
                onClick={() => {
                  setEditingFloorId(null)
                  setEditingDraft('')
                }}
                disabled={actionBusy}
              >
                取消编辑
              </button>
            ) : null}
            <button
              className={styles.primaryBtn}
              onClick={editingFloorId === null ? onPublishReply : onUpdateReply}
              disabled={actionBusy || !(editingFloorId === null ? replyDraft.trim() : editingDraft.trim())}
            >
              <Send size={14} />
              {editingFloorId === null ? (actionBusy ? '发送中...' : '发送回复') : actionBusy ? '保存中...' : '保存修改'}
            </button>
          </div>
        </div>

        <div className={styles.floorListContainer}>
          <div className={styles.floorListHeader}>回复</div>
          <div className={styles.floorList}>
            {!floors.items.length ? <div className={styles.emptyText}>暂无回复，来抢沙发吧</div> : null}
            {floors.items.map((item, index) => {
              const floor = item as Record<string, unknown>
              const floorId = getFloorId(floor)
              const canManage = canManageFloor(floor, (profile?.profile as Record<string, unknown> | null) || null)

              return (
                <div key={`floor-${index}`} className={styles.floorItem}>
                  <div className={styles.floorMeta}>
                    <div className={styles.floorAuthorGroup}>
                      <span className={styles.floorAuthor}>{getFloorAuthor(floor)}</span>
                      {floor.is_owner ? <span className={styles.authorTag}>楼主</span> : null}
                    </div>
                    <span className={styles.floorTime}>{formatTime(floor.time_created) || ''}</span>
                  </div>
                  <div className={styles.markdownContent}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{getFloorContent(floor)}</ReactMarkdown>
                  </div>
                  {canManage ? (
                    <div className={styles.floorActions}>
                      <button
                        className={styles.actionBtn}
                        onClick={() => {
                          setEditingFloorId(floorId)
                          setEditingDraft(getFloorContent(floor))
                        }}
                        disabled={actionBusy}
                      >
                        <Pencil size={12} /> 编辑
                      </button>
                      <button
                        className={`${styles.actionBtn} ${styles.actionBtnDanger}`}
                        onClick={() => floorId !== null && onDeleteReply(floorId)}
                        disabled={actionBusy}
                      >
                        <Trash2 size={12} /> 删除
                      </button>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
