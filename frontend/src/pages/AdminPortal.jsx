import { useState, useEffect, useRef, useCallback } from 'react'
import {
    getDashboard, listUsers, createUser, updateUser, deleteUser,
    listEquipment, listSafetyRules, getEscalationMatrix, listIncidentReports,
    listIncidents, getIncident, logout, getStoredUser,
    createEquipment, updateEquipment, deleteEquipment,
    uploadEquipmentManual, deleteEquipmentManual, getEquipmentManualStatus,
    createSafetyRule, updateSafetyRule, deleteSafetyRule,
    createEscalationLevel, updateEscalationLevel, deleteEscalationLevel,
    createEscalationRule, updateEscalationRule, deleteEscalationRule,
    changePassword, getKpiStats, getEscalationSessions,
    getAdminNotifications, markNotificationRead, markAllNotificationsRead,
} from '../services/api'
import EscalationChat from '../components/EscalationChat'
import LanguageToggle from '../components/LanguageToggle'
import { useI18n } from '../i18n'

function getSections(t) {
    return [
        { id: 'dashboard', label: t('adminPage.sidebar.sections.dashboard'), icon: '📊' },
        { id: 'users', label: t('adminPage.sidebar.sections.users'), icon: '👥' },
        { id: 'incidents', label: t('adminPage.sidebar.sections.incidents'), icon: '🔧' },
        { id: 'equipment', label: t('adminPage.sidebar.sections.equipment'), icon: '📦' },
        { id: 'safety', label: t('adminPage.sidebar.sections.safety'), icon: '🛡️' },
        { id: 'escalation', label: t('adminPage.sidebar.sections.escalation'), icon: '📈' },
        { id: 'live', label: t('adminPage.sidebar.sections.live'), icon: '💬' },
        { id: 'reports', label: t('adminPage.sidebar.sections.reports'), icon: '📋' },
    ]
}

const TYPE_COLORS = {
    admin: '#ef4444',
    operator: '#3b82f6',
    engineer: '#10b981',
    viewer: '#8b5cf6',
    expert: '#f97316',
    escalation_owner: '#f97316',
}
function userTypeColor(userType) {
    if (/^L\d+$/.test(userType)) return '#f97316'
    return TYPE_COLORS[userType] ?? '#64748b'
}

