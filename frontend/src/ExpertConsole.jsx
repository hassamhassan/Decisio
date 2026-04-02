import { useState, useEffect, useCallback, useRef } from 'react'
import { getEscalationSessions, checkExpertsAvailable, getStoredUser, getToken, logout } from './api'
import EscalationChat from './EscalationChat'

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

function statusBadge(status) {
    if (status === 'waiting') return { label: '⏳ Waiting', color: '#f59e0b' }
    if (status === 'active') return { label: '🟢 Active', color: '#10b981' }
    return { label: status, color: '#6b7280' }
}

export default function ExpertConsole({ user, onLogout, onAdmin, onSuperAdmin }) {
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
            .catch(err => {
                if (isMounted.current) {
                    setError(err.message || 'Failed to load sessions')
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

        // Helper to fetch token, assuming getToken() might become async in the future
        const fetchFreshToken = async () => {
            return getToken();
        }

        const connect = async () => {
            const token = await fetchFreshToken()
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
                        showToast('🔔 New escalation received!')
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
        <div className="app">
            {/* Header */}
            <header className="header">
                <h1>⚙️ <span>Decisio</span></h1>
                <div className="header-status">
                    <span style={{ color: '#06b6d4', fontWeight: 600 }}>
                        🔧 {user?.escalation_level_name || 'Shift Manager Console'}
                    </span>
                    {waiting.length > 0 && (
                        <span className="status-chip" style={{ borderColor: '#f59e0b', color: '#f59e0b' }}>
                            ⏳ {waiting.length} waiting
                        </span>
                    )}
                    <div className="header-user-area">
                        {activeSession?.session_id && chatMinimized && (
                            <button
                                className="btn btn-outline btn-sm"
                                onClick={() => setChatMinimized(false)}
                                style={{ borderColor: '#06b6d4', color: '#06b6d4' }}
                            >
                                💬 Chat
                            </button>
                        )}
                        <span className="header-username">{user?.full_name || user?.username}</span>
                        {isAdmin && (
                            <button className="btn btn-outline btn-sm" onClick={onAdmin}>Admin</button>
                        )}
                        <button className="btn btn-outline btn-sm btn-danger-outline" onClick={onLogout}>Logout</button>
                    </div>
                </div>
            </header>

            {/* Toast notification */}
            {toast && (
                <div key={toast.key} style={{
                    position: 'fixed', top: 16, right: 16, zIndex: 1000,
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
                            Escalation Inbox
                        </h2>
                        <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>
                            When an operator's solution fails, an escalation session is opened here.
                            Click <strong>Join Chat</strong> to connect and help resolve the incident.
                        </p>
                    </div>

                    {/* Warn admin if no expert accounts exist */}
                    {isAdmin && !hasExperts && (
                        <div style={{
                            background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444',
                            borderRadius: 8, padding: '12px 16px', marginBottom: 16,
                            fontSize: 13, color: '#ef4444',
                        }}>
                            ⚠️ <strong>No shift manager accounts found.</strong>{' '}
                            Go to <strong>Admin → Users</strong> and create at least one user with an
                            {' '}escalation level role (e.g. <code>L1</code>, <code>L2</code>).
                            Without this, escalated incidents will have no one to respond.
                        </div>
                    )}

                    {loading && (
                        <div className="loading" style={{ marginTop: 32 }}>
                            <div className="loading-dots"><span></span><span></span><span></span></div>
                            Loading sessions...
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
                            No open escalation sessions. All clear.
                        </div>
                    )}

                    {/* Waiting sessions */}
                    {waiting.length > 0 && (
                        <section style={{ marginBottom: 28 }}>
                            <h3 style={{ color: '#f59e0b', fontSize: 13, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 10 }}>
                                ⏳ Waiting — Operator Needs Help
                            </h3>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                                {waiting.map(s => (
                                    <SessionCard
                                        key={s.session_id}
                                        session={s}
                                        isActive={activeSession?.session_id === s.session_id}
                                        onJoin={() => joinSession(s)}
                                        currentUserId={storedUser?.id}
                                    />
                                ))}
                            </div>
                        </section>
                    )}

                    {/* Active sessions */}
                    {active.length > 0 && (
                        <section>
                            <h3 style={{ color: '#10b981', fontSize: 13, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: 10 }}>
                                🟢 Active — In Progress
                            </h3>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                                {active.map(s => (
                                    <SessionCard
                                        key={s.session_id}
                                        session={s}
                                        isActive={activeSession?.session_id === s.session_id}
                                        onJoin={() => joinSession(s)}
                                        currentUserId={storedUser?.id}
                                    />
                                ))}
                            </div>
                        </section>
                    )}

                    <div style={{ marginTop: 20, color: 'var(--text-dim)', fontSize: 12, textAlign: 'right' }}>
                        Auto-refreshes every {POLL_INTERVAL / 1000}s
                        {' · '}
                        <button
                            onClick={loadSessions}
                            style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0 }}
                        >
                            Refresh now
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
                    onMinimize={() => setChatMinimized(prev => !prev)}
                />
            )}
        </div>
    )
}


function SessionCard({ session, isActive, onJoin, currentUserId }) {
    const badge = statusBadge(session.status)
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
                    <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{formatDate(session.created_at)}</span>
                </div>
                <div style={{ color: 'var(--text-bright)', fontSize: 13, fontWeight: 600, marginBottom: 3 }}>
                    Operator: {session.user_name}
                </div>
                {session.expert_id ? (
                    <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                        Expert: {isMe ? `You (${session.expert_name || 'you'})` : session.expert_name || `#${session.expert_id}`}
                    </div>
                ) : (
                    <div style={{ color: '#f59e0b', fontSize: 12 }}>No expert assigned yet</div>
                )}
                <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 4, fontFamily: 'monospace' }}>
                    {session.session_id.slice(0, 8)}…
                </div>
            </div>

            {/* Right: action */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                {isActive ? (
                    <span style={{ color: 'var(--accent)', fontSize: 12, fontWeight: 600 }}>
                        💬 Open
                    </span>
                ) : (
                    <button
                        className="btn"
                        onClick={onJoin}
                        style={{ fontSize: 13, padding: '7px 16px', whiteSpace: 'nowrap' }}
                        disabled={isTakenByOther}
                    >
                        {isTakenByOther ? 'View (taken)' : 'Join Chat'}
                    </button>
                )}
                {isTakenByOther && (
                    <span style={{ fontSize: 11, color: 'var(--text-dim)', textAlign: 'right' }}>
                        Claimed by {session.expert_name || `#${session.expert_id}`}
                    </span>
                )}
            </div>
        </div>
    )
}
