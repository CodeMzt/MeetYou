import { useEffect, useRef } from 'react'
import { Search } from 'lucide-react'
import type { DanxiListResponse, DanxiSearchResponse } from '../../types'
import { formatTime, getPostId, getPostSummary } from '../../utils/danxiUtils'
import styles from './DanxiPostList.module.css'

interface DanxiPostListProps {
  searchQuery: string
  setSearchQuery: (val: string) => void
  searchResult: DanxiSearchResponse | null
  posts: DanxiListResponse
  visiblePosts: Record<string, unknown>[]
  selectedHoleId: number | null
  busy: boolean
  onSearch: () => void
  onClearSearch: () => void
  onSelectPost: (id: number) => void
  onLoadMore: () => void
}

export default function DanxiPostList({
  searchQuery,
  setSearchQuery,
  searchResult,
  posts,
  visiblePosts,
  selectedHoleId,
  busy,
  onSearch,
  onClearSearch,
  onSelectPost,
  onLoadMore,
}: DanxiPostListProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const loadMoreRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (searchResult || busy || visiblePosts.length === 0) {
      return
    }
    if (typeof IntersectionObserver === 'undefined') {
      return
    }
    const root = scrollRef.current
    const target = loadMoreRef.current
    if (!root || !target) {
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          onLoadMore()
        }
      },
      {
        root,
        rootMargin: '180px 0px',
        threshold: 0.1,
      },
    )
    observer.observe(target)
    return () => observer.disconnect()
  }, [busy, onLoadMore, searchResult, visiblePosts.length])

  return (
    <div className={styles.listPanel}>
      <div className={styles.listHeader}>
        <div className={styles.titleRow}>
          <div>
            <div className={styles.kicker}>旦夕帖子流</div>
            <div className={styles.title}>帖子流</div>
          </div>
          <div className={styles.listHint}>
            {searchResult ? `搜索命中 ${searchResult.floor_hits} 楼` : `按时间排序 · ${posts.count} 条`}
          </div>
        </div>

        <div className={styles.searchContainer}>
          <div className={styles.searchBox}>
            <Search size={14} className={styles.searchIcon} />
            <input
              className={styles.searchInput}
              placeholder="搜索旦夕帖子..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  onSearch()
                }
              }}
            />
            {searchQuery ? (
              <button
                className={styles.clearSearchBtn}
                onClick={onClearSearch}
              >
                ×
              </button>
            ) : null}
          </div>
          <button className={styles.searchBtn} disabled={busy} onClick={onSearch}>
            搜索
          </button>
        </div>
      </div>

      <div className={styles.listScroll} ref={scrollRef}>
        {!visiblePosts.length ? <div className={styles.emptyText}>暂无帖子</div> : null}
        {visiblePosts.map((item, index) => {
          const post = item as Record<string, unknown>
          const holeId = getPostId(post)
          const isSelected = selectedHoleId === holeId

          return (
            <div
              key={`${holeId || 'post'}-${index}`}
              className={`${styles.postCard} ${isSelected ? styles.postCardActive : ''}`}
              onClick={() => holeId && onSelectPost(holeId)}
            >
              <div className={styles.postMeta}>
                <span className={styles.postTime}>{formatTime(post.time_updated || post.time_created) || `#${holeId || index + 1}`}</span>
                <span className={styles.postReplyCount}>
                  #{holeId || index + 1}
                  {typeof post.reply === 'number' ? ` · ${post.reply} 回复` : ''}
                </span>
              </div>
              <div className={styles.postSummaryBlock}>
                <div className={styles.postText}>{getPostSummary(post)}</div>
              </div>
            </div>
          )
        })}

        {!searchResult && visiblePosts.length > 0 && (
          <div className={styles.loadingIndicator} ref={loadMoreRef}>
            {busy ? '加载中...' : '向下滚动加载更多'}
          </div>
        )}
      </div>
    </div>
  )
}
