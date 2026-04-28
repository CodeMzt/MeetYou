import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  BookOpenText,
} from 'lucide-react'
import {
  createDanxiReply,
  deleteDanxiReply,
  getDanxiPost,
  getDanxiPostSummary,
  getDanxiProfile,
  getDanxiSessionStatus,
  listDanxiDivisions,
  listDanxiFloors,
  listDanxiMessages,
  listDanxiPosts,
  loginDanxiSession,
  resolveDanxiMessageTarget,
  searchDanxiPosts,
  updateDanxiReply,
  updateDanxiWebvpnCookie,
} from './clientApi'
import type {
  DanxiListResponse,
  DanxiSearchResponse,
  DanxiSessionStatus,
  DanxiSummaryResponse,
  DanxiUserProfileResponse,
} from './types'
import { getMessageRelatedFloorId, getMessageRelatedHoleId } from './utils/danxiUtils'
import ConfirmModal from './components/common/ConfirmModal'
import SubWindow from './components/layout/SubWindow'
import { DEFAULT_BASE_URL, WINDOW_EVENT_CHANNEL, WINDOW_SYNC_CHANNEL } from './windowBridge'
import styles from './DanxiWindow.module.css'
import DanxiSidebar from './components/danxi/DanxiSidebar'
import DanxiPostList from './components/danxi/DanxiPostList'
import DanxiPostDetail from './components/danxi/DanxiPostDetail'
import DanxiMessageView from './components/danxi/DanxiMessageView'

type DanxiWindowPayload = {
  baseUrl: string
  preferredMode: string
  workspaceTitle: string
}

const EMPTY_PAYLOAD: DanxiWindowPayload = {
  baseUrl: DEFAULT_BASE_URL,
  preferredMode: 'general',
  workspaceTitle: '',
}

const DANXI_READ_LIMIT = 10

export function resolveDanxiAuthAction(options: {
  sessionLoggedIn: boolean
  email: string
  password: string
}): 'fresh_login' | 'update_cookie' {
  const hasManualCredentials = Boolean(options.email.trim() && options.password.trim())
  if (hasManualCredentials) {
    return 'fresh_login'
  }
  if (options.sessionLoggedIn) {
    return 'update_cookie'
  }
  return 'fresh_login'
}

function getMessageCursor(response: DanxiListResponse): string {
  const lastItem = response.items[response.items.length - 1] as Record<string, unknown> | undefined
  if (!lastItem) {
    return ''
  }
  const cursor = lastItem.time_created || lastItem.created_at || lastItem.updated_at
  return typeof cursor === 'string' || typeof cursor === 'number' ? String(cursor) : ''
}

