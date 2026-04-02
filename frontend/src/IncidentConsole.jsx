import { useState, useRef, useEffect, useCallback } from 'react'
import { createIncident, submitAnswer, submitOutcome, generateBrief, logout, getStoredUser, listIncidents, getIncident } from './api'
import EscalationChat from './EscalationChat'

const CATEGORY_LABELS = {
    trigger: 'Trigger',
    internal_equipment: 'Internal Equipment',
    upstream: 'Upstream',
    downstream: 'Downstream',
    control: 'Control System',
    instrumentation: 'Instrumentation',
    utilities: 'Utilities',
    process_conditions: 'Process Conditions',
    procedure_human: 'Procedure/Human',
    verification_closure: 'Verification',
    clarification: 'Clarification',
}

export default function IncidentConsole({ user, onLogout, onAdmin, onSuperAdmin }) {
    const [messages, setMessages] = useState([])
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [phase, setPhase] = useState('idle') // idle | diagnosing | brief | outcome | escalation_chat | closed
    const [incident, setIncident] = useState(null)
    const [escalationSession, setEscalationSession] = useState(null) // { session_id, ws_url }
    const [chatMinimized, setChatMinimized] = useState(false)
    const [history, setHistory] = useState([])
    const [showSidebar, setShowSidebar] = useState(user?.user_type === 'viewer')
    const chatRef = useRef(null)
    const inputRef = useRef(null)
    const outcomeSelectedOptionIdRef = useRef(null)

    const storedUser = getStoredUser()

    const loadHistory = useCallback(async () => {
        try {
            const data = await listIncidents()
            setHistory(data.incidents || [])
        } catch (e) {
            console.error("Failed to load history:", e)
        }
    }, [])

    useEffect(() => {
        loadHistory()
    }, [loadHistory])

    useEffect(() => {
        if (chatRef.current) {
            chatRef.current.scrollTop = chatRef.current.scrollHeight
        }
    }, [messages, loading])

    useEffect(() => {
        if (inputRef.current && !loading) {
            inputRef.current.focus()
        }
    }, [loading, phase])

    const addMessage = (type, content) => {
        setMessages(prev => [...prev, { id: Date.now() + Math.random(), type, content }])
    }

    const handleLoadIncident = async (incidentId) => {
        if (loading) return
        setLoading(true)
        // Reset escalation chat state to prevent stale chat from previous incident
        setEscalationSession(null)
        setChatMinimized(true)
        try {
            const data = await getIncident(incidentId)
            setIncident(data)

            const msgs = []
            if (data.report) {
                // Strip appended [User Clarification]: blocks — show only original report
                const cleanReport = data.report.split('[User Clarification]:')[0].trim()
                if (cleanReport) {
                    msgs.push({ id: Math.random(), type: 'user', content: cleanReport })
                }
            }
            if (data.incident_card) {
                msgs.push({ id: Math.random(), type: 'system', content: { type: 'incident_card', data: data.incident_card } })
                if (data.memory_guidance) {
                    msgs.push({ id: Math.random(), type: 'system', content: { type: 'memory_guidance', message: data.memory_guidance } })
                }
                if (data.retrieved_patterns?.length > 0) {
                    msgs.push({ id: Math.random(), type: 'system', content: { type: 'patterns', data: data.retrieved_patterns } })
                }
            }
            if (data.qa_history && data.qa_history.length > 0) {
                data.qa_history.forEach(qa => {
                    msgs.push({ id: Math.random(), type: 'system', content: { type: 'questions', data: [{ category: qa.category || 'clarification', question: qa.question }] } })
                    if (qa.answer) {
                        msgs.push({ id: Math.random(), type: 'user', content: qa.answer })
                    }
                })
            }
            if (data.decision_brief) {
                if (data.escalation_triggered) {
                    msgs.push({ id: Math.random(), type: 'system', content: { type: 'escalation_notice', message: '⏳ This incident requires immediate escalation. Connecting you with a specialist...' } })
                }
                if (data.escalation) {
                    msgs.push({ id: Math.random(), type: 'system', content: { type: 'escalation', data: data.escalation } })
                }
                msgs.push({ id: Math.random(), type: 'system', content: { type: 'brief', data: data.decision_brief, escalationTriggered: data.escalation_triggered } })
            }
            // Always show the pending clarification question (last LLM response) if present
            if (data.clarification_question) {
                msgs.push({ id: Math.random(), type: 'system', content: { type: 'questions', data: [{ category: 'clarification', question: data.clarification_question }] } })
            } else if (!data.decision_brief && data.questions && data.questions.length > 0 && !['CLOSED', 'SUCCESS'].includes(data.status)) {
                msgs.push({ id: Math.random(), type: 'system', content: { type: 'questions', data: data.questions, step: data.current_diagnostic_step } })
            }
            if (data.outcome && data.outcome !== 'pending') {
                msgs.push({ id: Math.random(), type: 'system', content: { type: 'outcome_result', data } })
            }

            setMessages(msgs)

            if (data.status === 'CLOSED' || data.status === 'SUCCESS') {
                setPhase('closed')
                setEscalationSession(null)
            } else if (data.escalation?.session_id) {
                setEscalationSession(data.escalation)
                setChatMinimized(false)
                setPhase('escalation_chat')
            } else if (data.decision_brief && data.outcome === 'pending') setPhase('outcome')
            else if (data.clarification_question || (data.questions && data.questions.length > 0)) setPhase('diagnosing')
            else setPhase('idle')
        } catch (err) {
            showError(err, 'Load incident:')
        }
        setLoading(false)
    }

    /** Show a user-friendly error in chat; log the real error for debugging. */
    const showError = (err, context = '') => {
        const raw = err?.message || String(err)
        if (raw.includes('NoneType') || raw.startsWith('Processing error:') || raw.includes('object has no attribute')) {
            console.error(context, raw)
            addMessage('system', { type: 'error', message: 'Something went wrong on our side. Please try again or start a new incident.' })
        } else {
            addMessage('system', { type: 'error', message: raw })
        }
    }

    const getPlaceholder = () => {
        if (loading) return 'Processing...'
        if (phase === 'idle') return 'Describe the incident...'
        if (phase === 'diagnosing') return 'Answer the questions...'
        if (phase === 'outcome') return 'Describe the outcome...'
        return 'Type a message...'
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        const text = input.trim()
        if (!text || loading) return

        setInput('')

        if (phase === 'idle') {
            // Create a new incident
            addMessage('user', text)
            setLoading(true)

            try {
                const data = await createIncident(text)
                setIncident(data)
                loadHistory()

                if (data.clarification_question) {
                    addMessage('system', { type: 'questions', data: [{ category: 'clarification', question: data.clarification_question }] })
                    setPhase('diagnosing')
                } else {
                    // Show incident card
                    addMessage('system', { type: 'incident_card', data: data.incident_card })

                    if (data.memory_guidance) {
                        addMessage('system', { type: 'memory_guidance', message: data.memory_guidance })
                    }
                    if (data.retrieved_patterns?.length > 0) {
                        addMessage('system', { type: 'patterns', data: data.retrieved_patterns })
                    }

                    // Show status
                    addMessage('system', { type: 'status', data })

                    if (data.escalation_triggered && data.decision_brief) {
                        addMessage('system', { type: 'escalation_notice', message: '⏳ This incident requires immediate escalation. Connecting you with a specialist...' })
                        if (data.escalation) {
                            addMessage('system', { type: 'escalation', data: data.escalation })
                            if (data.escalation.session_id) {
                                setEscalationSession(data.escalation)
                                setChatMinimized(false)
                                setPhase('escalation_chat')
                            }
                        }
                        addMessage('system', { type: 'escalation_notice', message: '✅ Escalation request sent. An expert will review your incident shortly.' })
                        addMessage('system', { type: 'brief', data: data.decision_brief, escalationTriggered: true })
                        if (!data.escalation?.session_id) {
                            // Fallback: no session yet, stay in outcome so user can still see brief
                            setPhase('outcome')
                        }
                    } else if (data.questions?.length > 0) {
                        addMessage('system', { type: 'questions', data: data.questions, step: data.current_diagnostic_step })
                        setPhase('diagnosing')
                    }
                }
            } catch (err) {
                showError(err, 'Create incident:')
            }

            setLoading(false)

        } else if (phase === 'diagnosing') {
            // Submit an answer
            addMessage('user', text)
            setLoading(true)

            try {
                const data = await submitAnswer(incident.incident_id, text)
                const prevMemoryGuidance = incident?.memory_guidance || ''
                // If card was just generated, show it
                if (!incident.incident_card && data.incident_card) {
                    addMessage('system', { type: 'incident_card', data: data.incident_card })
                    if (data.memory_guidance) {
                        addMessage('system', { type: 'memory_guidance', message: data.memory_guidance })
                    }
                    if (data.retrieved_patterns?.length > 0) {
                        addMessage('system', { type: 'patterns', data: data.retrieved_patterns })
                    }
                }

                setIncident(data)
                loadHistory()

                if (data.memory_guidance && data.memory_guidance !== prevMemoryGuidance) {
                    addMessage('system', { type: 'memory_guidance', message: data.memory_guidance })
                }
                if (data.retrieved_patterns?.length > 0 && incident.incident_card) {
                    const prevIds = (incident.retrieved_patterns || []).map((p) => p.pattern_id).join(',')
                    const nextIds = (data.retrieved_patterns || []).map((p) => p.pattern_id).join(',')
                    if (nextIds !== prevIds) {
                        addMessage('system', { type: 'patterns', data: data.retrieved_patterns })
                    }
                }

                if (data.clarification_question) {
                    addMessage('system', { type: 'questions', data: [{ category: 'clarification', question: data.clarification_question }] })
                } else {
                    addMessage('system', { type: 'status', data })

                    if (data.decision_brief) {
                        addMessage('system', { type: 'brief', data: data.decision_brief })
                        setPhase('outcome')
                    } else if (data.escalation_triggered) {
                        // Generate brief if escalation triggered
                        addMessage('system', { type: 'escalation_notice', message: '⏳ Based on the diagnosis, this incident needs to be escalated. Please wait...' })
                        const briefData = await generateBrief(data.incident_id)
                        setIncident(briefData)
                        if (briefData.escalation) {
                            addMessage('system', { type: 'escalation', data: briefData.escalation })
                            if (briefData.escalation.session_id) {
                                setEscalationSession(briefData.escalation)
                                setChatMinimized(false)
                                setPhase('escalation_chat')
                            }
                        }
                        addMessage('system', { type: 'escalation_notice', message: '✅ Escalation complete. An expert has been notified and will assist with this incident.' })
                        addMessage('system', { type: 'brief', data: briefData.decision_brief, escalationTriggered: true })
                        if (!briefData.escalation?.session_id) {
                            // Fallback: no session yet, stay in outcome so user can still see brief
                            setPhase('outcome')
                        }
                    } else if (data.questions?.length > 0) {
                        addMessage('system', { type: 'questions', data: data.questions, step: data.current_diagnostic_step })
                    } else {
                        // No more questions, generate brief
                        const briefData = await generateBrief(data.incident_id)
                        setIncident(briefData)
                        addMessage('system', { type: 'brief', data: briefData.decision_brief })
                        setPhase('outcome')
                    }
                }
            } catch (err) {
                showError(err, 'Submit answer:')
            }

            setLoading(false)

        } else if (phase === 'outcome') {
            // Submit outcome
            addMessage('user', text)
            setLoading(true)

            try {
                const selectedOpt = outcomeSelectedOptionIdRef.current
                outcomeSelectedOptionIdRef.current = null
                const data = await submitOutcome(incident.incident_id, text, selectedOpt)
                setIncident(data)

                addMessage('system', { type: 'outcome_result', data })

                if (data.outcome === 'success') {
                    setPhase('closed')
                    setEscalationSession(null)
                    setChatMinimized(false)
                } else if (data.escalation_triggered) {
                    addMessage('system', { type: 'escalation_notice', message: '⏳ Your issue is being escalated to a specialist. Please wait while we connect you with the right team...' })
                    if (data.escalation) {
                        addMessage('system', { type: 'escalation', data: data.escalation })
                    }
                    addMessage('system', { type: 'escalation_notice', message: '✅ Escalation request sent successfully. An expert has been notified and will review your incident. You will receive further guidance through the escalation channel.' })
                    // Open escalation chat if session exists
                    if (data.escalation?.session_id) {
                        setEscalationSession(data.escalation)
                        setChatMinimized(false)
                        setPhase('escalation_chat')
                    }
                    // If no session, stay in outcome (don't close) so user can retry or start new
                } else {
                    addMessage('system', { type: 'status', data })
                    // Failure — stay in outcome for retry
                }
            } catch (err) {
                showError(err, 'Submit outcome:')
            }

            setLoading(false)
        }
    }

    const handleNewIncident = () => {
        setMessages([])
        setIncident(null)
        setEscalationSession(null)
        setChatMinimized(false)
        setPhase('idle')
        setInput('')
    }

    const handleOutcomeButton = (outcome, selectedOptionId = null) => {
        outcomeSelectedOptionIdRef.current = selectedOptionId
        setInput(outcome)
        setTimeout(() => {
            const form = document.querySelector('form')
            if (form) form.requestSubmit()
        }, 50)
    }

    return (
        <div className="app">
            {/* Header */}
            <header className="header">
                <h1>⚙️ <span>Decisio</span></h1>
                <div className="header-status">
                    {incident && (
                        <>
                            <span>
                                <span className={`status-dot ${incident.escalation_triggered ? 'danger' : incident.confidence >= 0.8 ? 'active' : 'warning'}`}></span>
                                {incident.status}
                            </span>
                            <span>Risk: {incident.risk_score?.toFixed(1)}</span>
                            <span>Confidence: {Math.round((incident.confidence || 0) * 100)}%</span>
                        </>
                    )}
                    {(phase === 'closed' || phase === 'escalation_chat') && (
                        <button className="btn btn-outline" onClick={handleNewIncident} style={{ padding: '6px 12px', fontSize: '12px' }}>
                            + New Incident
                        </button>
                    )}
                    <div className="header-user-area">
                        {/* Live chat button — hide for resolved incidents */}
                        {escalationSession?.session_id && incident?.status !== 'SUCCESS' && incident?.status !== 'CLOSED' && (
                            <button
                                className="btn btn-outline btn-sm"
                                onClick={() => {
                                    setChatMinimized(false)
                                    setPhase('escalation_chat')
                                }}
                                style={{ borderColor: '#06b6d4', color: '#06b6d4' }}
                            >
                                💬 Live chat with expert
                            </button>
                        )}
                        <span className="header-username">{user?.full_name || user?.username}</span>
                        {user?.user_type === 'super_admin' && (
                            <button className="btn btn-outline btn-sm" onClick={onSuperAdmin} style={{ borderColor: '#7c3aed', color: '#7c3aed' }}>Super Admin</button>
                        )}
                        {(user?.user_type === 'admin' || user?.user_type === 'super_admin') && (
                            <button className="btn btn-outline btn-sm" onClick={onAdmin}>Admin</button>
                        )}
                        <button className="btn btn-outline btn-sm btn-danger-outline" onClick={logout}>Logout</button>
                    </div>
                </div>
            </header>

            <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
                {/* Sidebar */}
                {showSidebar && (
                    <div className="sidebar" style={{
                        width: '280px',
                        borderRight: '1px solid var(--border)',
                        background: 'var(--bg-card)',
                        display: 'flex',
                        flexDirection: 'column',
                        overflowY: 'auto'
                    }}>
                        <div style={{ padding: '16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ margin: 0, fontSize: '14px', color: 'var(--text-bright)' }}>My Incidents</h3>
                            <button className="btn btn-outline" style={{ padding: '4px 8px', fontSize: '11px' }} onClick={handleNewIncident}>+ New</button>
                        </div>
                        {history.length === 0 && (
                            <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-dim)', fontSize: '13px' }}>
                                No past incidents.
                            </div>
                        )}
                        {history.map(inc => (
                            <div
                                key={inc.incident_id}
                                onClick={() => handleLoadIncident(inc.incident_id)}
                                style={{
                                    padding: '12px 16px',
                                    borderBottom: '1px solid var(--border)',
                                    cursor: 'pointer',
                                    background: incident?.incident_id === inc.incident_id ? 'var(--bg-hover)' : 'transparent',
                                }}
                            >
                                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-bright)', marginBottom: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {inc.summary || 'New Incident'}
                                </div>
                                <div style={{ fontSize: '12px', color: 'var(--text-dim)', display: 'flex', justifyContent: 'space-between' }}>
                                    <span>{inc.status}</span>
                                    <span>{new Date(inc.created_at).toLocaleDateString()}</span>
                                </div>
                                {(inc.risk_score > 0 || inc.confidence > 0) && (
                                    <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>
                                        Risk: {inc.risk_score.toFixed(1)} | Conf: {Math.round(inc.confidence * 100)}%
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}

                {/* Main Content Area */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative' }}>
                    {/* Chat Area */}
                    <div className="chat-container" ref={chatRef}>
                        {messages.length === 0 && (
                            <div className="welcome">
                                <div className="welcome-icon">⚙️</div>
                                <h2>Decisio</h2>
                                <p>
                                    Operational Decision Support System.<br />
                                    Describe an incident to begin diagnosis.
                                </p>
                            </div>
                        )}

                        {messages.map(msg => (
                            <div key={msg.id} className={`message ${msg.type === 'user' ? 'message-user' : 'message-system'}`}>
                                {msg.type === 'user' && (
                                    <>
                                        <div className="message-label">You</div>
                                        <div>{msg.content}</div>
                                    </>
                                )}

                                {msg.type === 'system' && renderSystemMessage(msg.content, handleOutcomeButton, phase)}
                            </div>
                        ))}

                        {loading && (
                            <div className="message message-system">
                                <div className="loading">
                                    <div className="loading-dots">
                                        <span></span><span></span><span></span>
                                    </div>
                                    Analyzing...
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Escalation Chat Panel (visible for viewer as well once escalation starts) */}
                    {escalationSession?.session_id && (
                        <EscalationChat
                            sessionId={escalationSession.session_id}
                            companyId={storedUser?.company_id}
                            userId={storedUser?.id}
                            userRole={user?.user_type}
                            minimized={chatMinimized}
                            onMinimize={() => setChatMinimized(prev => !prev)}
                            onSessionClosed={async () => {
                                // After escalation chat closes, transition to outcome (success/fail buttons)
                                // without showing the decision brief
                                try {
                                    const data = await getIncident(incident.incident_id)
                                    setIncident(data)
                                } catch (err) {
                                    // ignore reload error
                                }
                                setPhase('outcome')
                            }}
                        />
                    )}

                    {/* Input Area — ChatGPT-style pill bar */}
                    {phase !== 'closed' && phase !== 'escalation_chat' && (
                        <div className="gpt-input-wrapper">
                            <form className="gpt-input-pill" onSubmit={handleSubmit}>
                                <textarea
                                    ref={inputRef}
                                    className="gpt-input-field"
                                    value={input}
                                    onChange={(e) => {
                                        setInput(e.target.value)
                                        // Auto-resize
                                        e.target.style.height = 'auto'
                                        e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px'
                                    }}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && !e.shiftKey) {
                                            e.preventDefault()
                                            handleSubmit(e)
                                        }
                                    }}
                                    placeholder={getPlaceholder()}
                                    disabled={loading}
                                    rows={1}
                                />
                                <button
                                    type="submit"
                                    className={`gpt-input-icon gpt-send-btn ${input.trim() ? 'has-text' : ''}`}
                                    disabled={loading || !input.trim()}
                                    title="Send"
                                >
                                    {input.trim() ? (
                                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a1 1 0 0 1 .707.293l.003.003-7.5 7.5a1 1 0 0 1-1.414-1.414L10.586 3H4a1 1 0 0 1 0-2h8z" transform="rotate(0 12 12)" /><path d="M12 3.414l5.293 5.293a1 1 0 0 0 1.414-1.414l-6-6a1 1 0 0 0-1.414 0l-6 6a1 1 0 0 0 1.414 1.414L12 3.414z" /><path d="M11 21V4h2v17h-2z" /></svg>
                                    ) : (
                                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" y1="19" x2="12" y2="23" /><line x1="8" y1="23" x2="16" y2="23" /></svg>
                                    )}
                                </button>
                            </form>
                            <div className="gpt-input-disclaimer">Decisio can make mistakes. Verify important decisions.</div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

function renderSystemMessage(content, onOutcome, phase) {
    if (typeof content === 'string') {
        return <div>{content}</div>
    }

    switch (content.type) {
        case 'incident_card':
            return <IncidentCard data={content.data} />
        case 'questions':
            return <Questions data={content.data} step={content.step} />
        case 'status':
            return <StatusBar data={content.data} />
        case 'brief':
            return <DecisionBrief data={content.data} onOutcome={onOutcome} showOutcome={phase === 'outcome'} escalationTriggered={content.escalationTriggered} />
        case 'patterns':
            return <Patterns data={content.data} />
        case 'memory_guidance':
            return (
                <div style={{
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: 'rgba(59, 130, 246, 0.08)',
                    border: '1px solid rgba(59, 130, 246, 0.25)',
                    fontSize: '13px',
                    color: 'var(--text-bright)',
                    lineHeight: 1.55,
                }}>
                    <div className="message-label" style={{ marginBottom: 6 }}>Decision Memory</div>
                    {content.message}
                </div>
            )
        case 'escalation':
            return <Escalation data={content.data} />
        case 'escalation_notice':
            return (
                <div style={{
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: 'rgba(251, 191, 36, 0.08)',
                    border: '1px solid rgba(251, 191, 36, 0.2)',
                    fontSize: '13px',
                    color: 'var(--warning)',
                    lineHeight: 1.5
                }}>
                    {content.message}
                </div>
            )
        case 'outcome_result':
            return <OutcomeResult data={content.data} />
        case 'error':
            return <div style={{ color: 'var(--danger)' }}>❌ {content.message}</div>
        default:
            return <div>{JSON.stringify(content)}</div>
    }
}


function IncidentCard({ data }) {
    if (!data) return null
    const severityClass = `badge badge-${data.severity || 'medium'}`

    return (
        <>
            <div className="message-label">Incident Card</div>
            <div style={{ fontSize: '14px', marginBottom: '8px', color: 'var(--text-bright)', fontWeight: 500 }}>
                {data.normalized_summary}
            </div>
            <div className="incident-card">
                <div className="incident-field">
                    <div className="incident-field-label">Asset</div>
                    <div className="incident-field-value">{data.asset_id || '—'}</div>
                </div>
                <div className="incident-field">
                    <div className="incident-field-label">Severity</div>
                    <div className="incident-field-value"><span className={severityClass}>{data.severity}</span></div>
                </div>
                <div className="incident-field">
                    <div className="incident-field-label">Safety</div>
                    <div className="incident-field-value">{data.safety_level || '—'}</div>
                </div>
                <div className="incident-field">
                    <div className="incident-field-label">Risk</div>
                    <div className="incident-field-value">{data.initial_risk_score ?? '—'}</div>
                </div>
                <div className="incident-field">
                    <div className="incident-field-label">Scope</div>
                    <div className="incident-field-value">{data.scope || '—'}</div>
                </div>
                <div className="incident-field">
                    <div className="incident-field-label">Symptoms</div>
                    <div className="incident-field-value">{data.symptoms?.join(', ') || '—'}</div>
                </div>
            </div>
        </>
    )
}


function Questions({ data, step }) {
    if (!data?.length) return null
    const stepLabel = step ? `Step ${step}/10` : ''

    return (
        <>
            <div className="message-label">
                {data.some(q => q.category === 'clarification') ? 'Intake Question' : `Diagnostic Questions — ${stepLabel}`}
            </div>
            <div className="questions-list">
                {data.map((q, i) => (
                    <div key={i} className="question-item">
                        <div className="question-category">
                            {CATEGORY_LABELS[q.category] || q.category}
                            {q.blocking_safety_flag && ' ⚠️'}
                        </div>
                        {q.question}
                    </div>
                ))}
            </div>
        </>
    )
}


function StatusBar({ data }) {
    return (
        <div className="status-bar">
            <span className="status-chip">Risk <strong>{data.risk_score?.toFixed(1)}</strong></span>
            <span className="status-chip">Confidence <strong>{Math.round((data.confidence || 0) * 100)}%</strong></span>
            <span className="status-chip">Step <strong>{data.current_diagnostic_step}/10</strong></span>
            {data.escalation_triggered && (
                <span className="status-chip" style={{ borderColor: 'var(--danger)', color: 'var(--danger)' }}>
                    ⚠️ Escalation
                </span>
            )}
            {data.hypotheses?.slice(0, 2).map((h, i) => (
                <span key={i} className="status-chip">
                    {h.description?.slice(0, 30)}... <strong>{Math.round(h.probability * 100)}%</strong>
                </span>
            ))}
        </div>
    )
}


function DecisionBrief({ data, onOutcome, showOutcome, escalationTriggered }) {
    const [selectedOption, setSelectedOption] = useState(null)

    useEffect(() => {
        if (!showOutcome || !data?.options?.length) {
            setSelectedOption(null)
            return
        }
        const recIdx = data.options.findIndex((o) => o.recommended)
        setSelectedOption(recIdx >= 0 ? recIdx : 0)
    }, [showOutcome, data])

    if (!data) return null

    return (
        <>
            <div className="message-label">📋 Decision Brief</div>
            <div className="brief">
                <div className="brief-meta">
                    <span className="brief-meta-item">Confidence: <strong>{Math.round((data.overall_confidence || 0) * 100)}%</strong></span>
                    <span className="brief-meta-item">Authority: <strong>{data.decision_authority || '—'}</strong></span>
                    {data.escalation_path && (
                        <span className="brief-meta-item">Escalation: <strong>{data.escalation_path}</strong></span>
                    )}
                </div>

                {data.risk_summary && (
                    <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginBottom: '12px', lineHeight: 1.5 }}>
                        {data.risk_summary}
                    </div>
                )}

                {data.options?.map((opt, i) => (
                    <div
                        key={i}
                        className={`option-card ${!escalationTriggered && opt.recommended ? 'recommended' : ''} ${selectedOption === i ? 'selected' : ''} ${showOutcome ? 'selectable' : ''}`}
                        onClick={() => showOutcome && setSelectedOption(i)}
                    >
                        <div className="option-header">
                            <span className="option-title">{opt.title}</span>
                            {!escalationTriggered && opt.recommended && <span className="option-badge">Recommended</span>}
                        </div>
                        <div className="option-desc">{opt.description}</div>
                        <div className="option-tags">
                            {opt.risks?.map((r, j) => <span key={j} className="option-tag">{r}</span>)}
                            {opt.constraints?.map((c, j) => <span key={j} className="option-tag constraint">{c}</span>)}
                        </div>
                    </div>
                ))}

                {data.safety_constraints?.length > 0 && (
                    <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--warning)' }}>
                        ⚠️ Safety: {data.safety_constraints.join(' • ')}
                    </div>
                )}

                {showOutcome && (
                    <div className="outcome-actions">
                        <button
                            className="btn btn-success"
                            onClick={() => {
                                if (data.options?.length > 0 && selectedOption === null) {
                                    return
                                }
                                const id =
                                    selectedOption != null && data.options?.[selectedOption] != null
                                        ? data.options[selectedOption].option_id
                                        : null
                                onOutcome('success', id)
                            }}
                            style={{ fontSize: '13px', padding: '8px 16px' }}
                        >
                            ✅ Success
                        </button>
                        <button className="btn btn-danger" onClick={() => onOutcome('failure', null)} style={{ fontSize: '13px', padding: '8px 16px' }}>
                            ❌ Failure
                        </button>
                    </div>
                )}
            </div>
        </>
    )
}


function Patterns({ data }) {
    if (!data?.length) return null
    return (
        <>
            <div className="message-label">Similar Past Incidents</div>
            {data.map((p, i) => (
                <div key={i} style={{ fontSize: '13px', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ color: 'var(--text-bright)' }}>{p.title}</span>
                    <span style={{ color: 'var(--text-dim)', marginLeft: '8px' }}>
                        {Math.round(p.similarity_score * 100)}%
                    </span>
                    {p.must_escalate && <span style={{ color: 'var(--danger)', marginLeft: '8px' }}>⚠️ Must Escalate</span>}
                    {p.decision_taken && (
                        <div style={{ color: 'var(--text-dim)', marginTop: 4, fontSize: '12px', lineHeight: 1.45 }}>
                            Prior decision: {p.decision_taken}
                        </div>
                    )}
                </div>
            ))}
        </>
    )
}


function Escalation({ data }) {
    if (!data) return null

    // Edge case: no escalation matrix configured for this company
    if (data.pending_config) {
        return (
            <>
                <div className="message-label" style={{ color: 'var(--warning)' }}>⏳ Escalation Pending</div>
                <div className="escalation-box" style={{ borderColor: 'var(--warning)' }}>
                    <div className="escalation-level" style={{ color: 'var(--warning)' }}>
                        ⚙️ Escalation Matrix Not Configured
                    </div>
                    <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: 6 }}>
                        {data.escalation_level_description || 'No escalation levels have been set up for your company.'}
                    </div>
                    <div style={{ fontSize: '12px', marginTop: '8px', color: 'var(--text-dim)', opacity: 0.8 }}>
                        Your incident has been flagged for escalation but is waiting until an administrator
                        configures the escalation matrix in <strong>Admin Portal → Escalation</strong>.
                    </div>
                </div>
            </>
        )
    }

    return (
        <>
            <div className="message-label" style={{ color: 'var(--danger)' }}>🔴 Escalation</div>
            <div className="escalation-box">
                <div className="escalation-level">
                    Level {data.escalation_level}: {data.escalation_level_name}
                </div>
                <div style={{ fontSize: '13px', color: 'var(--text-dim)' }}>
                    {data.escalation_summary}
                </div>
                {data.decision_authority && (
                    <div style={{ fontSize: '12px', marginTop: '6px' }}>
                        Authority: <strong>{data.decision_authority}</strong>
                    </div>
                )}
                {data.escalation_target && (
                    <div style={{ fontSize: '12px', marginTop: '2px' }}>
                        Escalation: <strong>{data.escalation_target}</strong>
                    </div>
                )}
                {data.urgency && (
                    <div style={{ fontSize: '12px', marginTop: '6px', color: 'var(--warning)' }}>
                        Urgency: {data.urgency}
                    </div>
                )}
            </div>
        </>
    )
}


function OutcomeResult({ data }) {
    const isSuccess = data.outcome === 'success'
    return (
        <>
            <div className="message-label" style={{ color: isSuccess ? 'var(--success)' : 'var(--danger)' }}>
                {isSuccess ? '✅ Resolved' : '❌ Resolution Failed'}
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-dim)' }}>
                Status: {data.status}
                {data.memory_written && ' • Decision pattern saved to memory'}
                {data.failed_attempts > 0 && ` • ${data.failed_attempts} failed attempt(s)`}
            </div>
        </>
    )
}
