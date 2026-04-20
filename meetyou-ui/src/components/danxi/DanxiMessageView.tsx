import { Bell, ChevronDown, CornerDownRight } from 'lucide-react'
import type { DanxiListResponse } from '../../types'
import {
  getMessageDescription,
  getMessageRelatedFloorId,
  getMessageRelatedHoleId,
  getMessageTimestamp,
  getMessageTitle,
} from '../../utils/danxiUtils'
import styles from './DanxiMessageView.module.css'

interface DanxiMessageViewProps {
  messages: DanxiListResponse
  busy: boolean
  onLoadMore: () => void
  onOpenPost: (message: Record<string, unknown>) => void
}

export default function DanxiMessageView({ messages, busy, onLoadMore, onOpenPost }: DanxiMessageViewProps) {
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget
    if (scrollHeight - scrollTop <= clientHeight + 100 && !busy && messages.items.length > 0) {
      onLoadMore()
    }
  }

  return (
    <div className={styles.messageView}>
      <div className={styles.messageHeader}>
        <div>
          <div className={styles.kicker}>Inbox</div>
          <h2 className={styles.messageTitle}>站内消息</h2>
        </div>
        <span className={styles.messageHint}>{messages.count} 条消息</span>
      </div>
      
      <div className={styles.messageScroll} onScroll={handleScroll}>
        {!messages.items.length ? (
          <div className={styles.emptyState}>
            <Bell size={28} className={styles.emptyIcon} />
            <span className={styles.emptyText}>暂无新消息</span>
          </div>
        ) : null}
        
        {messages.items.map((item, index) => {
          const msg = item as Record<string, unknown>
          const relatedHoleId = getMessageRelatedHoleId(msg)
          const relatedFloorId = getMessageRelatedFloorId(msg)
          const canOpenRelatedPost = relatedHoleId !== null || relatedFloorId !== null
          return (
            <button
              key={`message-${index}`}
              type="button"
              className={`${styles.messageItem} ${canOpenRelatedPost ? styles.messageItemLinkable : ''}`}
              onClick={() => {
                if (canOpenRelatedPost) {
                  onOpenPost(msg)
                }
              }}
              disabled={!canOpenRelatedPost}
            >
              <div className={styles.messageMeta}>
                <span className={styles.messageSubject}>{getMessageTitle(msg)}</span>
                <span className={styles.messageTime}>{getMessageTimestamp(msg)}</span>
              </div>
              {getMessageDescription(msg) ? <div className={styles.messageDesc}>{getMessageDescription(msg)}</div> : null}
              {canOpenRelatedPost ? (
                <span className={styles.messageJumpHint}>
                  <CornerDownRight size={13} />
                  {relatedHoleId !== null ? `跳转到帖子 #${relatedHoleId}` : `根据楼层 #${relatedFloorId} 打开关联帖子`}
                </span>
              ) : null}
            </button>
          )
        })}
        {messages.items.length > 0 ? (
          <div className={styles.loadingHint}>
            {busy ? '正在加载更早消息…' : <><ChevronDown size={14} /> 向下滚动加载更多</>}
          </div>
        ) : null}
      </div>
    </div>
  )
}
