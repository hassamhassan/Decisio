import { useState, useEffect, useCallback, useRef } from 'react'
import { getEscalationSessions, checkExpertsAvailable, getStoredUser, getToken, logout } from '../services/api'
import EscalationChat from '../components/EscalationChat'
import LanguageToggle from '../components/LanguageToggle'
import { useI18n } from '../i18n'

// Fallback polling interval in case WS connection drops or misses an event
const POLL_INTERVAL = 120_0000 // 15 seconds

function getWsBase() {
    const loc = window.location
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${loc.host}`
}

function formatTime(ts) {
    if (!ts) return '—'
    try {
        const d = new Date(ts)
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch {
        return '—'
    }
}

function formatDate(ts) {
    if (!ts) return '—'
    try {
        const d = new Date(ts)
        const today = new Date()
        if (d.toDateString() === today.toDateString()) return `Today ${formatTime(ts)}`
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + formatTime(ts)
    } catch {
        return '—'
    }
}

function statusBadge(status, t) {
    if (status === 'waiting') return { label: t('expertPage.status.waiting'), color: '#f59e0b' }
    if (status === 'active') return { label: t('expertPage.status.active'), color: '#10b981' }
    return { label: status, color: '#6b7280' }
}

export default function ExpertConsole({ user, onLogout, onAdmin, onSuperAdmin }) {
    const { lang, dir, t, toggleLang } = useI18n()
    const [sessions, setSessions] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [hasExperts, setHasExperts] = useState(true) // assume true until checked
    const [activeSession, setActiveSession] = useState(null) // { session_id, ws_url, ... }
    const [chatMinimized, setChatMinimized] = useState(false)
    const [toast, setToast] = useState(null) // { message, key }
    const wsRef = useRef(null)
    const toastTimerRef = useRef(null)
    const activeSessionRef = useRef(null)
    useEffect(() => {
        activeSessionRef.current = activeSession
    }, [activeSession])

    const storedUser = getStoredUser()
    const isAdmin = user?.user_type === 'admin' || user?.user_type === 'super_admin'
    const userLevel = (() => {
        const t = (user?.user_type || storedUser?.user_type || '').trim()
        const m = t.match(/^L(\d+)$/)
        return m ? Number(m[1]) : null
    })()

    const loadSessions = useCallback((isMounted = { current: true }) => {
        getEscalationSessions()
            .then(data => {
                if (isMounted.current) {
                    setSessions(data.sessions || [])
                    setError(null)
                }
            })
            .catch(() => {
                if (isMounted.current) {
                    setError(t('expertPage.errors.loadSessions'))
                }
            })
            .finally(() => {
                if (isMounted.current) setLoading(false)
            })
    }, [])

    // Show a toast notification
    const showToast = useCallback((message) => {
        if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
        setToast({ message, key: Date.now() })
        toastTimerRef.current = setTimeout(() => setToast(null), 5000)
    }, [])

    // Check if any expert accounts exist (admin warning)
    useEffect(() => {
        let isMounted = true;
        checkExpertsAvailable()
            .then(data => { if (isMounted) setHasExperts(data.has_experts) })
            .catch(() => { })
        return () => { isMounted = false; }
    }, [])

    // Initial load + polling
    useEffect(() => {
        const isMounted = { current: true }
        loadSessions(isMounted)
        const timer = setInterval(() => loadSessions(isMounted), POLL_INTERVAL)
        return () => {
            isMounted.current = false
            clearInterval(timer)
        }
    }, [loadSessions])

    // WebSocket notification channel — instant alerts for new escalations
    useEffect(() => {
        const companyId = storedUser?.company_id
        if (!companyId) return

        let ws = null
        let reconnectTimer = null
        let attempt = 0;
        let isCancelled = false;

        // Helper to fetch token, assuming getToken() might become async in the future
        const fetchFreshToken = async () => {
            return getToken();
        }

        const connect = async () => {
            const token = await fetchFreshToken()
            if (isCancelled) return;
            if (!token) {
                // If no token, user is logged out or token expired and couldn't refresh.
                // Attempt to reconnect after a delay, but don't proceed with WS connection.
                reconnectTimer = setTimeout(connect, 5000)
                return
            }

            const url = `${getWsBase()}/ws/notifications/${companyId}?token=${encodeURIComponent(token)}`
            ws = new WebSocket(url)
            wsRef.current = ws

            ws.onopen = () => {
                attempt = 0; // Reset attempts on successful connection
            }

            ws.onmessage = (evt) => {
                try {
                    const data = JSON.parse(evt.data)
                    if (data.type === 'new_escalation') {
                        const msgLevel = data.required_level != null ? Number(data.required_level) : null
                        if (!isAdmin) {
                            if (msgLevel != null) {
                                // If message has a level, you must either match it, or if you're a legacy expert (userLevel == null), you ignore it
                                if (userLevel == null || msgLevel !== userLevel) {
                                    return
                                }
                            }
                        }
                        loadSessions()
                        showToast(t('expertPage.toast.newEscalation'))
                    }
                    if (data.type === 'session_closed') {
                        loadSessions()
                    }
                    if (data.type === 'session_claimed') {
                        const msgLevel = data.required_level != null ? Number(data.required_level) : null
                        if (!isAdmin) {
                            if (msgLevel != null) {
                                if (userLevel == null || msgLevel !== userLevel) {
                                    return
                                }
                            }
                        }
                        // Another expert opened the chat first and claimed the session.
                        if (activeSessionRef.current?.session_id === data.session_id && data.expert_id !== storedUser?.id) {
                            setActiveSession(null)
                            setChatMinimized(false)
                        }
                        loadSessions()
                    }
                    if (data.type === 'ping') {
                        ws.send(JSON.stringify({ type: 'pong' }))
                    }
                } catch { /* ignore parse errors */ }
            }
            ws.onclose = () => {
                wsRef.current = null
                // Exponential backoff: min(30s, 2s * 2^attempt) + random jitter
                const backoffMs = Math.min(30000, 2000 * Math.pow(2, attempt)) + Math.random() * 1000
                attempt += 1
                reconnectTimer = setTimeout(connect, backoffMs)
            }
            ws.onerror = () => {
                // Will trigger onclose
            }
        }

        connect()

        return () => {
            isCancelled = true;
            if (reconnectTimer) clearTimeout(reconnectTimer)
            if (wsRef.current) {
                wsRef.current.onclose = null // prevent reconnect on cleanup
                wsRef.current.close()
                wsRef.current = null
            }
        }
    }, [storedUser?.company_id, loadSessions, showToast])

    const joinSession = (session) => {
        setActiveSession(session)
        setChatMinimized(false)
    }

    const waiting = sessions.filter(s => s.status === 'waiting')
    const active = sessions.filter(s => s.status === 'active')

    return (
        <div className="app" dir={dir}>
            {/* Header */}
            <header className="header">
                <h1>⚙️ <span>Decisio</span></h1>
                <div className="header-status">
                    <span style={{ color: '#06b6d4', fontWeight: 600 }}>
                        🔧 {user?.escalation_level_name || t('expertPage.topBar.consoleTitle')}
                    </span>
                    {waiting.length > 0 && (
                        <span className="status-chip" style={{ borderColor: '#f59e0b', color: '#f59e0b' }}>
                            ⏳ {waiting.length} {t('expertPage.topBar.waiting')}
                        </span>
                    )}
                    {isAdmin && (
                        <button className="btn btn-outline btn-sm" onClick={onAdmin}>{t('expertPage.topBar.admin')}</button>
                    )}
                    <div className="header-user-area">
                        {activeSession?.session_id && chatMinimized && (
                            <button
                                className="btn btn-outline btn-sm"
                                onClick={() => setChatMinimized(false)}
                                style={{ borderColor: '#06b6d4', color: '#06b6d4' }}
                            >
                                {t('expertPage.topBar.chat')}
                            </button>
                        )}
                        <LanguageToggle lang={lang} onToggle={toggleLang} t={t} />
                        <span className="header-username">{user?.full_name || user?.username}</span>
                        <button className="btn btn-outline btn-sm btn-danger-outline" onClick={onLogout}>{t('common.logout')}</button>
                    </div>
                </div>
            </header>

            {/* Toast notification */}
            {toast && (
                <div key={toast.key} style={{
                    position: 'fixed', top: 16, right: dir === 'rtl' ? 'auto' : 16, left: dir === 'rtl' ? 16 : 'auto', zIndex: 1000,
                    background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                    color: '#fff', padding: '12px 20px', borderRadius: 10,
                    fontSize: 14, fontWeight: 600, boxShadow: '0 4px 20px rgba(245,158,11,0.4)',
                    animation: 'fadeInDown 0.3s ease-out',
                    display: 'flex', alignItems: 'center', gap: 8,
                }}>
                    {toast.message}
                </div>
            )}

            {/* Main content */}
            <div className="chat-container" style={{ padding: '24px', overflowY: 'auto' }}>
                <div style={{ maxWidth: 720, margin: '0 auto' }}>
                    <div style={{ marginBottom: 24 }}>
                        <h2 style={{ color: 'var(--text-bright)', fontSize: 20, fontWeight: 700, marginBottom: 6 }}>
                            {t('expertPage.main.title')}
                        </h2>
                        <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>
                            {t('expertPage.main.subtitleLine1')}
                            {' '}
                            {t('expertPage.main.subtitleLine2Prefix')} <strong>{t('expertPage.main.joinChat')}</strong> {t('expertPage.main.subtitleLine2Suffix')}
                        </p>
                    </div>

                    {/* Warn admin if no expert accounts exist */}
                    {isAdmin && !hasExperts && (
                        <div style={{
                            background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444',
                            borderRadius: 8, padding: '12px 16px', marginBottom: 16,
                            fontSize: 13, color: '#ef4444',
                        }}>
                            ⚠️ <strong>{t('expertPage.main.noShiftManagersTitle')}</strong>{' '}
                            {t('expertPage.main.noShiftManagersBody1')} <strong>{t('expertPage.main.adminUsersPath')}</strong> {t('expertPage.main.noShiftManagersBody2')} <code>L1</code>, <code>L2</code>.
                            {' '}
                            {t('expertPage.main.noShiftManagersBody3')}
                        </div>
                    )}

                    {loading && (
                        <div className="loading" style={{ marginTop: 32 }}>
                            <div className="loading-dots"><span></span><span></span><span></span></div>
                            {t('expertPage.main.loadingSessions')}
                        </div>
                    )}

                    {error && (
                        <div style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}>
                            ⚠️ {error}
                        </div>
                    )}

                    {!loading && sessions.length === 0 && (
                        <div style={{
                            textAlign: 'center', padding: '48px 24px',
                            border: '1px dashed var(--border)', borderRadius: 10,
                            color: 'var(--text-dim)', fontSize: 14,
                        }}>
                            <div style={{ fontSize: 32, marginBottom: 12 }}>✅</div>
                            {t('expertPage.main.emptyState')}
                        </div>
                    )}

                    {/* Waiting sessions */}
                    {waiting.length > 0 && (
                        <section style={{ marginBottom: 28 }}>
                            <h3 style={{ color: '#f59e0b', fontSize: 13, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 10 }}>
                                {t('expertPage.main.waitingSection')}
                            </h3>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                                {waiting.map(s => (
                                    <SessionCard
                                        key={s.session_id}
                                        session={s}
                                        isActive={activeSession?.session_id === s.session_id}
                                        onJoin={() => joinSession(s)}
                                        currentUserId={storedUser?.id}
                                        t={t}
                                        dir={dir}
                                    />
                                ))}
                            </div>
                        </section>
                    )}

                    {/* Active sessions */}
                    {active.length > 0 && (
                        <section>
                            <h3 style={{ color: '#10b981', fontSize: 13, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 10 }}>
                                {t('expertPage.main.activeSection')}
                            </h3>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                                {active.map(s => (
                                    <SessionCard
                                        key={s.session_id}
                                        session={s}
                                        isActive={activeSession?.session_id === s.session_id}
                                        onJoin={() => joinSession(s)}
                                        currentUserId={storedUser?.id}
                                        t={t}
                                        dir={dir}
                                    />
                                ))}
                            </div>
                        </section>
                    )}

                    <div style={{ marginTop: 20, color: 'var(--text-dim)', fontSize: 12, textAlign: dir === 'rtl' ? 'left' : 'right' }}>
                        {t('expertPage.main.autoRefresh', { seconds: POLL_INTERVAL / 1000 })}
                        {' · '}
                        <button
                            onClick={loadSessions}
                            style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0 }}
                        >
                            {t('expertPage.main.refreshNow')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Escalation Chat Panel */}
            {activeSession?.session_id && (
                <EscalationChat
                    sessionId={activeSession.session_id}
                    companyId={storedUser?.company_id}
                    userId={storedUser?.id}
                    userRole={user?.user_type}
                    minimized={chatMinimized}
                    dir={dir}
                    labels={{
                        title: t('userPage.chat.title'),
                        statusConnected: t('userPage.chat.statusConnected'),
                        statusConnecting: t('userPage.chat.statusConnecting'),
                        statusDisconnected: t('userPage.chat.statusDisconnected'),
                        statusClosed: t('userPage.chat.statusClosed'),
                        closeSessionTitle: t('userPage.chat.closeSessionTitle'),
                        endButton: t('userPage.chat.endButton'),
                        minimizeTitle: t('userPage.chat.minimizeTitle'),
                        waitingShiftManager: t('userPage.chat.waitingShiftManager'),
                        waitingShiftManagerHelp: t('userPage.chat.waitingShiftManagerHelp'),
                        adminViewOnly: t('userPage.chat.adminViewOnly'),
                        expertPrompt: t('userPage.chat.expertPrompt'),
                        expertJoinedSystem: t('userPage.chat.expertJoinedSystem'),
                        sessionClosedSystem: t('userPage.chat.sessionClosedSystem'),
                        roleExpert: t('userPage.chat.roleExpert'),
                        userWithId: (id) => t('userPage.chat.userWithId', { id }),
                        placeholderConnected: t('userPage.chat.placeholderConnected'),
                        placeholderWaiting: t('userPage.chat.placeholderWaiting'),
                        send: t('common.send'),
                        you: t('common.you'),
                    }}
                    onMinimize={() => setChatMinimized(prev => !prev)}
                />
            )}
        </div>
    )
}


function SessionCard({ session, isActive, onJoin, currentUserId, t, dir }) {
    const badge = statusBadge(session.status, t)
    const isMe = session.expert_id === currentUserId
    // Another expert has already claimed this session
    const isTakenByOther = session.expert_id !== null && session.expert_id !== undefined && !isMe

    return (
        <div style={{
            background: 'var(--surface)',
            border: `1px solid ${isActive ? 'var(--accent)' : 'var(--border)'}`,
            borderRadius: 10,
            padding: '14px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: 16,
        }}>
            {/* Left: info */}
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ color: badge.color, fontSize: 12, fontWeight: 700 }}>{badge.label}</span>
                    <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>·</span>
                    <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{formatDate(session.created_at).replace('Today ', `${t('expertPage.main.today')} `)}</span>
                </div>
                <div style={{ color: 'var(--text-bright)', fontSize: 13, fontWeight: 600, marginBottom: 3 }}>
                    {t('expertPage.card.operator')}: {session.user_name}
                </div>
                {session.expert_id ? (
                    <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                        {t('expertPage.card.expert')}: {isMe ? `${t('common.you')} (${session.expert_name || t('common.you').toLowerCase()})` : session.expert_name || `#${session.expert_id}`}
                    </div>
                ) : (
                    <div style={{ color: '#f59e0b', fontSize: 12 }}>{t('expertPage.card.noExpert')}</div>
                )}
                <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 4, fontFamily: 'monospace' }}>
                    {session.session_id.slice(0, 8)}…
                </div>
            </div>

            {/* Right: action */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: dir === 'rtl' ? 'flex-start' : 'flex-end', gap: 4 }}>
                {isActive ? (
                    <span style={{ color: 'var(--accent)', fontSize: 12, fontWeight: 600 }}>
                        {t('expertPage.card.open')}
                    </span>
                ) : (
                    <button
                        className="btn"
                        onClick={onJoin}
                        style={{ fontSize: 13, padding: '7px 16px', whiteSpace: 'nowrap' }}
                        disabled={isTakenByOther}
                    >
                        {isTakenByOther ? t('expertPage.card.viewTaken') : t('expertPage.main.joinChat')}
                    </button>
                )}
                {isTakenByOther && (
                    <span style={{ fontSize: 11, color: 'var(--text-dim)', textAlign: dir === 'rtl' ? 'left' : 'right' }}>
                        {t('expertPage.card.claimedBy')} {session.expert_name || `#${session.expert_id}`}
                    </span>
                )}
            </div>
        </div>
    )
}
