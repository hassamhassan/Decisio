import { useState, useRef, useEffect } from 'react'
import { createIncident, submitAnswer, submitOutcome, generateBrief, logout } from './api'

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
}

export default function IncidentConsole({ user, onLogout, onAdmin, onSuperAdmin }) {
    const [messages, setMessages] = useState([])
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [phase, setPhase] = useState('idle') // idle | diagnosing | brief | outcome | closed
    const [incident, setIncident] = useState(null)
    const chatRef = useRef(null)
    const inputRef = useRef(null)

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

                // Show incident card
                addMessage('system', { type: 'incident_card', data: data.incident_card })

                // Show patterns
                if (data.retrieved_patterns?.length > 0) {
                    addMessage('system', { type: 'patterns', data: data.retrieved_patterns })
                }

                // Show status
                addMessage('system', { type: 'status', data })

                if (data.escalation_triggered && data.decision_brief) {
                    addMessage('system', { type: 'escalation', data: data.escalation })
                    addMessage('system', { type: 'brief', data: data.decision_brief })
                    setPhase('outcome')
                } else if (data.questions?.length > 0) {
                    addMessage('system', { type: 'questions', data: data.questions, step: data.current_diagnostic_step })
                    setPhase('diagnosing')
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
                setIncident(data)

                addMessage('system', { type: 'status', data })

                if (data.decision_brief) {
                    addMessage('system', { type: 'brief', data: data.decision_brief })
                    setPhase('outcome')
                } else if (data.escalation_triggered) {
                    // Generate brief if escalation triggered
                    const briefData = await generateBrief(data.incident_id)
                    setIncident(briefData)
                    if (briefData.escalation) {
                        addMessage('system', { type: 'escalation', data: briefData.escalation })
                    }
                    addMessage('system', { type: 'brief', data: briefData.decision_brief })
                    setPhase('outcome')
                } else if (data.questions?.length > 0) {
                    addMessage('system', { type: 'questions', data: data.questions, step: data.current_diagnostic_step })
                } else {
                    // No more questions, generate brief
                    const briefData = await generateBrief(data.incident_id)
                    setIncident(briefData)
                    addMessage('system', { type: 'brief', data: briefData.decision_brief })
                    setPhase('outcome')
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
                const data = await submitOutcome(incident.incident_id, text)
                setIncident(data)

                addMessage('system', { type: 'outcome_result', data })

                if (data.outcome === 'success') {
                    setPhase('closed')
                } else if (data.escalation_triggered) {
                    if (data.escalation) {
                        addMessage('system', { type: 'escalation', data: data.escalation })
                    }
                    setPhase('closed')
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
        setPhase('idle')
        setInput('')
    }

    const handleOutcomeButton = (outcome) => {
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
                    {phase === 'closed' && (
                        <button className="btn btn-outline" onClick={handleNewIncident} style={{ padding: '6px 12px', fontSize: '12px' }}>
                            + New Incident
                        </button>
                    )}
                    <div className="header-user-area">
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

            {/* Input Area */}
            {phase !== 'closed' && (
                <div className="input-area">
                    <form className="input-row" onSubmit={handleSubmit}>
                        <textarea
                            ref={inputRef}
                            className="input-field"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
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
                        <button className="btn" type="submit" disabled={loading || !input.trim()}>
                            Send
                        </button>
                    </form>
                </div>
            )}
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
            return <DecisionBrief data={content.data} onOutcome={onOutcome} showOutcome={phase === 'outcome'} />
        case 'patterns':
            return <Patterns data={content.data} />
        case 'escalation':
            return <Escalation data={content.data} />
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
            <div className="message-label">Diagnostic Questions — {stepLabel}</div>
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


function DecisionBrief({ data, onOutcome, showOutcome }) {
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
                    <div key={i} className={`option-card ${opt.recommended ? 'recommended' : ''}`}>
                        <div className="option-header">
                            <span className="option-title">{opt.title}</span>
                            {opt.recommended && <span className="option-badge">Recommended</span>}
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
                        <button className="btn btn-success" onClick={() => onOutcome('success')} style={{ fontSize: '13px', padding: '8px 16px' }}>
                            ✅ Success
                        </button>
                        <button className="btn btn-danger" onClick={() => onOutcome('failure')} style={{ fontSize: '13px', padding: '8px 16px' }}>
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
                </div>
            ))}
        </>
    )
}


function Escalation({ data }) {
    if (!data) return null
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