function NotificationDropdown({ notifications, onNotifClick, onMarkAll }) {
    const { t } = useI18n()
    const unread = notifications.filter(n => !n.is_read)
    const read = notifications.filter(n => n.is_read)
    const shown = [...unread, ...read].slice(0, 20)

    return (
        <div className="notif-dropdown">
            <div className="notif-dropdown-header">
                <span>{t('adminPage.sidebar.notifications')}</span>
                {unread.length > 0 && (
                    <button type="button" className="notif-mark-all-btn" onClick={onMarkAll}>
                        {t('adminPage.sidebar.markAllRead')}
                    </button>
                )}
            </div>
            {shown.length === 0 && (
                <div className="notif-empty">{t('adminPage.sidebar.noNotifications')}</div>
            )}
            {shown.map(n => (
                <button
                    key={n.id}
                    type="button"
                    className={`notif-item ${n.is_read ? 'notif-read' : 'notif-unread'}`}
                    onClick={() => onNotifClick(n)}
                >
                    <div className="notif-item-title">{n.title}</div>
                    <div className="notif-item-msg">{n.message}</div>
                    <div className="notif-item-meta">
                        {n.incident_id && <span className="notif-incident-id">#{n.incident_id.slice(0, 8)}</span>}
                        <span className="notif-time">
                            {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                        </span>
                    </div>
                </button>
            ))}
        </div>
    )
}

export default function AdminPortal() {
    const { dir, lang, t, toggleLang } = useI18n()
    const sections = getSections(t)
    const [section, setSection] = useState('dashboard')
    const [sidebarOpen, setSidebarOpen] = useState(false)
    const [showPwModal, setShowPwModal] = useState(false)
    const [pwForm, setPwForm] = useState({ current: '', new_pw: '', confirm: '' })
    const [pwError, setPwError] = useState('')
    const [pwSuccess, setPwSuccess] = useState('')
    const user = getStoredUser()

    // ── Notifications ──────────────────────────────────────────────
    const [notifications, setNotifications] = useState([])
    const [notifOpen, setNotifOpen] = useState(false)
    const notifRef = useRef(null)

    const unreadCount = notifications.filter(n => !n.is_read).length

    // When an admin notification indicates a missing machine, auto-open the
    // "Add Equipment" modal with the missing equipment ID prefilled.
    const [equipmentCreateNonce, setEquipmentCreateNonce] = useState(0)
    const [equipmentCreatePrefillId, setEquipmentCreatePrefillId] = useState('')

    const fetchNotifications = useCallback(async () => {
        try {
            const data = await getAdminNotifications()
            setNotifications(data.notifications || [])
        } catch {
            // non-critical — swallow silently
        }
    }, [])

    // Initial load via REST
    useEffect(() => {
        fetchNotifications()
    }, [fetchNotifications])

    // Live updates via WebSocket notification channel (no polling)
    useEffect(() => {
        const stored = getStoredUser()
        const companyId = stored?.company_id
        if (!companyId) return

        let ws = null
        let reconnectTimer = null
        let attempt = 0

        const getWsBase = () => {
            const loc = window.location
            const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:'
            return `${proto}//${loc.host}`
        }

        const connect = () => {
            const token = localStorage.getItem('decisio_token')
            if (!token) return
            const url = `${getWsBase()}/ws/notifications/${companyId}?token=${encodeURIComponent(token)}`
            ws = new WebSocket(url)

            ws.onopen = () => {
                attempt = 0
            }
            ws.onmessage = (evt) => {
                try {
                    const data = JSON.parse(evt.data)
                    if (data.type === 'admin_notification' && data.notification) {
                        setNotifications(prev => {
                            const existingIds = new Set(prev.map(n => n.id))
                            if (existingIds.has(data.notification.id)) return prev
                            return [data.notification, ...prev]
                        })
                    }
                    if (data.type === 'ping') {
                        ws.send(JSON.stringify({ type: 'pong' }))
                    }
                } catch {
                    // ignore parse errors
                }
            }
            ws.onclose = () => {
                ws = null
                const backoffMs = Math.min(30000, 2000 * Math.pow(2, attempt)) + Math.random() * 1000
                attempt += 1
                reconnectTimer = setTimeout(connect, backoffMs)
            }
            ws.onerror = () => {
                // handled by onclose
            }
        }

        connect()
        return () => {
            if (reconnectTimer) clearTimeout(reconnectTimer)
            if (ws) {
                ws.onclose = null
                ws.close()
            }
        }
    }, [])

    // Close dropdown when clicking outside
    useEffect(() => {
        function handleClick(e) {
            if (notifRef.current && !notifRef.current.contains(e.target)) {
                setNotifOpen(false)
            }
        }
        document.addEventListener('mousedown', handleClick)
        return () => document.removeEventListener('mousedown', handleClick)
    }, [])

    const handleNotifClick = async (notif) => {
        if (!notif.is_read) {
            try {
                await markNotificationRead(notif.id)
                setNotifications(prev => prev.map(n =>
                    n.id === notif.id ? { ...n, is_read: true } : n
                ))
            } catch { /* non-fatal */ }
        }
        setNotifOpen(false)

        // Route based on notification type
        if (notif.notification_type === 'MACHINE_NOT_REGISTERED') {
            const missingId = notif.payload?.missing_machine_id || ''
            setEquipmentCreatePrefillId(missingId)
            setEquipmentCreateNonce(n => n + 1)
            setSection('equipment')
            return
        }

        // Default: escalation configuration
        setSection('escalation')
    }

    const handleMarkAllRead = async () => {
        try {
            await markAllNotificationsRead()
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
        } catch { /* non-fatal */ }
    }

    const handlePwChange = async (e) => {
        e.preventDefault()
        setPwError(''); setPwSuccess('')
        if (pwForm.new_pw !== pwForm.confirm) { setPwError(t('adminPage.passwordModal.errors.noMatch')); return }
        if (pwForm.new_pw.length < 8) { setPwError(t('adminPage.passwordModal.errors.minLength')); return }
        try {
            await changePassword(pwForm.current, pwForm.new_pw)
            setPwSuccess(t('adminPage.passwordModal.success'))
            setPwForm({ current: '', new_pw: '', confirm: '' })
            setTimeout(() => setShowPwModal(false), 1500)
        } catch (err) { setPwError(err.message) }
    }

    return (
        <div className={`admin-layout ${sidebarOpen ? 'admin-sidebar-open' : ''}`} dir={dir}>
            <div className="admin-sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
            <header className="admin-mobile-header">
                <h2>⚙️ Decisio</h2>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <button type="button" className="admin-sidebar-toggle" onClick={() => setSidebarOpen(true)} aria-label={t('adminPage.sidebar.openMenu')}>☰</button>
                </div>
            </header>
            <aside className="admin-sidebar">
                <div className="sidebar-header">
                    <h2>⚙️ Decisio</h2>
                    <span className="sidebar-subtitle">{t('adminPage.sidebar.title')}</span>
                    {/* Bell icon — sits below the title in the sidebar header */}
                    <div ref={notifRef} className="notif-bell-wrapper">
                        <button
                            type="button"
                            className="notif-bell-btn"
                            onClick={() => setNotifOpen(o => !o)}
                            aria-label={`${t('adminPage.sidebar.notifications')}${unreadCount > 0 ? ` (${unreadCount} ${t('adminPage.sidebar.unread')})` : ''}`}
                        >
                            🔔 {t('adminPage.sidebar.notifications')}
                            {unreadCount > 0 && (
                                <span className="notif-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>
                            )}
                        </button>
                        {notifOpen && (
                            <NotificationDropdown
                                notifications={notifications}
                                onNotifClick={handleNotifClick}
                                onMarkAll={handleMarkAllRead}
                            />
                        )}
                    </div>
                </div>
                <nav className="sidebar-nav">
                    {sections.map(s => (
                        <button
                            key={s.id}
                            type="button"
                            className={`sidebar-item ${section === s.id ? 'active' : ''}`}
                            onClick={() => { setSection(s.id); setSidebarOpen(false); }}
                        >
                            <span className="sidebar-icon">{s.icon}</span>
                            <span className="sidebar-label">{s.label}</span>
                        </button>
                    ))}
                </nav>
                <div className="sidebar-footer">
                    <div className="sidebar-user">
                        <div className="sidebar-user-name">{user?.full_name || user?.username}</div>
                        <div className="sidebar-user-type">
                            <span className="user-type-badge" style={{ background: userTypeColor(user?.user_type) }}>
                                {user?.user_type}
                            </span>
                        </div>
                    </div>
                    <div className="sidebar-language-toggle">
                        <LanguageToggle lang={lang} onToggle={toggleLang} t={t} />
                    </div>
                    <div className="sidebar-actions">
                        <button className="sidebar-btn" onClick={() => setShowPwModal(true)}>🔑 {t('adminPage.sidebar.password')}</button>
                        <button className="sidebar-btn danger" onClick={logout}>{t('common.logout')}</button>
                    </div>
                </div>
            </aside>
            <main className="admin-main">
                {section === 'dashboard' && <DashboardSection />}
                {section === 'users' && <UsersSection />}
                {section === 'incidents' && <IncidentsSection />}
                {section === 'equipment' && (
                    <EquipmentSection
                        openCreateNonce={equipmentCreateNonce}
                        prefillId={equipmentCreatePrefillId}
                    />
                )}
                {section === 'safety' && <SafetySection />}
                {section === 'escalation' && <EscalationSection />}
                {section === 'live' && <LiveEscalationsSection />}
                {section === 'reports' && <ReportsSection />}
            </main>

            {showPwModal && (
                <Modal title={t('adminPage.passwordModal.title')} error={pwError} onClose={() => { setShowPwModal(false); setPwError(''); }}>
                    <form onSubmit={handlePwChange}>
                        <div className="form-group"><label>{t('adminPage.passwordModal.current')}</label><input type="password" value={pwForm.current} onChange={e => setPwForm({ ...pwForm, current: e.target.value })} required /></div>
                        <div className="form-group"><label>{t('adminPage.passwordModal.next')}</label><input type="password" value={pwForm.new_pw} onChange={e => setPwForm({ ...pwForm, new_pw: e.target.value })} required /></div>
                        <div className="form-group"><label>{t('adminPage.passwordModal.confirm')}</label><input type="password" value={pwForm.confirm} onChange={e => setPwForm({ ...pwForm, confirm: e.target.value })} required /></div>
                        {pwSuccess && <div style={{ color: '#10b981', margin: '8px 0', fontWeight: 600 }}>{pwSuccess}</div>}
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => setShowPwModal(false)}>{t('common.cancel')}</button>
                            <button type="submit" className="admin-btn primary">{t('adminPage.passwordModal.submit')}</button>
                        </div>
                    </form>
                </Modal>
            )}
        </div>
    )
}

// ── Reusable Modal ─────────────────────────────────────────────────

function Modal({ title, error, children, onClose }) {
    return (
        <div className="admin-modal-overlay" onClick={onClose}>
            <div className="admin-modal" onClick={e => e.stopPropagation()}>
                <h3>{title}</h3>
                {error && <div className="form-error" style={{ marginBottom: 16 }}>{error}</div>}
                {children}
            </div>
        </div>
    )
}

// ── Dashboard ──────────────────────────────────────────────────────

const DEFAULT_STATS = {
    total_incidents: 0,
    open_incidents: 0,
    closed_incidents: 0,
    total_users: 0,
    total_equipment: 0,
    total_safety_rules: 0,
    total_reports: 0,
    avg_mttd_seconds: null,
}

function DashboardSection() {
    const { t } = useI18n()
    const [stats, setStats] = useState(null)
    const [kpis, setKpis] = useState(null)
    const [loading, setLoading] = useState(true)
    const [loadError, setLoadError] = useState('')

    useEffect(() => {
        let isMounted = true;
        setLoadError('')
        Promise.all([
            getDashboard()
                .then((data) => {
                    if (isMounted) setStats(data || DEFAULT_STATS)
                })
                .catch((err) => {
                    if (isMounted) {
                        setStats(DEFAULT_STATS)
                        setLoadError(err?.message || t('adminPage.dashboard.failedToLoad'))
                    }
                }),
            getKpiStats().then(data => { if (isMounted) setKpis(data) }).catch(() => { if (isMounted) setKpis(null) }),
        ]).finally(() => { if (isMounted) setLoading(false) })

        return () => { isMounted = false; }
    }, [])

    if (loading && !stats) return <div className="admin-loading">{t('adminPage.dashboard.loading')}</div>

    const data = stats || DEFAULT_STATS
    const cards = [
        { label: t('adminPage.dashboard.cards.totalIncidents'), value: data.total_incidents, color: '#3b82f6', icon: '📋' },
        { label: t('adminPage.dashboard.cards.openIncidents'), value: data.open_incidents, color: '#f59e0b', icon: '⚡' },
        { label: t('adminPage.dashboard.cards.closed'), value: data.closed_incidents, color: '#10b981', icon: '✅' },
        { label: t('adminPage.dashboard.cards.users'), value: data.total_users, color: '#8b5cf6', icon: '👥' },
        { label: t('adminPage.dashboard.cards.equipment'), value: data.total_equipment, color: '#06b6d4', icon: '📦' },
        { label: t('adminPage.dashboard.cards.safetyRules'), value: data.total_safety_rules, color: '#ef4444', icon: '🛡️' },
        { label: t('adminPage.dashboard.cards.avgMttd'), value: data.avg_mttd_seconds != null ? `${data.avg_mttd_seconds}s` : '—', color: '#ec4899', icon: '⏱️' },
        { label: t('adminPage.dashboard.cards.reports'), value: data.total_reports, color: '#14b8a6', icon: '📊' },
    ]

    const fmtSec = (s) => s ? (s < 60 ? `${Math.round(s)}s` : `${(s / 60).toFixed(1)}m`) : '—'

    return (
        <div className="admin-section">
            <h2 className="admin-title">{t('adminPage.dashboard.title')}</h2>
            {loadError && (
                <div className="form-error" style={{ marginBottom: 16 }}>{loadError}</div>
            )}
            <div className="stats-grid">
                {cards.map((c, i) => (
                    <div key={i} className="stat-card" style={{ borderColor: c.color }}>
                        <div className="stat-icon">{c.icon}</div>
                        <div className="stat-value" style={{ color: c.color }}>{c.value}</div>
                        <div className="stat-label">{c.label}</div>
                    </div>
                ))}
            </div>

            {kpis && (
                <>
                    <h3 className="admin-subtitle" style={{ marginTop: 28 }}>{t('adminPage.dashboard.kpi.title')}</h3>
                    <div className="stats-grid">
                        <div className="stat-card" style={{ borderColor: '#ec4899' }}>
                            <div className="stat-icon">⏱️</div>
                            <div className="stat-value" style={{ color: '#ec4899' }}>{fmtSec(kpis.mttd?.average_seconds)}</div>
                            <div className="stat-label">{t('adminPage.dashboard.kpi.avgMttd')}</div>
                            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>{t('adminPage.dashboard.kpi.minMax', { min: fmtSec(kpis.mttd?.min_seconds), max: fmtSec(kpis.mttd?.max_seconds) })}</div>
                        </div>
                        <div className="stat-card" style={{ borderColor: '#f59e0b' }}>
                            <div className="stat-icon">📈</div>
                            <div className="stat-value" style={{ color: '#f59e0b' }}>{kpis.incidents?.escalation_rate_pct}%</div>
                            <div className="stat-label">{t('adminPage.dashboard.kpi.escalationRate')}</div>
                            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>{t('adminPage.dashboard.kpi.escalatedOfTotal', { escalated: kpis.incidents?.escalated, total: kpis.incidents?.total })}</div>
                        </div>
                        <div className="stat-card" style={{ borderColor: '#ef4444' }}>
                            <div className="stat-icon">⚠️</div>
                            <div className="stat-value" style={{ color: '#ef4444' }}>{kpis.process_failures?.detection_rate_pct}%</div>
                            <div className="stat-label">{t('adminPage.dashboard.kpi.processFailureRate')}</div>
                            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>{t('adminPage.dashboard.kpi.ofReports', { count: kpis.process_failures?.count, total: kpis.process_failures?.total_reports })}</div>
                        </div>
                        <div className="stat-card" style={{ borderColor: '#10b981' }}>
                            <div className="stat-icon">✅</div>
                            <div className="stat-value" style={{ color: '#10b981' }}>{kpis.incidents?.closed}</div>
                            <div className="stat-label">{t('adminPage.dashboard.kpi.resolved')}</div>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

// ── Users ──────────────────────────────────────────────────────────

// User type options: only Viewer (extra) + escalation levels added by admin (no Admin in list)
function getUserTypeOptions(escalationLevels, currentValue, t) {
    const options = [{ value: 'viewer', label: t('adminPage.users.viewer') }]
    escalationLevels.forEach(l => options.push({ value: `L${l.level}`, label: `L${l.level} – ${l.name}` }))
    // When editing, include current value so select displays correctly if it's not in the list (e.g. admin)
    if (currentValue && !options.some(o => o.value === currentValue)) {
        options.push({ value: currentValue, label: currentValue })
    }
    return options
}

function UsersSection() {
    const { t } = useI18n()
    const [users, setUsers] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [editUser, setEditUser] = useState(null)
    const [form, setForm] = useState({ username: '', email: '', password: '', full_name: '', user_type: 'viewer', contact_number: '' })
    const [error, setError] = useState('')
    const [escalationLevels, setEscalationLevels] = useState([])
    const [confirmAction, setConfirmAction] = useState(null)

    const loadUsers = () => {
        setLoading(true)
        listUsers().then(d => setUsers(d.users)).catch(console.error).finally(() => setLoading(false))
    }
    useEffect(() => { loadUsers() }, [])
    useEffect(() => {
        getEscalationMatrix().then(data => setEscalationLevels(data?.levels ?? [])).catch(() => setEscalationLevels([]))
    }, [])

    const userTypeOptions = getUserTypeOptions(escalationLevels, form.user_type, t)

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError('')

        const emailRegex = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/
        if (form.email && !emailRegex.test(form.email.trim())) {
            setError(t('adminPage.users.errors.invalidEmail'))
            return
        }
        if (form.password && form.password.length < 8) {
            setError(t('adminPage.users.errors.passwordMin'))
            return
        }

        try {
            if (editUser) {
                const update = {}
                if (form.email) update.email = form.email
                if (form.full_name !== undefined) update.full_name = form.full_name
                if (form.user_type) update.user_type = form.user_type
                if (form.password) update.password = form.password
                if (form.contact_number !== undefined) update.contact_number = form.contact_number
                await updateUser(editUser.id, update)
            } else {
                await createUser(form)
            }
            setShowForm(false)
            setEditUser(null)
            setForm({ username: '', email: '', password: '', full_name: '', user_type: 'viewer', contact_number: '' })
            loadUsers()
        } catch (err) { setError(err.message) }
    }

    const handleEdit = (u) => {
        setEditUser(u)
        setForm({ username: u.username, email: u.email, password: '', full_name: u.full_name, user_type: u.user_type, contact_number: u.contact_number || '' })
        setShowForm(true)
    }

    const handleDelete = async (u) => {
        setConfirmAction({ action: 'deactivate', user: u })
    }

    const handleActivate = async (u) => {
        setConfirmAction({ action: 'activate', user: u })
    }

    const confirmExecute = async () => {
        const { action, user } = confirmAction
        try {
            if (action === 'deactivate') {
                await deleteUser(user.id)
            } else if (action === 'activate') {
                await updateUser(user.id, { is_active: true })
            }
            loadUsers()
            setConfirmAction(null)
        } catch (err) {
            alert(err.message)
        }
    }

    return (
        <div className="admin-section">
            <div className="admin-header-row">
                <h2 className="admin-title">{t('adminPage.users.title')}</h2>
                <button className="admin-btn primary" onClick={() => { setShowForm(true); setEditUser(null); setForm({ username: '', email: '', password: '', full_name: '', user_type: 'viewer' }) }}>{t('adminPage.users.create')}</button>
            </div>

            {showForm && (
                <Modal title={editUser ? t('adminPage.users.modal.edit') : t('adminPage.users.modal.create')} error={error} onClose={() => { setShowForm(false); setError(''); }}>
                    <form onSubmit={handleSubmit}>
                        {!editUser && <div className="form-group"><label>{t('adminPage.users.fields.username')}</label><input value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} required /></div>}
                        <div className="form-group"><label>{t('adminPage.users.fields.email')}</label><input type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} required={!editUser} /></div>
                        <div className="form-group"><label>{t('adminPage.users.fields.fullName')}</label><input value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} /></div>
                        <div className="form-group"><label>Contact Number</label><input value={form.contact_number} onChange={e => setForm({ ...form, contact_number: e.target.value })} /></div>
                        <div className="form-group"><label>{t('adminPage.users.fields.password')} {editUser && `(${t('adminPage.users.fields.keepBlank')})`}</label><input type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} required={!editUser} /></div>
                        <div className="form-group"><label>{t('adminPage.users.fields.userType')}</label>
                            <select value={form.user_type} onChange={e => setForm({ ...form, user_type: e.target.value })}>
                                {userTypeOptions.map(({ value, label }) => (
                                    <option key={value} value={value}>{label}</option>
                                ))}
                            </select>
                        </div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => setShowForm(false)}>{t('common.cancel')}</button>
                            <button type="submit" className="admin-btn primary">{editUser ? t('common.save') : t('common.create')}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {confirmAction && (
                <Modal title={confirmAction.action === 'activate' ? t('adminPage.users.actions.activateUser') : t('adminPage.users.actions.deactivateUser')} onClose={() => setConfirmAction(null)}>
                    <div style={{ padding: '0 10px 10px 10px' }}>
                        <p style={{ margin: '0 0 20px 0', fontSize: '15px' }}>
                            {t('adminPage.users.confirm', { action: confirmAction.action === 'activate' ? t('common.activate') : t('common.deactivate'), username: confirmAction.user.username })}
                        </p>
                        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                            <button className="admin-btn" onClick={() => setConfirmAction(null)}>{t('common.cancel')}</button>
                            <button
                                className={`admin-btn ${confirmAction.action === 'activate' ? 'success' : 'danger'}`}
                                onClick={confirmExecute}
                                style={confirmAction.action === 'activate' ? { background: '#10b981', color: 'white', border: 'none' } : {}}
                            >
                                {confirmAction.action === 'activate' ? t('common.activate') : t('common.deactivate')}
                            </button>
                        </div>
                    </div>
                </Modal>
            )}

            {loading ? <div className="admin-loading">{t('adminPage.users.loading')}</div> : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>{t('adminPage.users.table.username')}</th><th>{t('adminPage.users.table.fullName')}</th><th>{t('adminPage.users.table.email')}</th><th>Contact Number</th><th>{t('adminPage.users.table.type')}</th><th>{t('adminPage.users.table.status')}</th><th>{t('adminPage.users.table.created')}</th><th>{t('adminPage.users.table.actions')}</th></tr></thead>
                        <tbody>
                            {users.map(u => (
                                <tr key={u.id} className={!u.is_active ? 'inactive-row' : ''}>
                                    <td className="td-bold">{u.username}</td>
                                    <td>{u.full_name || '—'}</td>
                                    <td>{u.email}</td>
                                    <td>{u.contact_number || '—'}</td>
                                    <td><span className="user-type-badge" style={{ background: userTypeColor(u.user_type) }}>{u.user_type}</span></td>
                                    <td><span className={`status-badge ${u.is_active ? 'active' : 'inactive'}`}>{u.is_active ? t('common.active') : t('common.inactive')}</span></td>
                                    <td>{new Date(u.created_at).toLocaleDateString()}</td>
                                    <td>
                                        <button className="admin-btn-sm" onClick={() => handleEdit(u)}>{t('common.edit')}</button>
                                        {u.is_active ? (
                                            <button className="admin-btn-sm danger" style={{ marginInlineStart: '6px' }} onClick={() => handleDelete(u)}>{t('common.deactivate')}</button>
                                        ) : (
                                            <button className="admin-btn-sm" style={{ marginInlineStart: '6px' }} onClick={() => handleActivate(u)}>{t('common.activate')}</button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

// ── Incidents ──────────────────────────────────────────────────────

function IncidentsSection() {
    const { t } = useI18n()
    const [incidents, setIncidents] = useState([])
    const [loading, setLoading] = useState(true)
    const [filterEscalatedOnly, setFilterEscalatedOnly] = useState(false)
    const [selectedId, setSelectedId] = useState(null)
    const [detail, setDetail] = useState(null)
    const [detailLoading, setDetailLoading] = useState(false)

    const loadList = () => {
        setLoading(true)
        listIncidents().then(d => setIncidents(d.incidents || [])).catch(console.error).finally(() => setLoading(false))
    }
    useEffect(() => { loadList() }, [])

    useEffect(() => {
        if (!selectedId) { setDetail(null); return }
        setDetailLoading(true)
        getIncident(selectedId)
            .then(setDetail)
            .catch(() => setDetail(null))
            .finally(() => setDetailLoading(false))
    }, [selectedId])

    const statusColor = (s) => {
        if (s === 'CLOSED') return '#10b981'
        if (s === 'ESCALATED') return '#ef4444'
        if (s === 'OPEN' || s === 'DIAGNOSIS_LOOP') return '#f59e0b'
        return '#6b7280'
    }
    const statusLabel = (s) => {
        if (s === 'CLOSED') return t('adminPage.incidents.status.closed')
        if (s === 'ESCALATED') return t('adminPage.incidents.status.escalated')
        if (s === 'OPEN') return t('adminPage.incidents.status.open')
        if (s === 'DIAGNOSIS_LOOP') return t('adminPage.incidents.status.diagnosis')
        return s
    }

    const filtered = filterEscalatedOnly ? incidents.filter(i => i.status === 'ESCALATED') : incidents

    return (
        <div className="admin-section">
            <div className="admin-header-row" style={{ flexWrap: 'wrap', gap: 12 }}>
                <h2 className="admin-title">{t('adminPage.incidents.title')}</h2>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-dim)' }}>
                    <input
                        type="checkbox"
                        checked={filterEscalatedOnly}
                        onChange={e => setFilterEscalatedOnly(e.target.checked)}
                    />
                    {t('adminPage.incidents.escalatedOnly')}
                </label>
            </div>
            {loading ? <div className="admin-loading">{t('common.loading')}</div> : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>{t('adminPage.incidents.table.id')}</th><th>{t('adminPage.incidents.table.summary')}</th><th>{t('adminPage.incidents.table.asset')}</th><th>{t('adminPage.incidents.table.severity')}</th><th>{t('adminPage.incidents.table.status')}</th><th>{t('adminPage.incidents.table.confidence')}</th><th>{t('adminPage.incidents.table.risk')}</th><th></th></tr></thead>
                        <tbody>
                            {filtered.length === 0 ? (
                                <tr><td colSpan={8} className="td-empty">{filterEscalatedOnly ? t('adminPage.incidents.empty.escalatedOnly') : t('adminPage.incidents.empty.none')}</td></tr>
                            ) : filtered.map((inc, i) => (
                                <tr
                                    key={i}
                                    onClick={() => setSelectedId(inc.incident_id)}
                                    style={{ cursor: 'pointer' }}
                                    className={selectedId === inc.incident_id ? 'admin-table-row-selected' : ''}
                                >
                                    <td className="td-mono">{inc.incident_id?.slice(0, 12)}...</td>
                                    <td>{inc.summary?.slice(0, 50) || '—'}</td>
                                    <td className="td-bold">{inc.asset_id || '—'}</td>
                                    <td><span className={`badge badge-${inc.severity || 'medium'}`}>{inc.severity}</span></td>
                                    <td><span style={{ color: statusColor(inc.status), fontWeight: 600 }}>{statusLabel(inc.status)}</span></td>
                                    <td>{Math.round((inc.confidence || 0) * 100)}%</td>
                                    <td>{inc.risk_score?.toFixed(1) || '—'}</td>
                                    <td><span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{t('adminPage.incidents.view')}</span></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {selectedId && (
                <Modal title={t('adminPage.incidents.details.title')} onClose={() => setSelectedId(null)}>
                    {detailLoading ? (
                        <div className="admin-loading">{t('adminPage.incidents.details.loading')}</div>
                    ) : !detail ? (
                        <div className="admin-loading">{t('adminPage.incidents.details.loadFailed')}</div>
                    ) : (
                        <IncidentDetailContent detail={detail} onClose={() => setSelectedId(null)} />
                    )}
                </Modal>
            )}
        </div>
    )
}

function IncidentDetailContent({ detail, onClose }) {
    const { t } = useI18n()
    const card = detail.incident_card || {}
    const esc = detail.escalation || {}
    const brief = detail.decision_brief || {}
    const isEscalated = detail.status === 'ESCALATED' || detail.escalation_triggered

    return (
        <div style={{ maxHeight: '80vh', overflowY: 'auto' }}>
            {/* Incident summary */}
            <div style={{ marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontSize: 14, color: 'var(--text-bright)', fontWeight: 600, marginBottom: 8 }}>{card.normalized_summary || '—'}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 24px', fontSize: 12, color: 'var(--text-dim)' }}>
                    <span><strong>{t('adminPage.incidents.table.id')}:</strong> {detail.incident_id}</span>
                    <span><strong>{t('adminPage.incidents.table.asset')}:</strong> {card.asset_id || '—'}</span>
                    <span><strong>{t('adminPage.incidents.table.severity')}:</strong> <span className={`badge badge-${card.severity || 'medium'}`}>{card.severity}</span></span>
                    <span><strong>{t('adminPage.incidents.table.status')}:</strong> <span style={{ color: isEscalated ? '#ef4444' : '#10b981', fontWeight: 600 }}>{detail.status}</span></span>
                    <span><strong>{t('adminPage.incidents.table.risk')}:</strong> {detail.risk_score?.toFixed(1) ?? '—'}</span>
                    <span><strong>{t('adminPage.incidents.table.confidence')}:</strong> {Math.round((detail.confidence || 0) * 100)}%</span>
                    {detail.failed_attempts > 0 && <span><strong>{t('adminPage.incidents.details.failedAttempts')}:</strong> {detail.failed_attempts}</span>}
                </div>
            </div>

            {/* Escalation detail — only when escalated */}
            {isEscalated && (
                <div style={{
                    marginBottom: 20, padding: 16, background: 'rgba(239,68,68,0.08)', border: '1px solid #ef4444',
                    borderRadius: 8,
                }}>
                    <h3 style={{ color: '#ef4444', fontSize: 14, fontWeight: 700, marginBottom: 12 }}>🔴 {t('adminPage.incidents.details.escalationDetail')}</h3>

                    {detail.escalation_reasons?.length > 0 && (
                        <div style={{ marginBottom: 12 }}>
                            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 4 }}>{t('adminPage.incidents.details.reasons')}</div>
                            <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 13 }}>
                                {detail.escalation_reasons.map((r, i) => <li key={i}>{r}</li>)}
                            </ul>
                        </div>
                    )}

                    {(esc.escalation_level != null || esc.escalation_level_name) && (
                        <div style={{ marginBottom: 8, fontSize: 13 }}>
                            <strong>{t('adminPage.incidents.details.level')}:</strong> {esc.escalation_level} — {esc.escalation_level_name}
                        </div>
                    )}
                    {esc.escalation_summary && <div style={{ marginBottom: 8, fontSize: 13 }}>{esc.escalation_summary}</div>}
                    {esc.urgency && <div style={{ marginBottom: 8, fontSize: 12, color: '#f59e0b' }}>{t('adminPage.incidents.details.urgency')}: {esc.urgency}</div>}
                    {esc.recommended_expertise && <div style={{ marginBottom: 8, fontSize: 12 }}>{t('adminPage.incidents.details.recommendedExpertise')}: {esc.recommended_expertise}</div>}

                    {esc.what_was_tried?.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 4 }}>{t('adminPage.incidents.details.whatWasTried')}</div>
                            <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 12 }}>{esc.what_was_tried.map((w, i) => <li key={i}>{w}</li>)}</ul>
                        </div>
                    )}
                    {esc.safety_warnings?.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                            <div style={{ fontSize: 11, color: '#ef4444', marginBottom: 4 }}>{t('adminPage.incidents.details.safetyWarnings')}</div>
                            <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 12 }}>{esc.safety_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
                        </div>
                    )}

                    {detail.escalation?.session_id && (
                        <div style={{ marginTop: 12, padding: 10, background: 'var(--surface)', borderRadius: 6, fontSize: 12 }}>
                            <strong>💬 {t('adminPage.incidents.details.escalationChat')}</strong> — {t('adminPage.incidents.details.sessionId')}: <code style={{ fontSize: 11 }}>{detail.escalation.session_id}</code>
                            <div style={{ color: 'var(--text-dim)', marginTop: 6 }}>{t('adminPage.incidents.details.supervisorHelp')}</div>
                        </div>
                    )}
                </div>
            )}

            {/* Decision brief summary */}
            {brief.risk_summary && (
                <div style={{ marginBottom: 16, padding: 12, border: '1px solid var(--border)', borderRadius: 8 }}>
                    <h3 style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>{t('adminPage.incidents.details.decisionBrief')}</h3>
                    <div style={{ fontSize: 13, marginBottom: 8 }}>{brief.risk_summary}</div>
                    {brief.options?.length > 0 && (
                        <div style={{ fontSize: 12 }}>
                            <span style={{ color: 'var(--text-dim)' }}>{t('adminPage.incidents.details.options')}: </span>
                            {brief.options.map((o, i) => <span key={i}>{o.title}{i < brief.options.length - 1 ? '; ' : ''}</span>)}
                        </div>
                    )}
                    {brief.safety_constraints?.length > 0 && (
                        <div style={{ marginTop: 8, fontSize: 12, color: '#f59e0b' }}>⚠️ {brief.safety_constraints.join(' • ')}</div>
                    )}
                </div>
            )}

            <div style={{ textAlign: 'right' }}>
                <button type="button" className="admin-btn" onClick={onClose}>{t('common.close')}</button>
            </div>
        </div>
    )
}

// ── Equipment (CRUD) ───────────────────────────────────────────────

function EquipmentSection({ openCreateNonce, prefillId }) {
    const { t } = useI18n()
    const [equipment, setEquipment] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [editItem, setEditItem] = useState(null)
    const [form, setForm] = useState({ id: '', name: '', equipment_type: 'rotating', process_line: 'Line A', criticality: 'medium', description: '', upstream_id: '', downstream_id: '' })
    const [error, setError] = useState('')
    const [confirmDelete, setConfirmDelete] = useState(null) // equipment row
    const [manualStatuses, setManualStatuses] = useState({})
    const [showManualModal, setShowManualModal] = useState(false)
    const [manualTarget, setManualTarget] = useState(null)
    const [uploadFile, setUploadFile] = useState(null)
    const [uploading, setUploading] = useState(false)
    const [uploadProgress, setUploadProgress] = useState('')

    const load = () => {
        setLoading(true);
        listEquipment().then(async d => {
            const eqs = d.equipment || [];
            setEquipment(eqs);
            const statuses = { ...manualStatuses };
            await Promise.all(eqs.map(async (eq) => {
                try {
                    const st = await getEquipmentManualStatus(eq.id);
                    statuses[eq.id] = st.has_manual;
                } catch (e) { }
            }));
            setManualStatuses(statuses);
        }).catch(console.error).finally(() => setLoading(false))
    }
    useEffect(() => { load() }, [])

    const openCreate = (prefill = '') => {
        setEditItem(null)
        setForm({
            id: prefill || '',
            name: prefill || '',
            equipment_type: 'rotating',
            process_line: 'Line A',
            criticality: 'medium',
            description: '',
            upstream_id: '',
            downstream_id: '',
        })
        setShowForm(true)
        setError('')
    }

    // Auto-open "Add Equipment" when a notification requests it.
    useEffect(() => {
        if (openCreateNonce > 0) {
            openCreate(prefillId || '')
        }
    }, [openCreateNonce, prefillId])

    const openEdit = (eq) => {
        setEditItem(eq)
        setForm({ id: eq.id, name: eq.name, equipment_type: eq.type, process_line: eq.process_line || '', criticality: eq.criticality, description: eq.description || '', upstream_id: eq.upstream_id || '', downstream_id: eq.downstream_id || '' })
        setShowForm(true)
        setError('')
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError('')
        try {
            if (editItem) {
                await updateEquipment(editItem.id, {
                    name: form.name, equipment_type: form.equipment_type, process_line: form.process_line,
                    criticality: form.criticality, description: form.description,
                    upstream_id: form.upstream_id || null, downstream_id: form.downstream_id || null,
                })
            } else {
                await createEquipment(form)
            }
            setShowForm(false)
            load()
        } catch (err) { setError(err.message) }
    }

    const handleDelete = async (eq) => {
        setConfirmDelete(eq)
    }

    const openManualModal = (eq) => {
        setManualTarget(eq);
        setShowManualModal(true);
        setUploadFile(null);
        setError('');
        setUploadProgress('');
    }

    const handleManualUpload = async (e) => {
        e.preventDefault();
        if (!uploadFile) return;
        setError('');
        setUploading(true);
        setUploadProgress('Uploading and processing...');
        try {
            await uploadEquipmentManual(manualTarget.id, uploadFile);
            setShowManualModal(false);
            setUploadFile(null);
            load();
        } catch (err) {
            setError(err.message);
        } finally {
            setUploading(false);
            setUploadProgress('');
        }
    }

    const handleManualDelete = async () => {
        if (!window.confirm(`Delete manual for ${manualTarget.name}?`)) return;
        setError('');
        setUploading(true);
        try {
            await deleteEquipmentManual(manualTarget.id);
            setShowManualModal(false);
            load();
        } catch (err) {
            setError(err.message);
        } finally {
            setUploading(false);
        }
    }

    const critColor = (c) => c === 'critical' ? '#ef4444' : c === 'high' ? '#f59e0b' : c === 'medium' ? '#3b82f6' : '#6b7280'

    return (
        <div className="admin-section">
            <div className="admin-header-row">
                <h2 className="admin-title">{t('adminPage.equipment.title')}</h2>
                <button className="admin-btn primary" onClick={() => openCreate('')}>{t('adminPage.equipment.add')}</button>
            </div>

            {showForm && (
                <Modal title={editItem ? t('adminPage.equipment.editTitle', { id: editItem.id }) : t('adminPage.equipment.addTitle')} error={error} onClose={() => { setShowForm(false); setError(''); }}>
                    <form onSubmit={handleSubmit}>
                        {!editItem && <div className="form-group"><label>{t('adminPage.equipment.fields.id')}</label><input value={form.id} onChange={e => setForm({ ...form, id: e.target.value })} placeholder="e.g. CMP-02" required /></div>}
                        <div className="form-group"><label>{t('adminPage.equipment.fields.name')}</label><input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required /></div>
                        <div className="form-group"><label>{t('adminPage.equipment.fields.type')}</label>
                            <select value={form.equipment_type} onChange={e => setForm({ ...form, equipment_type: e.target.value })}>
                                <option value="rotating">{t('adminPage.equipment.types.rotating')}</option><option value="pressure_vessel">{t('adminPage.equipment.types.pressure_vessel')}</option>
                                <option value="heat_exchange">{t('adminPage.equipment.types.heat_exchange')}</option><option value="storage">{t('adminPage.equipment.types.storage')}</option>
                                <option value="piping">{t('adminPage.equipment.types.piping')}</option><option value="electrical">{t('adminPage.equipment.types.electrical')}</option>
                            </select>
                        </div>
                        <div className="form-row">
                            <div className="form-group"><label>{t('adminPage.equipment.fields.line')}</label><input value={form.process_line} onChange={e => setForm({ ...form, process_line: e.target.value })} /></div>
                            <div className="form-group"><label>{t('adminPage.equipment.fields.criticality')}</label>
                                <select value={form.criticality} onChange={e => setForm({ ...form, criticality: e.target.value })}>
                                    <option value="critical">{t('adminPage.equipment.criticality.critical')}</option><option value="high">{t('adminPage.equipment.criticality.high')}</option>
                                    <option value="medium">{t('adminPage.equipment.criticality.medium')}</option><option value="low">{t('adminPage.equipment.criticality.low')}</option>
                                </select>
                            </div>
                        </div>
                        <div className="form-group"><label>{t('adminPage.equipment.fields.description')}</label><input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></div>
                        <div className="form-row">
                            <div className="form-group"><label>{t('adminPage.equipment.fields.upstream')}</label><input value={form.upstream_id} onChange={e => setForm({ ...form, upstream_id: e.target.value })} placeholder="e.g. CMP-01" /></div>
                            <div className="form-group"><label>{t('adminPage.equipment.fields.downstream')}</label><input value={form.downstream_id} onChange={e => setForm({ ...form, downstream_id: e.target.value })} placeholder="e.g. CON-01" /></div>
                        </div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => setShowForm(false)}>{t('common.cancel')}</button>
                            <button type="submit" className="admin-btn primary">{editItem ? t('common.save') : t('common.add')}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {confirmDelete && (
                <Modal title={t('common.confirm')} error={error} onClose={() => { setConfirmDelete(null); setError(''); }}>
                    <div style={{ marginBottom: 14 }}>
                        {t('adminPage.equipment.confirmDelete', { id: confirmDelete.id })}
                    </div>
                    <div className="form-actions">
                        <button type="button" className="admin-btn" onClick={() => setConfirmDelete(null)}>{t('common.cancel')}</button>
                        <button
                            type="button"
                            className="admin-btn danger"
                            onClick={async () => {
                                try {
                                    await deleteEquipment(confirmDelete.id)
                                    setConfirmDelete(null)
                                    load()
                                } catch (err) {
                                    setError(err?.message || t('common.error'))
                                }
                            }}
                        >
                            {t('common.delete')}
                        </button>
                    </div>
                </Modal>
            )}

            {showManualModal && manualTarget && (
                <Modal title={`Manual: ${manualTarget.name}`} error={error} onClose={() => { if (!uploading) setShowManualModal(false); setError(''); }}>
                    <form onSubmit={handleManualUpload}>
                        <div className="form-group">
                            <label>File (.pdf, .docx, .txt)</label>
                            <input type="file" accept=".pdf,.docx,.txt" onChange={e => setUploadFile(e.target.files[0])} disabled={uploading} />
                        </div>
                        {uploadProgress && <div style={{ marginBottom: 10, color: '#3b82f6', fontSize: '0.9rem' }}>{uploadProgress}</div>}

                        <div className="form-actions" style={{ justifyContent: manualStatuses[manualTarget.id] ? 'space-between' : 'flex-end', marginTop: 24 }}>
                            {manualStatuses[manualTarget.id] && (
                                <button type="button" className="admin-btn danger" onClick={handleManualDelete} disabled={uploading}>Delete Manual</button>
                            )}
                            <div>
                                <button type="button" className="admin-btn" style={{ marginRight: 8 }} onClick={() => { if (!uploading) setShowManualModal(false); }} disabled={uploading}>{t('common.cancel')}</button>
                                <button type="submit" className="admin-btn primary" disabled={!uploadFile || uploading}>Upload</button>
                            </div>
                        </div>
                    </form>
                </Modal>
            )}

            {loading ? <div className="admin-loading">{t('common.loading')}</div> : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>{t('adminPage.equipment.table.id')}</th><th>{t('adminPage.equipment.table.name')}</th><th>{t('adminPage.equipment.table.type')}</th><th>{t('adminPage.equipment.table.line')}</th><th>{t('adminPage.equipment.table.criticality')}</th><th>{t('adminPage.equipment.table.upstream')}</th><th>{t('adminPage.equipment.table.downstream')}</th><th>Manual</th><th>{t('adminPage.equipment.table.actions')}</th></tr></thead>
                        <tbody>
                            {equipment.map(eq => (
                                <tr key={eq.id}>
                                    <td className="td-bold">{eq.id}</td>
                                    <td>{eq.name}</td>
                                    <td className="td-mono">{eq.type}</td>
                                    <td>{eq.process_line}</td>
                                    <td><span style={{ color: critColor(eq.criticality), fontWeight: 600 }}>{eq.criticality}</span></td>
                                    <td>{eq.upstream_id || '—'}</td>
                                    <td>{eq.downstream_id || '—'}</td>
                                    <td>{manualStatuses[eq.id] ? <span style={{ color: '#10b981', fontWeight: 600, fontSize: '0.85rem', padding: '2px 6px', backgroundColor: '#ecfdf5', borderRadius: 4 }}>Uploaded</span> : <span style={{ color: '#9ca3af', fontSize: '0.85rem' }}>None</span>}</td>
                                    <td>
                                        <button className="admin-btn-sm" onClick={() => openManualModal(eq)}>Manual</button>
                                        <button className="admin-btn-sm" onClick={() => openEdit(eq)}>{t('common.edit')}</button>
                                        <button className="admin-btn-sm danger" onClick={() => handleDelete(eq)}>{t('common.delete')}</button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

// ── Safety Rules (CRUD) ────────────────────────────────────────────

function SafetySection() {
    const { t } = useI18n()
    const [rules, setRules] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [editItem, setEditItem] = useState(null)
    const [form, setForm] = useState({ type: '', rule: '' })
    const [error, setError] = useState('')
    const [confirmDelete, setConfirmDelete] = useState(null) // rule row

    const load = () => { setLoading(true); listSafetyRules().then(d => setRules(d.rules || [])).catch(console.error).finally(() => setLoading(false)) }
    useEffect(() => { load() }, [])

    const openCreate = () => {
        setEditItem(null)
        setForm({ type: 'general', rule: '' })
        setShowForm(true)
        setError('')
    }

    const safetyTypeOptions = ['general', 'rotating', 'pressure_vessel', 'heat_exchange', 'storage', 'piping', 'electrical']
    const openEdit = (r) => {
        setEditItem(r)
        const type = safetyTypeOptions.includes(r.equipment_type) ? r.equipment_type : 'general'
        setForm({ type, rule: r.rule_text || '' })
        setShowForm(true)
        setError('')
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError('')
        const payload = { equipment_type: form.type, rule_text: form.rule, severity_class: 'constraint', is_general: false, sort_order: 100 }
        try {
            if (editItem) {
                await updateSafetyRule(editItem.id, payload)
            } else {
                await createSafetyRule(payload)
            }
            setShowForm(false)
            load()
        } catch (err) { setError(err.message) }
    }

    const handleDelete = async (r) => {
        setConfirmDelete(r)
    }

    return (
        <div className="admin-section">
            <div className="admin-header-row">
                <h2 className="admin-title">{t('adminPage.safety.title')}</h2>
                <button className="admin-btn primary" onClick={openCreate}>{t('adminPage.safety.addRule')}</button>
            </div>

            {showForm && (
                <Modal title={editItem ? t('adminPage.safety.editRule', { id: editItem.id }) : t('adminPage.safety.addRuleTitle')} error={error} onClose={() => { setShowForm(false); setError(''); }}>
                    <form onSubmit={handleSubmit}>
                        <div className="form-group"><label>{t('adminPage.safety.table.type')}</label>
                            <select value={form.type} onChange={e => setForm({ ...form, type: e.target.value })} required>
                                {safetyTypeOptions.map(t => (
                                    <option key={t} value={t}>{t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</option>
                                ))}
                            </select>
                        </div>
                        <div className="form-group"><label>{t('adminPage.safety.table.rule')}</label><input value={form.rule} onChange={e => setForm({ ...form, rule: e.target.value })} placeholder={t('adminPage.safety.rulePlaceholder')} required /></div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => setShowForm(false)}>{t('common.cancel')}</button>
                            <button type="submit" className="admin-btn primary">{editItem ? t('common.save') : t('common.add')}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {confirmDelete && (
                <Modal title={t('common.confirm')} error={error} onClose={() => { setConfirmDelete(null); setError(''); }}>
                    <div style={{ marginBottom: 14 }}>
                        {t('adminPage.safety.confirmDelete', { id: confirmDelete.id })}
                    </div>
                    <div className="form-actions">
                        <button type="button" className="admin-btn" onClick={() => setConfirmDelete(null)}>{t('common.cancel')}</button>
                        <button
                            type="button"
                            className="admin-btn danger"
                            onClick={async () => {
                                try {
                                    await deleteSafetyRule(confirmDelete.id)
                                    setConfirmDelete(null)
                                    load()
                                } catch (err) {
                                    setError(err?.message || t('common.error'))
                                }
                            }}
                        >
                            {t('common.delete')}
                        </button>
                    </div>
                </Modal>
            )}

            {loading ? <div className="admin-loading">{t('common.loading')}</div> : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>{t('adminPage.safety.table.type')}</th><th>{t('adminPage.safety.table.rule')}</th><th>{t('adminPage.safety.table.actions')}</th></tr></thead>
                        <tbody>
                            {rules.map(r => (
                                <tr key={r.id}>
                                    <td className="td-bold">{r.equipment_type}</td>
                                    <td>{r.rule_text}</td>
                                    <td>
                                        <button className="admin-btn-sm" onClick={() => openEdit(r)}>{t('common.edit')}</button>
                                        <button className="admin-btn-sm danger" onClick={() => handleDelete(r)}>{t('common.delete')}</button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

// ── Escalation (CRUD) ──────────────────────────────────────────────

function EscalationSection() {
    const { t } = useI18n()
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(true)
    const [showLevelForm, setShowLevelForm] = useState(false)
    const [editLevel, setEditLevel] = useState(null)
    const [levelForm, setLevelForm] = useState({ level: 1, name: '', description: '' })
    const [showRuleForm, setShowRuleForm] = useState(false)
    const [editRule, setEditRule] = useState(null)
    const [ruleForm, setRuleForm] = useState({ condition: '', confidence_min: 0, confidence_max: 1, safety_impact: 'low', escalation_level: 1, description: '', sort_order: 100 })
    const [error, setError] = useState('')
    const [confirmDelete, setConfirmDelete] = useState(null) // { kind: 'level'|'rule', item }

    const load = () => { setLoading(true); getEscalationMatrix().then(setData).catch(console.error).finally(() => setLoading(false)) }
    useEffect(() => { load() }, [])

    // Level handlers
    const openCreateLevel = () => { setEditLevel(null); setLevelForm({ level: (data?.levels?.length || 0) + 1, name: '', description: '' }); setShowLevelForm(true); setError('') }
    const openEditLevel = (l) => { setEditLevel(l); setLevelForm({ level: l.level, name: l.name, description: l.description || '' }); setShowLevelForm(true); setError('') }
    const submitLevel = async (e) => {
        e.preventDefault(); setError('')
        try {
            if (editLevel) { await updateEscalationLevel(editLevel.level, levelForm) }
            else { await createEscalationLevel(levelForm) }
            setShowLevelForm(false); load()
        } catch (err) { setError(err.message) }
    }
    const removeLevel = async (l) => {
        setConfirmDelete({ kind: 'level', item: l })
    }

    // Rule handlers
    const openCreateRule = () => { setEditRule(null); setRuleForm({ condition: '', confidence_min: 0, confidence_max: 1, safety_impact: 'low', escalation_level: 1, description: '', sort_order: 100 }); setShowRuleForm(true); setError('') }
    const openEditRule = (r) => { setEditRule(r); setRuleForm({ condition: r.condition, confidence_min: r.confidence_min, confidence_max: r.confidence_max, safety_impact: r.safety_impact, escalation_level: r.escalation_level, description: r.description || '', sort_order: r.sort_order || 100 }); setShowRuleForm(true); setError('') }
    const submitRule = async (e) => {
        e.preventDefault(); setError('')
        try {
            if (editRule) { await updateEscalationRule(editRule.id, ruleForm) }
            else { await createEscalationRule(ruleForm) }
            setShowRuleForm(false); load()
        } catch (err) { setError(err.message) }
    }
    const removeRule = async (r) => {
        setConfirmDelete({ kind: 'rule', item: r })
    }

    const impactColor = (i) => i === 'high' ? '#ef4444' : i === 'medium' ? '#f59e0b' : '#10b981'

    const levels = data?.levels || []
    const rules = data?.rules || []

    return (
        <div className="admin-section">
            <h2 className="admin-title">{t('adminPage.escalation.title')}</h2>
            {confirmDelete && (
                <Modal title={t('common.confirm')} error={error} onClose={() => { setConfirmDelete(null); setError(''); }}>
                    <div style={{ marginBottom: 14 }}>
                        {confirmDelete.kind === 'level'
                            ? t('adminPage.escalation.confirmDeleteLevel', { level: confirmDelete.item.level })
                            : t('adminPage.escalation.confirmDeleteRule', { id: confirmDelete.item.id })}
                    </div>
                    <div className="form-actions">
                        <button type="button" className="admin-btn" onClick={() => setConfirmDelete(null)}>{t('common.cancel')}</button>
                        <button
                            type="button"
                            className="admin-btn danger"
                            onClick={async () => {
                                try {
                                    if (confirmDelete.kind === 'level') {
                                        await deleteEscalationLevel(confirmDelete.item.level)
                                    } else {
                                        await deleteEscalationRule(confirmDelete.item.id)
                                    }
                                    setConfirmDelete(null)
                                    load()
                                } catch (err) {
                                    setError(err?.message || t('common.error'))
                                }
                            }}
                        >
                            {t('common.delete')}
                        </button>
                    </div>
                </Modal>
            )}
            {loading ? <div className="admin-loading">{t('common.loading')}</div> : (
                <>
                    {/* Levels */}
                    <div className="admin-header-row" style={{ marginBottom: 12 }}>
                        <h3 className="admin-subtitle">{t('adminPage.escalation.levels')}</h3>
                        <button className="admin-btn primary" onClick={openCreateLevel}>{t('adminPage.escalation.addLevel')}</button>
                    </div>

                    {showLevelForm && (
                        <Modal title={editLevel ? t('adminPage.escalation.editLevel', { level: editLevel.level }) : t('adminPage.escalation.addLevelTitle')} error={error} onClose={() => { setShowLevelForm(false); setError(''); }}>
                            <form onSubmit={submitLevel}>
                                {!editLevel && <div className="form-group"><label>{t('adminPage.escalation.levelNumber')}</label><input type="number" value={levelForm.level} onChange={e => setLevelForm({ ...levelForm, level: parseInt(e.target.value) })} required /></div>}
                                <div className="form-group"><label>{t('common.name')}</label><input value={levelForm.name} onChange={e => setLevelForm({ ...levelForm, name: e.target.value })} placeholder={t('adminPage.escalation.levelNamePlaceholder')} required /></div>
                                <div className="form-group"><label>{t('common.description')}</label><input value={levelForm.description} onChange={e => setLevelForm({ ...levelForm, description: e.target.value })} /></div>
                                <div className="form-actions">
                                    <button type="button" className="admin-btn" onClick={() => setShowLevelForm(false)}>{t('common.cancel')}</button>
                                    <button type="submit" className="admin-btn primary">{editLevel ? t('common.save') : t('common.add')}</button>
                                </div>
                            </form>
                        </Modal>
                    )}

                    {levels.length === 0 ? (
                        <div className="admin-loading">{t('adminPage.escalation.emptyLevels')}</div>
                    ) : (
                        <div className="escalation-levels">
                            {levels.map(l => (
                                <div key={l.level} className="escalation-level-card">
                                    <div className="esc-level-num">L{l.level}</div>
                                    <div className="esc-level-name">{l.name}</div>
                                    <div className="esc-level-desc">{l.description}</div>
                                    <div className="esc-level-actions">
                                        <button className="admin-btn-sm" onClick={() => openEditLevel(l)}>{t('common.edit')}</button>
                                        <button className="admin-btn-sm danger" onClick={() => removeLevel(l)}>{t('common.delete')}</button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Rules */}
                    <div className="admin-header-row" style={{ marginTop: 24, marginBottom: 12 }}>
                        <h3 className="admin-subtitle">{t('adminPage.escalation.rules')}</h3>
                        <button className="admin-btn primary" onClick={openCreateRule}>{t('adminPage.escalation.addRule')}</button>
                    </div>

                    {showRuleForm && (
                        <Modal title={editRule ? t('adminPage.escalation.editRule', { id: editRule.id }) : t('adminPage.escalation.addRuleTitle')} error={error} onClose={() => { setShowRuleForm(false); setError(''); }}>
                            <form onSubmit={submitRule}>
                                <div className="form-group"><label>{t('adminPage.escalation.table.condition')}</label><input value={ruleForm.condition} onChange={e => setRuleForm({ ...ruleForm, condition: e.target.value })} placeholder={t('adminPage.escalation.conditionPlaceholder')} required /></div>
                                <div className="form-row">
                                    <div className="form-group"><label>{t('adminPage.escalation.confidenceMin')}</label><input type="number" step="0.01" min="0" max="1" value={ruleForm.confidence_min} onChange={e => setRuleForm({ ...ruleForm, confidence_min: parseFloat(e.target.value) })} /></div>
                                    <div className="form-group"><label>{t('adminPage.escalation.confidenceMax')}</label><input type="number" step="0.01" min="0" max="1" value={ruleForm.confidence_max} onChange={e => setRuleForm({ ...ruleForm, confidence_max: parseFloat(e.target.value) })} /></div>
                                </div>
                                <div className="form-row">
                                    <div className="form-group"><label>{t('adminPage.escalation.table.impact')}</label>
                                        <select value={ruleForm.safety_impact} onChange={e => setRuleForm({ ...ruleForm, safety_impact: e.target.value })}>
                                            <option value="low">{t('common.low')}</option><option value="medium">{t('common.medium')}</option><option value="high">{t('common.high')}</option>
                                        </select>
                                    </div>
                                    <div className="form-group"><label>{t('adminPage.escalation.table.level')}</label>
                                        <select value={ruleForm.escalation_level} onChange={e => setRuleForm({ ...ruleForm, escalation_level: parseInt(e.target.value, 10) })}>
                                            <option value={0}>{t('adminPage.escalation.noEscalation')}</option>
                                            {(levels || []).map(l => (
                                                <option key={l.level} value={l.level}>L{l.level} – {l.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                                <div className="form-group"><label>{t('common.description')}</label><input value={ruleForm.description} onChange={e => setRuleForm({ ...ruleForm, description: e.target.value })} /></div>
                                <div className="form-actions">
                                    <button type="button" className="admin-btn" onClick={() => setShowRuleForm(false)}>{t('common.cancel')}</button>
                                    <button type="submit" className="admin-btn primary">{editRule ? t('common.save') : t('common.add')}</button>
                                </div>
                            </form>
                        </Modal>
                    )}

                    {rules.length === 0 ? (
                        <div className="admin-loading">{t('adminPage.escalation.emptyRules')}</div>
                    ) : (
                        <div className="admin-table-wrap">
                            <table className="admin-table">
                                <thead><tr><th>{t('adminPage.escalation.table.id')}</th><th>{t('adminPage.escalation.table.condition')}</th><th>{t('adminPage.escalation.table.confidence')}</th><th>{t('adminPage.escalation.table.impact')}</th><th>{t('adminPage.escalation.table.level')}</th><th>{t('adminPage.escalation.table.description')}</th><th>{t('adminPage.escalation.table.actions')}</th></tr></thead>
                                <tbody>
                                    {rules.map(r => (
                                        <tr key={r.id}>
                                            <td className="td-mono">#{r.id}</td>
                                            <td className="td-bold">{r.condition}</td>
                                            <td className="td-mono">{(r.confidence_min * 100).toFixed(0)}–{(r.confidence_max * 100).toFixed(0)}%</td>
                                            <td><span style={{ color: impactColor(r.safety_impact), fontWeight: 600 }}>{r.safety_impact}</span></td>
                                            <td className="td-bold">{r.escalation_level === 0 ? t('adminPage.escalation.noEscalation') : `L${r.escalation_level}`}</td>
                                            <td>{r.description}</td>
                                            <td>
                                                <button className="admin-btn-sm" onClick={() => openEditRule(r)}>{t('common.edit')}</button>
                                                <button className="admin-btn-sm danger" onClick={() => removeRule(r)}>{t('common.delete')}</button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

// ── Historical Reports ─────────────────────────────────────────────

function ReportsSection() {
    const { t } = useI18n()
    const [reports, setReports] = useState([])
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        listIncidentReports().then(d => setReports(d.reports || [])).catch(console.error).finally(() => setLoading(false))
    }, [])

    return (
        <div className="admin-section">
            <h2 className="admin-title">{t('adminPage.reports.title')}</h2>
            {loading ? <div className="admin-loading">{t('common.loading')}</div> : (
                <div className="reports-grid" style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '20px' }}>
                    {reports.map(r => (
                        <div key={r.id} className="report-card" style={{ padding: '20px', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface)' }}>
                            <div style={{ fontWeight: '600', fontSize: '1.2em', marginBottom: '15px', color: 'var(--text-bright)' }}>
                                {t('adminPage.reports.labels.incidentId')}: {r.id || `IR-2024-${r.id}`}
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(150px, auto) 1fr', gap: '8px', marginBottom: '15px' }}>
                                <div style={{ color: 'var(--text-muted)' }}>{t('adminPage.reports.labels.dateTime')}:</div>
                                <div>{r.created_at ? new Date(r.created_at).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).replace(',', ' –') : '—'}</div>

                                <div style={{ color: 'var(--text-muted)' }}>{t('adminPage.reports.labels.processLine')}:</div>
                                <div>{r.process_line || '—'}</div>

                                <div style={{ color: 'var(--text-muted)' }}>{t('adminPage.reports.labels.machine')}:</div>
                                <div>{r.asset_id || '—'}</div>
                            </div>

                            <div style={{ marginBottom: '10px' }}>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('adminPage.reports.labels.symptom')}:</div>
                                <div>{r.symptoms?.join(', ') || r.title || '—'}</div>
                            </div>

                            <div style={{ marginBottom: '10px' }}>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('adminPage.reports.labels.triggerCondition')}:</div>
                                <div>{r.trigger_condition || '—'}</div>
                            </div>

                            <div style={{ marginBottom: '10px' }}>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('adminPage.reports.labels.initialAssumption')}:</div>
                                <div>{r.initial_assumption || '—'}</div>
                            </div>

                            <div style={{ marginBottom: '10px' }}>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('adminPage.reports.labels.rootCause')}:</div>
                                <div>{r.root_cause || '—'}</div>
                            </div>

                            <div style={{ marginBottom: '10px' }}>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('adminPage.reports.labels.resolution')}:</div>
                                <div>{r.resolution || '—'}</div>
                            </div>

                            <div style={{ marginBottom: '10px' }}>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('adminPage.reports.labels.diagnosisTime')}:</div>
                                <div style={{ paddingInlineStart: '15px' }}>{t('adminPage.reports.labels.traditional')}: ~{r.diagnosis_time_traditional || 45} {t('adminPage.reports.labels.minutes')}</div>
                                <div style={{ paddingInlineStart: '15px' }}>{t('adminPage.reports.labels.structured')}: ~{r.diagnosis_time_structured || 18} {t('adminPage.reports.labels.minutes')}</div>
                            </div>

                            <div style={{ marginBottom: '0' }}>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>{t('adminPage.reports.labels.escalation')}:</div>
                                <div>{r.escalation_required ? t('adminPage.reports.escalatedToLevel', { level: r.escalation_level }) : t('adminPage.reports.noEscalation')}</div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

// ── Live Escalation Chats (EC6) ────────────────────────────────────

function getWsBase() {
    const loc = window.location
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${loc.host}`
}

function LiveEscalationsSection() {
    const { t } = useI18n()
    const [sessions, setSessions] = useState([])
    const [loading, setLoading] = useState(true)
    const [activeSession, setActiveSession] = useState(null)
    const user = getStoredUser()

    const load = () => {
        setLoading(true)
        getEscalationSessions()
            .then(data => setSessions((data.sessions || []).filter(s => s.status !== 'closed')))
            .catch(console.error)
            .finally(() => setLoading(false))
    }
    useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t) }, [])

    const statusColor = (s) => s === 'waiting' ? '#f59e0b' : s === 'active' ? '#10b981' : '#6b7280'
    const statusLabel = (s) => s === 'waiting' ? t('adminPage.live.status.waiting') : s === 'active' ? t('adminPage.live.status.active') : s

    if (activeSession) {
        return (
            <div className="admin-section">
                <div className="admin-header-row">
                    <h2 className="admin-title">💬 {t('adminPage.live.chatTitle')}</h2>
                    <button className="admin-btn" onClick={() => setActiveSession(null)}>{t('adminPage.live.backToList')}</button>
                </div>
                <div style={{ height: 500, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                    <EscalationChat
                        sessionId={activeSession.session_id}
                        companyId={user?.company_id || activeSession.company_id}
                        userId={user?.id}
                        userRole={user?.user_type}
                        userName={user?.full_name || user?.username}
                        embedded={true}
                        minimized={false}
                        onMinimize={() => { }}
                    />
                </div>
            </div>
        )
    }

    return (
        <div className="admin-section">
            <div className="admin-header-row">
                <h2 className="admin-title">{t('adminPage.live.title')}</h2>
                <button className="admin-btn" onClick={load}>↻ {t('common.refresh')}</button>
            </div>
            {loading ? <div className="admin-loading">{t('common.loading')}</div> : sessions.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-dim)' }}>
                    <div style={{ fontSize: 32, marginBottom: 12 }}>💬</div>
                    <p>{t('adminPage.live.empty')}</p>
                </div>
            ) : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>{t('adminPage.live.table.session')}</th><th>{t('adminPage.live.table.reporter')}</th><th>{t('adminPage.live.table.expert')}</th><th>{t('adminPage.live.table.status')}</th><th>{t('adminPage.live.table.created')}</th><th></th></tr></thead>
                        <tbody>
                            {sessions.map(s => (
                                <tr key={s.session_id}>
                                    <td className="td-mono">{s.session_id?.slice(0, 12)}...</td>
                                    <td>{s.user_name || t('adminPage.live.userWithId', { id: s.user_id })}</td>
                                    <td>{s.expert_name || (s.expert_id ? t('adminPage.live.expertWithId', { id: s.expert_id }) : '—')}</td>
                                    <td><span style={{ color: statusColor(s.status), fontWeight: 600 }}>{statusLabel(s.status)}</span></td>
                                    <td>{s.created_at ? new Date(s.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}</td>
                                    <td><button className="admin-btn-sm outline" onClick={() => setActiveSession(s)}>{t('adminPage.live.viewChat')}</button></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}