export default function DanxiWindow() {
  const [payload, setPayload] = useState<DanxiWindowPayload>(EMPTY_PAYLOAD)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [session, setSession] = useState<DanxiSessionStatus | null>(null)
  const [profile, setProfile] = useState<DanxiUserProfileResponse | null>(null)
  const [divisions, setDivisions] = useState<DanxiListResponse>({ count: 0, items: [] })
  const [posts, setPosts] = useState<DanxiListResponse>({ count: 0, items: [] })
  const [messages, setMessages] = useState<DanxiListResponse>({ count: 0, items: [] })
  const [selectedDivisionId, setSelectedDivisionId] = useState<number | null>(null)
  const [selectedHoleId, setSelectedHoleId] = useState<number | null>(null)
  const [selectedPost, setSelectedPost] = useState<Record<string, unknown> | null>(null)
  const [floors, setFloors] = useState<DanxiListResponse>({ count: 0, items: [] })
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResult, setSearchResult] = useState<DanxiSearchResponse | null>(null)
  const [summary, setSummary] = useState<DanxiSummaryResponse | null>(null)
  const [replyDraft, setReplyDraft] = useState('')
  const [editingFloorId, setEditingFloorId] = useState<number | null>(null)
  const [deleteTargetFloorId, setDeleteTargetFloorId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [summaryBusy, setSummaryBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [messageCursor, setMessageCursor] = useState('')

  const [editingDraft, setEditingDraft] = useState('')
  const [viewMode, setViewMode] = useState<'posts' | 'messages'>('posts')

  const clearDetailState = useCallback(() => {
    setSelectedHoleId(null)
    setSelectedPost(null)
    setFloors({ count: 0, items: [] })
    setSummary(null)
    setReplyDraft('')
    setEditingFloorId(null)
    setEditingDraft('')
    setDeleteTargetFloorId(null)
  }, [])

  const setSuccess = useCallback((_message: string) => {
    // optional success handling
    setError(null)
  }, [])

  const setFailure = useCallback((message: string) => {
    setError(message)
  }, [])

  const loadReadonlyData = useCallback(async (baseUrl: string) => {
    const [nextDivisions, nextPosts, nextMessages] = await Promise.all([
      listDanxiDivisions(baseUrl),
      listDanxiPosts(baseUrl, { length: DANXI_READ_LIMIT, order: 'time_created' }),
      listDanxiMessages(baseUrl, { unread_only: false }),
    ])
    const nextProfile = await getDanxiProfile(baseUrl).catch(() => null)
    setDivisions(nextDivisions)
    setPosts(nextPosts)
    setMessages(nextMessages)
    setMessageCursor(getMessageCursor(nextMessages))
    if (nextProfile) {
      setProfile(nextProfile)
    }
  }, [])

  const reloadCurrentPostList = useCallback(async () => {
    if (searchResult && searchQuery.trim()) {
      const result = await searchDanxiPosts(payload.baseUrl, { query: searchQuery, length: DANXI_READ_LIMIT })
      setSearchResult(result)
      return
    }
    const nextPosts = await listDanxiPosts(payload.baseUrl, {
      division_id: selectedDivisionId ?? undefined,
      length: DANXI_READ_LIMIT,
      order: 'time_created',
    })
    setPosts(nextPosts)
  }, [payload.baseUrl, searchQuery, searchResult, selectedDivisionId])

  const refreshSelectedPost = useCallback(
    async (holeId: number, options: { refreshSummary?: boolean } = {}) => {
      const [post, nextFloors, nextSummary] = await Promise.all([
        getDanxiPost(payload.baseUrl, holeId),
        listDanxiFloors(payload.baseUrl, holeId, { size: 50 }),
        options.refreshSummary ? getDanxiPostSummary(payload.baseUrl, holeId, { floor_limit: 50 }) : Promise.resolve(null),
      ])
      setSelectedHoleId(holeId)
      setSelectedPost(post.hole)
      setFloors(nextFloors)
      if (options.refreshSummary) {
        setSummary(nextSummary)
      }
    },
    [payload.baseUrl],
  )

  const handleLoadMorePosts = useCallback(async () => {
    if (searchResult) return // 暂不支持搜索结果的分页
    try {
      setBusy(true)
      const lastPost = posts.items[posts.items.length - 1] as Record<string, unknown> | undefined
      const lastTime = lastPost?.time_updated || lastPost?.time_created || ''
      const nextPosts = await listDanxiPosts(payload.baseUrl, {
        division_id: selectedDivisionId ?? undefined,
        length: DANXI_READ_LIMIT,
        start_time: String(lastTime || ''),
        order: 'time_created',
      })
      setPosts((prev) => ({
        ...nextPosts,
        items: [...prev.items, ...nextPosts.items],
      }))
      setError(null)
    } catch (err) {
      setFailure(err instanceof Error ? err.message : '加载更多帖子失败')
    } finally {
      setBusy(false)
    }
  }, [payload.baseUrl, posts.items, searchResult, selectedDivisionId, setFailure])

  const handleLoadMoreMessages = useCallback(async () => {
    if (!messageCursor) {
      return
    }
    try {
      setBusy(true)
      const nextMessages = await listDanxiMessages(payload.baseUrl, {
        unread_only: false,
        start_time: messageCursor,
      })
      setMessages((prev) => ({
        ...nextMessages,
        items: [...prev.items, ...nextMessages.items],
      }))
      setMessageCursor(getMessageCursor(nextMessages))
      setError(null)
    } catch (err) {
      setFailure(err instanceof Error ? err.message : '加载更多消息失败')
    } finally {
      setBusy(false)
    }
  }, [messageCursor, payload.baseUrl, setFailure])

  const handleClearSearch = useCallback(async () => {
    try {
      setBusy(true)
      setSearchQuery('')
      setSearchResult(null)
      const nextPosts = await listDanxiPosts(payload.baseUrl, {
        division_id: selectedDivisionId ?? undefined,
        length: DANXI_READ_LIMIT,
        order: 'time_created',
      })
      setPosts(nextPosts)
      setError(null)
    } catch (err) {
      setFailure(err instanceof Error ? err.message : '重置搜索失败')
    } finally {
      setBusy(false)
    }
  }, [payload.baseUrl, selectedDivisionId, setFailure])

  const handleChangeViewMode = useCallback((mode: 'posts' | 'messages') => {
    setViewMode(mode)
    setDeleteTargetFloorId(null)
    setEditingFloorId(null)
    setEditingDraft('')
    setError(null)
  }, [])

  const refreshSession = useCallback(async () => {
    try {
      const nextSession = await getDanxiSessionStatus(payload.baseUrl)
      setSession(nextSession)
      setProfile({
        session_key: nextSession.session_key,
        logged_in: nextSession.logged_in,
        transport: nextSession.transport,
        webvpn_enabled: nextSession.webvpn_enabled,
        has_webvpn_cookie: nextSession.has_webvpn_cookie,
        webvpn_required: nextSession.webvpn_required,
        direct_connect_available: nextSession.direct_connect_available,
        profile: nextSession.user_profile,
      })
      setError(nextSession.connection_error ?? null)
      if (nextSession.logged_in) {
        await loadReadonlyData(payload.baseUrl)
      } else {
        setDivisions({ count: 0, items: [] })
        setPosts({ count: 0, items: [] })
        setMessages({ count: 0, items: [] })
        setMessageCursor('')
        clearDetailState()
      }
    } catch (sessionError) {
      setSession(null)
      setProfile(null)
      setMessageCursor('')
      clearDetailState()
      setFailure(sessionError instanceof Error ? sessionError.message : '读取旦夕会话失败')
    }
  }, [clearDetailState, loadReadonlyData, payload.baseUrl, setFailure])

  useEffect(() => {
    const handleDanxiPanelUpdated = (_event: unknown, data: DanxiWindowPayload | null) => {
      if (!data) {
        return
      }
      setPayload({ ...EMPTY_PAYLOAD, ...data })
    }
    window.ipcRenderer?.on(WINDOW_SYNC_CHANNEL.danxi.update, handleDanxiPanelUpdated)
    window.ipcRenderer?.send(WINDOW_SYNC_CHANNEL.danxi.request)
    return () => {
      window.ipcRenderer?.off(WINDOW_SYNC_CHANNEL.danxi.update, handleDanxiPanelUpdated)
    }
  }, [])

  useEffect(() => {
    void refreshSession()
  }, [refreshSession])

  useEffect(() => {
    const handleAuthUpdated = async (_event: unknown, data: { cookie_header?: string; cancelled?: boolean } | null) => {
      if (!data || data.cancelled || !data.cookie_header) {
        return
      }
      try {
        setBusy(true)
        setError(null)
        const authAction = resolveDanxiAuthAction({
          sessionLoggedIn: Boolean(session?.logged_in),
          email,
          password,
        })
        if (authAction === 'update_cookie') {
          const nextSession = await updateDanxiWebvpnCookie(payload.baseUrl, { cookie_header: data.cookie_header })
          setSession(nextSession)
          await loadReadonlyData(payload.baseUrl)
          setSuccess('WebVPN 登录态已更新。')
          return
        }
        const nextSession = await loginDanxiSession(payload.baseUrl, {
          email,
          password,
          use_webvpn: true,
          webvpn_cookie: data.cookie_header,
        })
        setSession(nextSession)
        await loadReadonlyData(payload.baseUrl)
          setSuccess('旦夕已通过 WebVPN 登录并同步数据。')
      } catch (authError) {
        setFailure(authError instanceof Error ? authError.message : '旦夕 WebVPN 登录处理失败')
      } finally {
        setBusy(false)
      }
    }

    window.ipcRenderer?.on(WINDOW_EVENT_CHANNEL.danxiAuthUpdated, handleAuthUpdated)
    return () => {
      window.ipcRenderer?.off(WINDOW_EVENT_CHANNEL.danxiAuthUpdated, handleAuthUpdated)
    }
  }, [email, loadReadonlyData, password, payload.baseUrl, session?.logged_in])

  const handleDirectLogin = useCallback(async () => {
    try {
      setBusy(true)
      setError(null)
      const nextSession = await loginDanxiSession(payload.baseUrl, {
        email,
        password,
        use_webvpn: false,
      })
      setSession(nextSession)
      await loadReadonlyData(payload.baseUrl)
      setSuccess('旦夕已直连登录并同步数据。')
    } catch (loginError) {
      setFailure(loginError instanceof Error ? loginError.message : '旦夕登录或初始化失败')
    } finally {
      setBusy(false)
    }
  }, [email, loadReadonlyData, password, payload.baseUrl, setFailure, setSuccess])

  const handleOpenWebvpnLogin = useCallback(async () => {
    setError(null)
    try {
      setBusy(true)
      await window.ipcRenderer?.invoke?.('open-danxi-auth-window')
    } catch (invokeError) {
      setFailure(invokeError instanceof Error ? invokeError.message : '打开 WebVPN 登录窗失败')
    } finally {
      setBusy(false)
    }
  }, [setFailure])

  const handleSelectDivision = useCallback(async (divisionId: number | null) => {
    try {
      setBusy(true)
      setViewMode('posts')
      setSelectedDivisionId(divisionId)
      setSearchResult(null)
      setSearchQuery('')
      setSummary(null)
      const nextPosts = await listDanxiPosts(payload.baseUrl, {
        division_id: divisionId ?? undefined,
        length: DANXI_READ_LIMIT,
        order: 'time_created',
      })
      setPosts(nextPosts)
      clearDetailState()
    } catch (loadError) {
      setFailure(loadError instanceof Error ? loadError.message : '加载旦夕分区帖子失败')
    } finally {
      setBusy(false)
    }
  }, [clearDetailState, payload.baseUrl, setFailure])

  const handleSelectPost = useCallback(async (holeId: number) => {
    try {
      setBusy(true)
      setViewMode('posts')
      setSummary(null)
      setEditingFloorId(null)
      setEditingDraft('')
      await refreshSelectedPost(holeId)
    } catch (loadError) {
      setFailure(loadError instanceof Error ? loadError.message : '加载旦夕帖子详情失败')
    } finally {
      setBusy(false)
    }
  }, [refreshSelectedPost, setFailure])

  const handleOpenMessagePost = useCallback(
    async (message: Record<string, unknown>) => {
      const directHoleId = getMessageRelatedHoleId(message)
      const relatedFloorId = getMessageRelatedFloorId(message)
      let resolvedHoleId = directHoleId
      if (resolvedHoleId === null && relatedFloorId !== null) {
        const target = await resolveDanxiMessageTarget(payload.baseUrl, relatedFloorId)
        resolvedHoleId = target.hole_id
      }
      if (resolvedHoleId === null) {
        setFailure('当前消息缺少可跳转的帖子信息。')
        return
      }
      setViewMode('posts')
      await handleSelectPost(resolvedHoleId)
    },
    [handleSelectPost, payload.baseUrl, setFailure],
  )

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      setSearchResult(null)
      return
    }
    try {
      setBusy(true)
      setViewMode('posts')
      clearDetailState()
      const result = await searchDanxiPosts(payload.baseUrl, { query: searchQuery, length: DANXI_READ_LIMIT })
      setSearchResult(result)
    } catch (searchError) {
      setFailure(searchError instanceof Error ? searchError.message : '搜索旦夕帖子失败')
    } finally {
      setBusy(false)
    }
  }, [clearDetailState, payload.baseUrl, searchQuery, setFailure])

  const handleReplySubmit = useCallback(async () => {
    if (!selectedHoleId || !replyDraft.trim()) {
      return
    }
    try {
      setActionBusy(true)
      await createDanxiReply(payload.baseUrl, selectedHoleId, { content: replyDraft })
      setReplyDraft('')
      await Promise.all([
        refreshSelectedPost(selectedHoleId, { refreshSummary: Boolean(summary) }),
        reloadCurrentPostList(),
      ])
      setSuccess('回复已发布，当前帖子和列表已刷新。')
    } catch (replyError) {
      setFailure(replyError instanceof Error ? replyError.message : '发布回复失败')
    } finally {
      setActionBusy(false)
    }
  }, [payload.baseUrl, refreshSelectedPost, reloadCurrentPostList, replyDraft, selectedHoleId, setFailure, setSuccess, summary])

  const handleUpdateFloor = useCallback(async () => {
    if (!editingFloorId || !editingDraft.trim()) {
      return
    }
    try {
      setActionBusy(true)
      await updateDanxiReply(payload.baseUrl, editingFloorId, { content: editingDraft })
      if (selectedHoleId) {
        await Promise.all([
          refreshSelectedPost(selectedHoleId, { refreshSummary: Boolean(summary) }),
          reloadCurrentPostList(),
        ])
      }
      setEditingFloorId(null)
      setEditingDraft('')
      setSuccess('回复已更新，当前帖子和列表已刷新。')
    } catch (updateError) {
      setFailure(updateError instanceof Error ? updateError.message : '编辑回复失败')
    } finally {
      setActionBusy(false)
    }
  }, [editingDraft, editingFloorId, payload.baseUrl, refreshSelectedPost, reloadCurrentPostList, selectedHoleId, setFailure, setSuccess, summary])

  const handleDeleteFloor = useCallback(async () => {
    if (!deleteTargetFloorId) {
      return
    }
    try {
      setActionBusy(true)
      await deleteDanxiReply(payload.baseUrl, deleteTargetFloorId, { confirm: true })
      if (selectedHoleId) {
        await Promise.all([
          refreshSelectedPost(selectedHoleId, { refreshSummary: Boolean(summary) }),
          reloadCurrentPostList(),
        ])
      }
      setDeleteTargetFloorId(null)
      setSuccess('回复已删除，当前帖子和列表已刷新。')
    } catch (deleteError) {
      setFailure(deleteError instanceof Error ? deleteError.message : '删除回复失败')
    } finally {
      setActionBusy(false)
    }
  }, [deleteTargetFloorId, payload.baseUrl, refreshSelectedPost, reloadCurrentPostList, selectedHoleId, setFailure, setSuccess, summary])

  const handleGenerateSummary = useCallback(async () => {
    if (!selectedHoleId) {
      return
    }
    try {
      setSummaryBusy(true)
      const nextSummary = await getDanxiPostSummary(payload.baseUrl, selectedHoleId, { floor_limit: 50 })
      setSummary(nextSummary)
      setSuccess('智能摘要已生成。')
    } catch (summaryError) {
      setFailure(summaryError instanceof Error ? summaryError.message : '生成智能摘要失败')
    } finally {
      setSummaryBusy(false)
    }
  }, [payload.baseUrl, selectedHoleId, setFailure, setSuccess])

  const visiblePosts = useMemo(() => {
    if (searchResult) {
      return searchResult.items || []
    }
    return posts.items || []
  }, [posts.items, searchResult])

  return (
    <SubWindow title="旦夕" icon={<BookOpenText size={16} />} className={styles.windowOverride}>
      <div className={styles.layout}>
        <DanxiSidebar
          email={email}
          setEmail={setEmail}
          password={password}
          setPassword={setPassword}
          session={session}
          profile={profile}
          divisions={divisions}
          messages={messages}
          selectedDivisionId={selectedDivisionId}
          viewMode={viewMode}
          setViewMode={handleChangeViewMode}
          busy={busy}
          error={error}
          onDirectLogin={() => void handleDirectLogin()}
          onWebvpnLogin={() => void handleOpenWebvpnLogin()}
          onRefreshSession={() => void refreshSession()}
          onSelectDivision={(id) => void handleSelectDivision(id)}
        />

        <div className={styles.main}>
          {viewMode === 'messages' ? (
            <DanxiMessageView
              messages={messages}
              busy={busy}
              onLoadMore={() => void handleLoadMoreMessages()}
              onOpenPost={(holeId) => void handleOpenMessagePost(holeId)}
            />
          ) : !selectedHoleId || !selectedPost ? (
            <div className={`${styles.feedShell} ${styles.feedListMode}`}>
              <DanxiPostList
                searchQuery={searchQuery}
                setSearchQuery={setSearchQuery}
                searchResult={searchResult}
                posts={posts}
                visiblePosts={visiblePosts}
                selectedHoleId={selectedHoleId}
                busy={busy}
                onSearch={() => void handleSearch()}
                onClearSearch={() => void handleClearSearch()}
                onSelectPost={(id) => void handleSelectPost(id)}
                onLoadMore={() => void handleLoadMorePosts()}
              />
            </div>
          ) : (
            <div className={`${styles.feedShell} ${styles.feedDetailMode}`}>
              <DanxiPostDetail
                selectedHoleId={selectedHoleId}
                selectedPost={selectedPost}
                floors={floors}
                summary={summary}
                profile={profile}
                replyDraft={replyDraft}
                setReplyDraft={setReplyDraft}
                editingDraft={editingDraft}
                setEditingDraft={setEditingDraft}
                editingFloorId={editingFloorId}
                setEditingFloorId={setEditingFloorId}
                actionBusy={actionBusy}
                summaryBusy={summaryBusy}
                onBack={clearDetailState}
                onPublishReply={() => void handleReplySubmit()}
                onUpdateReply={() => void handleUpdateFloor()}
                onDeleteReply={(floorId) => setDeleteTargetFloorId(floorId)}
                onSummarize={() => void handleGenerateSummary()}
              />
            </div>
          )}
        </div>
      </div>
      <ConfirmModal
        isOpen={deleteTargetFloorId !== null}
        title="删除回复"
        message="删除后会立即刷新当前帖子楼层，且该操作通常不可撤销。确认继续吗？"
        confirmText="确认删除"
        cancelText="取消"
        isDestructive
        onConfirm={() => void handleDeleteFloor()}
        onCancel={() => setDeleteTargetFloorId(null)}
      />
    </SubWindow>
  )
}
