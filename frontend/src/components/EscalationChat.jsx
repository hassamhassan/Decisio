import { useState, useRef, useEffect, useCallback } from 'react'
import { getToken, getEscalationMessages, getWsBaseUrl } from '../services/api'

/**
 * EscalationChat — Real-time WebSocket chat panel for escalation sessions.
 *
 * Props:
 *   sessionId  - escalation session UUID
 *   companyId  - tenant company id
 *   userId     - current user id
 *   userRole   - current user's role (user_type)
 *   onMinimize      - optional callback when user minimizes the panel
 *   minimized       - whether panel is currently minimized
 *   onSessionClosed - optional callback when the escalation session is closed
 */
export default function EscalationChat({
    sessionId,
    companyId,
    userId,
    userRole,
    onMinimize,
    minimized,
    onSessionClosed,
    embedded = false,
    labels = {},
    dir = 'ltr',
}) {
    const [messages, setMessages] = useState([])
    const [input, setInput] = useState('')
    const [status, setStatus] = useState('connecting') // connecting | connected | disconnected | closed
    const [expertPresent, setExpertPresent] = useState(false) // true once an expert has joined
    const [error, setError] = useState(null)
    const wsRef = useRef(null)
    const chatEndRef = useRef(null)
    const reconnectTimer = useRef(null)
    const reconnectAttempts = useRef(0)
    const isClosedIntentional = useRef(false)
    const MAX_RECONNECT = 5

    const isShiftManager = /^L\d+$/.test(userRole)
    const isAdmin = userRole === 'admin' || userRole === 'super_admin'
    const isExpert = isShiftManager || userRole === 'expert' || userRole === 'escalation_owner' || isAdmin
    // Admins are view-only. Only escalation_owner can end via UI.
    const canEndSession = !isShiftManager && userRole === 'escalation_owner'

    // Scroll to bottom when new messages arrive
    useEffect(() => {
        if (chatEndRef.current && !minimized) {
            chatEndRef.current.scrollIntoView({ behavior: 'smooth' })
        }
    }, [messages, minimized])

    // Load message history on mount
    useEffect(() => {
        if (!sessionId) return
        getEscalationMessages(sessionId)
            .then(data => {
                if (data?.messages) {
                    setMessages(data.messages.map(m => ({
                        id: m.id,
                        senderId: m.sender_id,
                        senderRole: m.sender_role,
                        message: m.message,
                        timestamp: m.created_at,
                    })))
                }
            })
            .catch(() => { /* history load failed, not fatal */ })
    }, [sessionId])

    // WebSocket connection
    const connectWs = useCallback(() => {
        if (!sessionId || !companyId) return

        const token = getToken()
        if (!token) {
            setStatus('disconnected')
            setError('No auth token')
            return
        }

        const wsBase = getWsBaseUrl()
        const url = `${wsBase}/ws/chat/${companyId}/${sessionId}?token=${token}`

        setStatus('connecting')
        const ws = new WebSocket(url)
        wsRef.current = ws

        ws.onopen = () => {
            setStatus('connected')
            setError(null)
            reconnectAttempts.current = 0
        }

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data)

                if (data.type === 'ping') {
                    ws.send(JSON.stringify({ type: 'pong' }))
                    return
                }
                if (data.type === 'pong') return

                if (data.type === 'expert_joined') {
                    setExpertPresent(true)
                    setMessages(prev => [...prev, {
                        id: `sys-${Date.now()}`,
                        senderId: null,
                        senderRole: 'system',
                        message: labels.expertJoinedSystem || '✅ Shift manager has joined the chat.',
                        timestamp: data.timestamp,
                    }])
                    return
                }

                if (data.type === 'session_closed') {
                    isClosedIntentional.current = true;
                    setStatus('closed')
                    setMessages(prev => [...prev, {
                        id: `sys-${Date.now()}`,
                        senderId: null,
                        senderRole: 'system',
                        message: labels.sessionClosedSystem || 'Session has been closed by the shift manager.',
                        timestamp: data.timestamp,
                    }])
                    // Notify parent so it can transition to decision brief / outcome buttons
                    if (onSessionClosed) {
                        setTimeout(() => onSessionClosed(), 1500)
                    }
                    return
                }

                if (data.error) {
                    setError(data.error)
                    return
                }

                // Regular chat message
                if (data.sender_id !== undefined) {
                    setMessages(prev => {
                        // Avoid duplicates
                        const exists = prev.some(m => m.timestamp === data.timestamp && m.senderId === data.sender_id && m.message === data.message)
                        if (exists) return prev
                        return [...prev, {
                            id: `msg-${Date.now()}-${Math.random()}`,
                            senderId: data.sender_id,
                            senderRole: data.sender_role,
                            message: data.message,
                            timestamp: data.timestamp,
                        }]
                    })
                }
            } catch {
                // Ignore unparseable messages
            }
        }

        ws.onclose = (e) => {
            wsRef.current = null
            if (isClosedIntentional.current) return;
            if (e.code === 4001 || e.code === 4003) {
                setStatus('disconnected')
                setError(e.reason || 'Access denied')
                return
            }
            if (e.code === 4004) {
                setStatus('disconnected')
                setError(e.reason || 'Access denied for this escalation session.')
                return
            }
            // Auto-reconnect unless session was explicitly closed
            setStatus(prev => prev === 'closed' ? 'closed' : 'disconnected')
            if (reconnectAttempts.current < MAX_RECONNECT) {
                reconnectAttempts.current++
                const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 15000)
                reconnectTimer.current = setTimeout(connectWs, delay)
            }
        }

        ws.onerror = () => {
            // onclose will fire after onerror, handled there
        }
    }, [sessionId, companyId])

    useEffect(() => {
        connectWs()
        return () => {
            isClosedIntentional.current = true;
            if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
            if (wsRef.current) {
                wsRef.current.onclose = null
                wsRef.current.close()
                wsRef.current = null
            }
        }
    }, [connectWs])

    const sendMessage = (e) => {
        e.preventDefault()
        const text = input.trim()
        if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

        wsRef.current.send(JSON.stringify({ type: 'message', message: text }))
        setInput('')
    }

    const closeSession = () => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            isClosedIntentional.current = true;
            wsRef.current.send(JSON.stringify({ type: 'close' }))
        }
    }

    const formatTime = (ts) => {
        if (!ts) return ''
        try {
            const d = new Date(ts)
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        } catch {
            return ''
        }
    }

    const statusDot = status === 'connected' ? 'active'
        : status === 'connecting' ? 'warning'
            : status === 'closed' ? 'danger'
                : 'danger'

    if (!embedded && minimized) {
        return (
            <div className="escalation-chat-minimized" onClick={onMinimize}>
                <span className={`status-dot ${statusDot}`}></span>
                <span>{labels.title || '💬 Escalation Chat'}</span>
                {messages.length > 0 && <span className="chat-badge">{messages.length}</span>}
            </div>
        )
    }

    return (
        <div className={`escalation-chat ${embedded ? 'escalation-chat-embedded' : ''}`} dir={dir}>
            {/* Header */}
            <div className="chat-header">
                <div className="chat-header-left">
                    <span className={`status-dot ${statusDot}`}></span>
                    <span className="chat-header-title">{labels.title || '💬 Escalation Chat'}</span>
                    <span className="chat-status-text">
                        {status === 'connected' && (labels.statusConnected || 'Connected')}
                        {status === 'connecting' && (labels.statusConnecting || 'Connecting...')}
                        {status === 'disconnected' && (labels.statusDisconnected || 'Disconnected')}
                        {status === 'closed' && (labels.statusClosed || 'Session Ended')}
                    </span>
                </div>
                <div className="chat-header-actions">
                    {canEndSession && status === 'connected' && (
                        <button className="btn btn-sm btn-danger-outline" onClick={closeSession} title={labels.closeSessionTitle || 'Close Session'}>
                            {labels.endButton || '✕ End'}
                        </button>
                    )}
                    {!embedded && (
                        <button className="btn btn-sm btn-outline" onClick={onMinimize} title={labels.minimizeTitle || 'Minimize'}>
                            ─
                        </button>
                    )}
                </div>
            </div>

            {/* Error banner */}
            {error && (
                <div className="chat-error">⚠️ {error}</div>
            )}

            {/* Messages */}
            <div className="chat-messages">
                {messages.length === 0 && status === 'connected' && !expertPresent && !isExpert && (
                    <div className="chat-empty" style={{ color: '#f59e0b' }}>
                        {(labels.waitingShiftManager || '⏳ Waiting for a shift manager to join…')}<br />
                        <span style={{ fontSize: 12, opacity: 0.75 }}>{labels.waitingShiftManagerHelp || 'You can type a message and they will see it when they connect.'}</span>
                    </div>
                )}
                {messages.length === 0 && status === 'connected' && isExpert && (
                    <div className="chat-empty">
                        {isAdmin
                            ? (labels.adminViewOnly || 'View-only: you can review escalation messages here.')
                            : (labels.expertPrompt || 'You have joined the escalation. Send a message to start helping the operator.')}
                    </div>
                )}

                {messages.map(msg => {
                    const isMe = msg.senderId === userId
                    const isSystem = msg.senderRole === 'system'

                    if (isSystem) {
                        return (
                            <div key={msg.id} className="chat-msg chat-msg-system">
                                <div className="chat-msg-bubble system">{msg.message}</div>
                            </div>
                        )
                    }

                    return (
                        <div key={msg.id} className={`chat-msg ${isMe ? 'chat-msg-me' : 'chat-msg-other'}`}>
                            <div className="chat-msg-meta">
                                <span className="chat-msg-role">
                                    {isMe ? (labels.you || 'You') : msg.senderRole === 'expert' ? (labels.roleExpert || '🔧 Expert') : (labels.userWithId ? labels.userWithId(msg.senderId) : `User #${msg.senderId}`)}
                                </span>
                                <span className="chat-msg-time">{formatTime(msg.timestamp)}</span>
                            </div>
                            <div className={`chat-msg-bubble ${isMe ? 'me' : 'other'}`}>
                                {msg.message}
                            </div>
                        </div>
                    )
                })}
                <div ref={chatEndRef} />
            </div>

            {/* Input */}
            {status !== 'closed' && !isAdmin && (
                <form className="chat-input-area" onSubmit={sendMessage}>
                    <input
                        type="text"
                        className="chat-input"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder={status === 'connected' ? (labels.placeholderConnected || 'Type a message...') : (labels.placeholderWaiting || 'Waiting for connection...')}
                        disabled={status !== 'connected'}
                    />
                    <button
                        type="submit"
                        className="btn chat-send-btn"
                        disabled={status !== 'connected' || !input.trim()}
                    >
                        {labels.send || 'Send'}
                    </button>
                </form>
            )}
        </div>
    )
}
