import { Bell, Compass, RefreshCw, UserRound } from 'lucide-react'
import type { DanxiListResponse, DanxiSessionStatus, DanxiUserProfileResponse } from '../../types'
import { getDivisionLabel, pickProfileEntries } from '../../utils/danxiUtils'
import styles from './DanxiSidebar.module.css'

interface DanxiSidebarProps {
  email: string
  setEmail: (val: string) => void
  password: string
  setPassword: (val: string) => void
  session: DanxiSessionStatus | null
  profile: DanxiUserProfileResponse | null
  divisions: DanxiListResponse
  messages: DanxiListResponse
  selectedDivisionId: number | null
  viewMode: 'posts' | 'messages'
  setViewMode: (mode: 'posts' | 'messages') => void
  busy: boolean
  error: string | null
  onDirectLogin: () => void
  onWebvpnLogin: () => void
  onRefreshSession: () => void
  onSelectDivision: (id: number | null) => void
}

export default function DanxiSidebar({
  email,
  setEmail,
  password,
  setPassword,
  session,
  profile,
  divisions,
  messages,
  selectedDivisionId,
  viewMode,
  setViewMode,
  busy,
  error,
  onDirectLogin,
  onWebvpnLogin,
  onRefreshSession,
  onSelectDivision,
}: DanxiSidebarProps) {
  const isLoggedIn = session?.logged_in
  const hasWebvpn = session?.has_webvpn_cookie
  const profileRecord = (profile?.profile as Record<string, unknown> | null) || null
  const profileRows = pickProfileEntries(profileRecord)

  return (
    <div className={styles.sidebar}>
      <div className={styles.sidebarHeader}>
        <div className={styles.brandBlock}>
          <div className={styles.kicker}>旦夕工作区</div>
          <div className={styles.sidebarTitleRow}>
            <div className={styles.sidebarTitle}>旦夕</div>
            <button className={styles.iconBtn} onClick={onRefreshSession} disabled={busy} title="刷新状态">
              <RefreshCw size={14} />
            </button>
          </div>
          <div className={styles.sidebarSubtitle}>极简阅读与消息工作台</div>
        </div>

        {isLoggedIn ? (
          <div className={styles.accountCard}>
            <div className={styles.profileHeader}>
              <div className={styles.avatar}>
                <UserRound size={18} />
              </div>
              <div className={styles.profileInfo}>
                <div className={styles.profileName}>
                  {(profileRecord?.nickname as string) ||
                    (profileRecord?.name as string) ||
                    (profileRecord?.username as string) ||
                    '旦夕用户'}
                </div>
                <div className={styles.statusRow}>
                  <span className={`${styles.statusDot} ${styles.online}`} />
                  已登录 · {session?.transport || '未知'}
                </div>
              </div>
            </div>
            <div className={styles.metaPills}>
              <span className={styles.metaPill}>WebVPN {hasWebvpn ? '已就绪' : '未就绪'}</span>
              {profileRows[0] ? <span className={styles.metaPill}>{profileRows[0][1]}</span> : null}
            </div>
            {profileRows.length > 1 ? (
              <div className={styles.profileRows}>
                {profileRows.slice(1, 4).map(([label, val]) => (
                  <div key={label} className={styles.profileRow}>
                    <span className={styles.profileLabel}>{label}</span>
                    <span className={styles.profileValue}>{val}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className={styles.loginCard}>
            <div className={styles.cardTitle}>登录旦夕</div>
            <input
              className={styles.input}
              placeholder="邮箱或账号"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              className={styles.input}
              placeholder="密码"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <div className={styles.buttonRow}>
              <button
                className={styles.primaryBtn}
                disabled={busy || !email.trim() || !password.trim()}
                onClick={onDirectLogin}
              >
                直连登录
              </button>
              <button className={styles.secondaryBtn} disabled={busy} onClick={onWebvpnLogin}>
                WebVPN
              </button>
            </div>
            <div className={styles.statusRow}>
              <span className={`${styles.statusDot} ${hasWebvpn ? styles.online : styles.offline}`} />
              WebVPN {hasWebvpn ? '已就绪' : '未就绪'}
            </div>
          </div>
        )}

        {error ? <div className={styles.errorText}>{error}</div> : null}
      </div>

      <div className={styles.navSection}>
        <div className={styles.sectionLabel}>主导航</div>
        <div className={styles.navList}>
          <button
            className={`${styles.navItem} ${viewMode === 'posts' ? styles.navItemActive : ''}`}
            onClick={() => setViewMode('posts')}
          >
            <Compass size={14} />
            <span>帖子流</span>
          </button>
          <button
            className={`${styles.navItem} ${viewMode === 'messages' ? styles.navItemActive : ''}`}
            onClick={() => setViewMode('messages')}
          >
            <Bell size={14} />
            <span>站内消息</span>
            {messages.items.length > 0 ? <span className={styles.badge}>{messages.items.length}</span> : null}
          </button>
        </div>
      </div>

      {viewMode === 'posts' ? (
        <div className={styles.contextSection}>
          <div className={styles.sectionLabel}>分区导航</div>
          <div className={styles.contextScroll}>
            <button
              className={`${styles.contextItem} ${selectedDivisionId === null ? styles.contextItemActive : ''}`}
              onClick={() => onSelectDivision(null)}
            >
              首页推荐
            </button>
            {divisions.items.map((item, index) => {
              const division = item as Record<string, unknown>
              const divisionId =
                typeof division.division_id === 'number'
                  ? division.division_id
                  : typeof division.id === 'number'
                    ? division.id
                    : index
              return (
                <button
                  key={divisionId}
                  className={`${styles.contextItem} ${selectedDivisionId === divisionId ? styles.contextItemActive : ''}`}
                  onClick={() => onSelectDivision(divisionId)}
                >
                  {getDivisionLabel(division)}
                </button>
              )
            })}
          </div>
        </div>
      ) : (
        <div className={styles.contextSection}>
          <div className={styles.sectionLabel}>消息说明</div>
          <div className={styles.messageHintCard}>
            <div className={styles.messageHintTitle}>消息中心</div>
            <div className={styles.messageHintText}>
              这里会集中展示互动提醒、系统通知和论坛消息，阅读空间将完全让给消息内容。
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
