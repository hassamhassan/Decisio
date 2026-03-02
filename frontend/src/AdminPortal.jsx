import { useState, useEffect } from 'react'
import {
    getDashboard, listUsers, createUser, updateUser, deleteUser,
    listEquipment, listSafetyRules, getEscalationMatrix, listIncidentReports,
    listIncidents, logout, getStoredUser,
    createEquipment, updateEquipment, deleteEquipment,
    createSafetyRule, updateSafetyRule, deleteSafetyRule,
    createEscalationLevel, updateEscalationLevel, deleteEscalationLevel,
    createEscalationRule, updateEscalationRule, deleteEscalationRule,
    changePassword, getKpiStats,
} from './api'

const SECTIONS = [
    { id: 'dashboard', label: '📊 Dashboard', icon: '📊' },
    { id: 'users', label: '👥 Users', icon: '👥' },
    { id: 'incidents', label: '🔧 Incidents', icon: '🔧' },
    { id: 'equipment', label: '📦 Equipment', icon: '📦' },
    { id: 'safety', label: '🛡️ Safety Rules', icon: '🛡️' },
    { id: 'escalation', label: '📈 Escalation', icon: '📈' },
    { id: 'reports', label: '📋 Reports', icon: '📋' },
]

const TYPE_COLORS = {
    admin: '#ef4444',
    operator: '#3b82f6',
    engineer: '#10b981',
    viewer: '#8b5cf6',
    escalation_owner: '#f97316',
    expert: '#06b6d4',
}
function userTypeColor(userType) {
    return TYPE_COLORS[userType] ?? '#64748b'
}

export default function AdminPortal() {
    const [section, setSection] = useState('dashboard')
    const [sidebarOpen, setSidebarOpen] = useState(false)
    const [showPwModal, setShowPwModal] = useState(false)
    const [pwForm, setPwForm] = useState({ current: '', new_pw: '', confirm: '' })
    const [pwError, setPwError] = useState('')
    const [pwSuccess, setPwSuccess] = useState('')
    const user = getStoredUser()

    const handlePwChange = async (e) => {
        e.preventDefault()
        setPwError(''); setPwSuccess('')
        if (pwForm.new_pw !== pwForm.confirm) { setPwError('Passwords do not match'); return }
        if (pwForm.new_pw.length < 4) { setPwError('Password must be at least 4 characters'); return }
        try {
            await changePassword(pwForm.current, pwForm.new_pw)
            setPwSuccess('Password changed successfully!')
            setPwForm({ current: '', new_pw: '', confirm: '' })
            setTimeout(() => setShowPwModal(false), 1500)
        } catch (err) { setPwError(err.message) }
    }

    return (
        <div className={`admin-layout ${sidebarOpen ? 'admin-sidebar-open' : ''}`}>
            <div className="admin-sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
            <header className="admin-mobile-header">
                <h2>⚙️ Decisio</h2>
                <button type="button" className="admin-sidebar-toggle" onClick={() => setSidebarOpen(true)} aria-label="Open menu">☰</button>
            </header>
            <aside className="admin-sidebar">
                <div className="sidebar-header">
                    <h2>⚙️ Decisio</h2>
                    <span className="sidebar-subtitle">Admin Portal</span>
                </div>
                <nav className="sidebar-nav">
                    {SECTIONS.map(s => (
                        <button
                            key={s.id}
                            type="button"
                            className={`sidebar-item ${section === s.id ? 'active' : ''}`}
                            onClick={() => { setSection(s.id); setSidebarOpen(false); }}
                        >
                            <span className="sidebar-icon">{s.icon}</span>
                            <span className="sidebar-label">{s.label.split(' ').slice(1).join(' ')}</span>
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
                    <div className="sidebar-actions">
                        <button className="sidebar-btn" onClick={() => setShowPwModal(true)}>🔑 Password</button>
                        <button className="sidebar-btn danger" onClick={logout}>Logout</button>
                    </div>
                </div>
            </aside>
            <main className="admin-main">
                {section === 'dashboard' && <DashboardSection />}
                {section === 'users' && <UsersSection />}
                {section === 'incidents' && <IncidentsSection />}
                {section === 'equipment' && <EquipmentSection />}
                {section === 'safety' && <SafetySection />}
                {section === 'escalation' && <EscalationSection />}
                {section === 'reports' && <ReportsSection />}
            </main>

            {showPwModal && (
                <Modal title="Change Password" onClose={() => setShowPwModal(false)}>
                    <form onSubmit={handlePwChange}>
                        <div className="form-group"><label>Current Password</label><input type="password" value={pwForm.current} onChange={e => setPwForm({ ...pwForm, current: e.target.value })} required /></div>
                        <div className="form-group"><label>New Password</label><input type="password" value={pwForm.new_pw} onChange={e => setPwForm({ ...pwForm, new_pw: e.target.value })} required /></div>
                        <div className="form-group"><label>Confirm New Password</label><input type="password" value={pwForm.confirm} onChange={e => setPwForm({ ...pwForm, confirm: e.target.value })} required /></div>
                        {pwError && <div className="form-error">{pwError}</div>}
                        {pwSuccess && <div style={{ color: '#10b981', margin: '8px 0', fontWeight: 600 }}>{pwSuccess}</div>}
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => setShowPwModal(false)}>Cancel</button>
                            <button type="submit" className="admin-btn primary">Change Password</button>
                        </div>
                    </form>
                </Modal>
            )}
        </div>
    )
}

// ── Reusable Modal ─────────────────────────────────────────────────

function Modal({ title, children, onClose }) {
    return (
        <div className="admin-modal-overlay" onClick={onClose}>
            <div className="admin-modal" onClick={e => e.stopPropagation()}>
                <h3>{title}</h3>
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
    const [stats, setStats] = useState(null)
    const [kpis, setKpis] = useState(null)
    const [loading, setLoading] = useState(true)
    const [loadError, setLoadError] = useState('')

    useEffect(() => {
        setLoadError('')
        Promise.all([
            getDashboard()
                .then((data) => {
                    setStats(data || DEFAULT_STATS)
                })
                .catch((err) => {
                    setStats(DEFAULT_STATS)
                    setLoadError(err?.message || 'Failed to load dashboard data')
                }),
            getKpiStats().then(setKpis).catch(() => setKpis(null)),
        ]).finally(() => setLoading(false))
    }, [])

    if (loading && !stats) return <div className="admin-loading">Loading dashboard...</div>

    const data = stats || DEFAULT_STATS
    const cards = [
        { label: 'Total Incidents', value: data.total_incidents, color: '#3b82f6', icon: '📋' },
        { label: 'Open Incidents', value: data.open_incidents, color: '#f59e0b', icon: '⚡' },
        { label: 'Closed', value: data.closed_incidents, color: '#10b981', icon: '✅' },
        { label: 'Users', value: data.total_users, color: '#8b5cf6', icon: '👥' },
        { label: 'Equipment', value: data.total_equipment, color: '#06b6d4', icon: '📦' },
        { label: 'Safety Rules', value: data.total_safety_rules, color: '#ef4444', icon: '🛡️' },
        { label: 'Avg MTTD', value: data.avg_mttd_seconds != null ? `${data.avg_mttd_seconds}s` : '—', color: '#ec4899', icon: '⏱️' },
        { label: 'Reports', value: data.total_reports, color: '#14b8a6', icon: '📊' },
    ]

    const fmtSec = (s) => s ? (s < 60 ? `${Math.round(s)}s` : `${(s / 60).toFixed(1)}m`) : '—'

    return (
        <div className="admin-section">
            <h2 className="admin-title">Dashboard</h2>
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
                    <h3 className="admin-subtitle" style={{ marginTop: 28 }}>Key Performance Indicators (§27)</h3>
                    <div className="stats-grid">
                        <div className="stat-card" style={{ borderColor: '#ec4899' }}>
                            <div className="stat-icon">⏱️</div>
                            <div className="stat-value" style={{ color: '#ec4899' }}>{fmtSec(kpis.mttd?.average_seconds)}</div>
                            <div className="stat-label">Avg MTTD</div>
                            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>Min {fmtSec(kpis.mttd?.min_seconds)} / Max {fmtSec(kpis.mttd?.max_seconds)}</div>
                        </div>
                        <div className="stat-card" style={{ borderColor: '#f59e0b' }}>
                            <div className="stat-icon">📈</div>
                            <div className="stat-value" style={{ color: '#f59e0b' }}>{kpis.incidents?.escalation_rate_pct}%</div>
                            <div className="stat-label">Escalation Rate</div>
                            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>{kpis.incidents?.escalated} of {kpis.incidents?.total} escalated</div>
                        </div>
                        <div className="stat-card" style={{ borderColor: '#ef4444' }}>
                            <div className="stat-icon">⚠️</div>
                            <div className="stat-value" style={{ color: '#ef4444' }}>{kpis.process_failures?.detection_rate_pct}%</div>
                            <div className="stat-label">Process Failure Rate</div>
                            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>{kpis.process_failures?.count} of {kpis.process_failures?.total_reports} reports</div>
                        </div>
                        <div className="stat-card" style={{ borderColor: '#10b981' }}>
                            <div className="stat-icon">✅</div>
                            <div className="stat-value" style={{ color: '#10b981' }}>{kpis.incidents?.closed}</div>
                            <div className="stat-label">Resolved</div>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

// ── Users ──────────────────────────────────────────────────────────

// User type options: only Viewer (extra) + escalation levels added by admin (no Admin in list)
function getUserTypeOptions(escalationLevels, currentValue) {
    const options = [{ value: 'viewer', label: 'Viewer' }]
    escalationLevels.forEach(l => options.push({ value: `L${l.level}`, label: `L${l.level} – ${l.name}` }))
    // When editing, include current value so select displays correctly if it's not in the list (e.g. admin)
    if (currentValue && !options.some(o => o.value === currentValue)) {
        options.push({ value: currentValue, label: currentValue })
    }
    return options
}

function UsersSection() {
    const [users, setUsers] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [editUser, setEditUser] = useState(null)
    const [form, setForm] = useState({ username: '', email: '', password: '', full_name: '', user_type: 'viewer' })
    const [error, setError] = useState('')
    const [escalationLevels, setEscalationLevels] = useState([])

    const loadUsers = () => {
        setLoading(true)
        listUsers().then(d => setUsers(d.users)).catch(console.error).finally(() => setLoading(false))
    }
    useEffect(() => { loadUsers() }, [])
    useEffect(() => {
        getEscalationMatrix().then(data => setEscalationLevels(data?.levels ?? [])).catch(() => setEscalationLevels([]))
    }, [])

    const userTypeOptions = getUserTypeOptions(escalationLevels, form.user_type)

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError('')
        try {
            if (editUser) {
                const update = {}
                if (form.email) update.email = form.email
                if (form.full_name) update.full_name = form.full_name
                if (form.user_type) update.user_type = form.user_type
                if (form.password) update.password = form.password
                await updateUser(editUser.id, update)
            } else {
                await createUser(form)
            }
            setShowForm(false)
            setEditUser(null)
            setForm({ username: '', email: '', password: '', full_name: '', user_type: 'viewer' })
            loadUsers()
        } catch (err) { setError(err.message) }
    }

    const handleEdit = (u) => {
        setEditUser(u)
        setForm({ username: u.username, email: u.email, password: '', full_name: u.full_name, user_type: u.user_type })
        setShowForm(true)
    }

    const handleDelete = async (u) => {
        if (!confirm(`Deactivate user "${u.username}"?`)) return
        try { await deleteUser(u.id); loadUsers() } catch (err) { alert(err.message) }
    }

    return (
        <div className="admin-section">
            <div className="admin-header-row">
                <h2 className="admin-title">User Management</h2>
                <button className="admin-btn primary" onClick={() => { setShowForm(true); setEditUser(null); setForm({ username: '', email: '', password: '', full_name: '', user_type: 'viewer' }) }}>+ Create User</button>
            </div>

            {showForm && (
                <Modal title={editUser ? 'Edit User' : 'Create New User'} onClose={() => setShowForm(false)}>
                    <form onSubmit={handleSubmit}>
                        {!editUser && <div className="form-group"><label>Username</label><input value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} required /></div>}
                        <div className="form-group"><label>Email</label><input type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} required={!editUser} /></div>
                        <div className="form-group"><label>Full Name</label><input value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} /></div>
                        <div className="form-group"><label>Password {editUser && '(leave blank to keep)'}</label><input type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} required={!editUser} /></div>
                        <div className="form-group"><label>User Type</label>
                            <select value={form.user_type} onChange={e => setForm({ ...form, user_type: e.target.value })}>
                                {userTypeOptions.map(({ value, label }) => (
                                    <option key={value} value={value}>{label}</option>
                                ))}
                            </select>
                        </div>
                        {error && <div className="form-error">{error}</div>}
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => setShowForm(false)}>Cancel</button>
                            <button type="submit" className="admin-btn primary">{editUser ? 'Save' : 'Create'}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {loading ? <div className="admin-loading">Loading users...</div> : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>Username</th><th>Full Name</th><th>Email</th><th>Type</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>
                        <tbody>
                            {users.map(u => (
                                <tr key={u.id} className={!u.is_active ? 'inactive-row' : ''}>
                                    <td className="td-bold">{u.username}</td>
                                    <td>{u.full_name || '—'}</td>
                                    <td>{u.email}</td>
                                    <td><span className="user-type-badge" style={{ background: userTypeColor(u.user_type) }}>{u.user_type}</span></td>
                                    <td><span className={`status-badge ${u.is_active ? 'active' : 'inactive'}`}>{u.is_active ? 'Active' : 'Inactive'}</span></td>
                                    <td>{new Date(u.created_at).toLocaleDateString()}</td>
                                    <td>
                                        <button className="admin-btn-sm" onClick={() => handleEdit(u)}>Edit</button>
                                        {u.is_active && <button className="admin-btn-sm danger" onClick={() => handleDelete(u)}>Deactivate</button>}
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
    const [incidents, setIncidents] = useState([])
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        listIncidents().then(d => setIncidents(d.incidents || [])).catch(console.error).finally(() => setLoading(false))
    }, [])

    const statusColor = (s) => {
        if (s === 'CLOSED') return '#10b981'
        if (s === 'ESCALATED') return '#ef4444'
        if (s === 'OPEN' || s === 'DIAGNOSIS_LOOP') return '#f59e0b'
        return '#6b7280'
    }

    return (
        <div className="admin-section">
            <h2 className="admin-title">Incidents</h2>
            {loading ? <div className="admin-loading">Loading...</div> : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>ID</th><th>Summary</th><th>Asset</th><th>Severity</th><th>Status</th><th>Confidence</th><th>Risk</th></tr></thead>
                        <tbody>
                            {incidents.length === 0 ? (
                                <tr><td colSpan={7} className="td-empty">No incidents yet</td></tr>
                            ) : incidents.map((inc, i) => (
                                <tr key={i}>
                                    <td className="td-mono">{inc.incident_id?.slice(0, 12)}...</td>
                                    <td>{inc.summary?.slice(0, 50) || '—'}</td>
                                    <td className="td-bold">{inc.asset_id || '—'}</td>
                                    <td><span className={`badge badge-${inc.severity || 'medium'}`}>{inc.severity}</span></td>
                                    <td><span style={{ color: statusColor(inc.status), fontWeight: 600 }}>{inc.status}</span></td>
                                    <td>{Math.round((inc.confidence || 0) * 100)}%</td>
                                    <td>{inc.risk_score?.toFixed(1) || '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

// ── Equipment (CRUD) ───────────────────────────────────────────────

function EquipmentSection() {
    const [equipment, setEquipment] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [editItem, setEditItem] = useState(null)
    const [form, setForm] = useState({ id: '', name: '', equipment_type: 'rotating', process_line: 'Line A', criticality: 'medium', description: '', upstream_id: '', downstream_id: '' })
    const [error, setError] = useState('')

    const load = () => { setLoading(true); listEquipment().then(d => setEquipment(d.equipment || [])).catch(console.error).finally(() => setLoading(false)) }
    useEffect(() => { load() }, [])

    const openCreate = () => {
        setEditItem(null)
        setForm({ id: '', name: '', equipment_type: 'rotating', process_line: 'Line A', criticality: 'medium', description: '', upstream_id: '', downstream_id: '' })
        setShowForm(true)
        setError('')
    }

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
        if (!confirm(`Delete equipment "${eq.id}"?`)) return
        try { await deleteEquipment(eq.id); load() } catch (err) { alert(err.message) }
    }

    const critColor = (c) => c === 'critical' ? '#ef4444' : c === 'high' ? '#f59e0b' : c === 'medium' ? '#3b82f6' : '#6b7280'

    return (
        <div className="admin-section">
            <div className="admin-header-row">
                <h2 className="admin-title">Equipment Registry</h2>
                <button className="admin-btn primary" onClick={openCreate}>+ Add Equipment</button>
            </div>

            {showForm && (
                <Modal title={editItem ? `Edit ${editItem.id}` : 'Add Equipment'} onClose={() => setShowForm(false)}>
                    <form onSubmit={handleSubmit}>
                        {!editItem && <div className="form-group"><label>Equipment ID</label><input value={form.id} onChange={e => setForm({ ...form, id: e.target.value })} placeholder="e.g. CMP-02" required /></div>}
                        <div className="form-group"><label>Name</label><input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required /></div>
                        <div className="form-group"><label>Type</label>
                            <select value={form.equipment_type} onChange={e => setForm({ ...form, equipment_type: e.target.value })}>
                                <option value="rotating">Rotating</option><option value="pressure_vessel">Pressure Vessel</option>
                                <option value="heat_exchange">Heat Exchange</option><option value="storage">Storage</option>
                                <option value="piping">Piping</option><option value="electrical">Electrical</option>
                            </select>
                        </div>
                        <div className="form-row">
                            <div className="form-group"><label>Process Line</label><input value={form.process_line} onChange={e => setForm({ ...form, process_line: e.target.value })} /></div>
                            <div className="form-group"><label>Criticality</label>
                                <select value={form.criticality} onChange={e => setForm({ ...form, criticality: e.target.value })}>
                                    <option value="critical">Critical</option><option value="high">High</option>
                                    <option value="medium">Medium</option><option value="low">Low</option>
                                </select>
                            </div>
                        </div>
                        <div className="form-group"><label>Description</label><input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></div>
                        <div className="form-row">
                            <div className="form-group"><label>Upstream ID</label><input value={form.upstream_id} onChange={e => setForm({ ...form, upstream_id: e.target.value })} placeholder="e.g. CMP-01" /></div>
                            <div className="form-group"><label>Downstream ID</label><input value={form.downstream_id} onChange={e => setForm({ ...form, downstream_id: e.target.value })} placeholder="e.g. CON-01" /></div>
                        </div>
                        {error && <div className="form-error">{error}</div>}
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => setShowForm(false)}>Cancel</button>
                            <button type="submit" className="admin-btn primary">{editItem ? 'Save' : 'Add'}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {loading ? <div className="admin-loading">Loading...</div> : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Line</th><th>Criticality</th><th>Upstream</th><th>Downstream</th><th>Actions</th></tr></thead>
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
                                    <td>
                                        <button className="admin-btn-sm" onClick={() => openEdit(eq)}>Edit</button>
                                        <button className="admin-btn-sm danger" onClick={() => handleDelete(eq)}>Delete</button>
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
    const [rules, setRules] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [editItem, setEditItem] = useState(null)
    const [form, setForm] = useState({ type: '', rule: '' })
    const [error, setError] = useState('')

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
        if (!confirm(`Delete safety rule #${r.id}?`)) return
        try { await deleteSafetyRule(r.id); load() } catch (err) { alert(err.message) }
    }

    return (
        <div className="admin-section">
            <div className="admin-header-row">
                <h2 className="admin-title">Safety Rules</h2>
                <button className="admin-btn primary" onClick={openCreate}>+ Add Rule</button>
            </div>

            {showForm && (
                <Modal title={editItem ? `Edit Rule #${editItem.id}` : 'Add Safety Rule'} onClose={() => setShowForm(false)}>
                    <form onSubmit={handleSubmit}>
                        <div className="form-group"><label>Type</label>
                            <select value={form.type} onChange={e => setForm({ ...form, type: e.target.value })} required>
                                {safetyTypeOptions.map(t => (
                                    <option key={t} value={t}>{t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</option>
                                ))}
                            </select>
                        </div>
                        <div className="form-group"><label>Rule</label><input value={form.rule} onChange={e => setForm({ ...form, rule: e.target.value })} placeholder="Rule text" required /></div>
                        {error && <div className="form-error">{error}</div>}
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => setShowForm(false)}>Cancel</button>
                            <button type="submit" className="admin-btn primary">{editItem ? 'Save' : 'Add'}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {loading ? <div className="admin-loading">Loading...</div> : (
                <div className="admin-table-wrap">
                    <table className="admin-table">
                        <thead><tr><th>Type</th><th>Rule</th><th>Actions</th></tr></thead>
                        <tbody>
                            {rules.map(r => (
                                <tr key={r.id}>
                                    <td className="td-bold">{r.equipment_type}</td>
                                    <td>{r.rule_text}</td>
                                    <td>
                                        <button className="admin-btn-sm" onClick={() => openEdit(r)}>Edit</button>
                                        <button className="admin-btn-sm danger" onClick={() => handleDelete(r)}>Delete</button>
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
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(true)
    const [showLevelForm, setShowLevelForm] = useState(false)
    const [editLevel, setEditLevel] = useState(null)
    const [levelForm, setLevelForm] = useState({ level: 1, name: '', description: '' })
    const [showRuleForm, setShowRuleForm] = useState(false)
    const [editRule, setEditRule] = useState(null)
    const [ruleForm, setRuleForm] = useState({ condition: '', confidence_min: 0, confidence_max: 1, safety_impact: 'low', escalation_level: 1, description: '', sort_order: 100 })
    const [error, setError] = useState('')

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
        if (!confirm(`Delete level ${l.level}?`)) return
        try { await deleteEscalationLevel(l.level); load() } catch (err) { alert(err.message) }
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
        if (!confirm(`Delete rule #${r.id}?`)) return
        try { await deleteEscalationRule(r.id); load() } catch (err) { alert(err.message) }
    }

    const impactColor = (i) => i === 'high' ? '#ef4444' : i === 'medium' ? '#f59e0b' : '#10b981'

    const levels = data?.levels || []
    const rules = data?.rules || []

    return (
        <div className="admin-section">
            <h2 className="admin-title">Escalation Matrix</h2>
            {loading ? <div className="admin-loading">Loading...</div> : (
                <>
                    {/* Levels */}
                    <div className="admin-header-row" style={{ marginBottom: 12 }}>
                        <h3 className="admin-subtitle">Levels</h3>
                        <button className="admin-btn primary" onClick={openCreateLevel}>+ Add Level</button>
                    </div>

                    {showLevelForm && (
                        <Modal title={editLevel ? `Edit Level ${editLevel.level}` : 'Add Escalation Level'} onClose={() => setShowLevelForm(false)}>
                            <form onSubmit={submitLevel}>
                                {!editLevel && <div className="form-group"><label>Level Number</label><input type="number" value={levelForm.level} onChange={e => setLevelForm({ ...levelForm, level: parseInt(e.target.value) })} required /></div>}
                                <div className="form-group"><label>Name</label><input value={levelForm.name} onChange={e => setLevelForm({ ...levelForm, name: e.target.value })} placeholder="e.g. Field Supervisor" required /></div>
                                <div className="form-group"><label>Description</label><input value={levelForm.description} onChange={e => setLevelForm({ ...levelForm, description: e.target.value })} /></div>
                                {error && <div className="form-error">{error}</div>}
                                <div className="form-actions">
                                    <button type="button" className="admin-btn" onClick={() => setShowLevelForm(false)}>Cancel</button>
                                    <button type="submit" className="admin-btn primary">{editLevel ? 'Save' : 'Add'}</button>
                                </div>
                            </form>
                        </Modal>
                    )}

                    {levels.length === 0 ? (
                        <div className="admin-loading">No escalation levels yet. Click "+ Add Level" to create one.</div>
                    ) : (
                        <div className="escalation-levels">
                            {levels.map(l => (
                                <div key={l.level} className="escalation-level-card">
                                    <div className="esc-level-num">L{l.level}</div>
                                    <div className="esc-level-name">{l.name}</div>
                                    <div className="esc-level-desc">{l.description}</div>
                                    <div className="esc-level-actions">
                                        <button className="admin-btn-sm" onClick={() => openEditLevel(l)}>Edit</button>
                                        <button className="admin-btn-sm danger" onClick={() => removeLevel(l)}>Delete</button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Rules */}
                    <div className="admin-header-row" style={{ marginTop: 24, marginBottom: 12 }}>
                        <h3 className="admin-subtitle">Rules</h3>
                        <button className="admin-btn primary" onClick={openCreateRule}>+ Add Rule</button>
                    </div>

                    {showRuleForm && (
                        <Modal title={editRule ? `Edit Rule #${editRule.id}` : 'Add Escalation Rule'} onClose={() => setShowRuleForm(false)}>
                            <form onSubmit={submitRule}>
                                <div className="form-group"><label>Condition</label><input value={ruleForm.condition} onChange={e => setRuleForm({ ...ruleForm, condition: e.target.value })} placeholder="e.g. high_risk_low_confidence" required /></div>
                                <div className="form-row">
                                    <div className="form-group"><label>Confidence Min</label><input type="number" step="0.01" min="0" max="1" value={ruleForm.confidence_min} onChange={e => setRuleForm({ ...ruleForm, confidence_min: parseFloat(e.target.value) })} /></div>
                                    <div className="form-group"><label>Confidence Max</label><input type="number" step="0.01" min="0" max="1" value={ruleForm.confidence_max} onChange={e => setRuleForm({ ...ruleForm, confidence_max: parseFloat(e.target.value) })} /></div>
                                </div>
                                <div className="form-row">
                                    <div className="form-group"><label>Safety Impact</label>
                                        <select value={ruleForm.safety_impact} onChange={e => setRuleForm({ ...ruleForm, safety_impact: e.target.value })}>
                                            <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
                                        </select>
                                    </div>
                                    <div className="form-group"><label>Escalation Level</label>
                                        <select value={ruleForm.escalation_level} onChange={e => setRuleForm({ ...ruleForm, escalation_level: parseInt(e.target.value, 10) })}>
                                            <option value={0}>0 – No escalation</option>
                                            {(levels || []).map(l => (
                                                <option key={l.level} value={l.level}>L{l.level} – {l.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                                <div className="form-group"><label>Description</label><input value={ruleForm.description} onChange={e => setRuleForm({ ...ruleForm, description: e.target.value })} /></div>
                                {error && <div className="form-error">{error}</div>}
                                <div className="form-actions">
                                    <button type="button" className="admin-btn" onClick={() => setShowRuleForm(false)}>Cancel</button>
                                    <button type="submit" className="admin-btn primary">{editRule ? 'Save' : 'Add'}</button>
                                </div>
                            </form>
                        </Modal>
                    )}

                    {rules.length === 0 ? (
                        <div className="admin-loading">No escalation rules yet. Click "+ Add Rule" to create one.</div>
                    ) : (
                        <div className="admin-table-wrap">
                            <table className="admin-table">
                                <thead><tr><th>ID</th><th>Condition</th><th>Confidence</th><th>Impact</th><th>Level</th><th>Description</th><th>Actions</th></tr></thead>
                                <tbody>
                                    {rules.map(r => (
                                        <tr key={r.id}>
                                            <td className="td-mono">#{r.id}</td>
                                            <td className="td-bold">{r.condition}</td>
                                            <td className="td-mono">{(r.confidence_min * 100).toFixed(0)}–{(r.confidence_max * 100).toFixed(0)}%</td>
                                            <td><span style={{ color: impactColor(r.safety_impact), fontWeight: 600 }}>{r.safety_impact}</span></td>
                                            <td className="td-bold">{r.escalation_level === 0 ? 'No escalation' : `L${r.escalation_level}`}</td>
                                            <td>{r.description}</td>
                                            <td>
                                                <button className="admin-btn-sm" onClick={() => openEditRule(r)}>Edit</button>
                                                <button className="admin-btn-sm danger" onClick={() => removeRule(r)}>Delete</button>
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
    const [reports, setReports] = useState([])
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        listIncidentReports().then(d => setReports(d.reports || [])).catch(console.error).finally(() => setLoading(false))
    }, [])

    return (
        <div className="admin-section">
            <h2 className="admin-title">Historical Incident Reports</h2>
            {loading ? <div className="admin-loading">Loading...</div> : (
                <div className="reports-grid">
                    {reports.map(r => (
                        <div key={r.id} className="report-card">
                            <div className="report-header">
                                <span className="report-id">{r.id}</span>
                                <span className={`badge badge-${r.severity}`}>{r.severity}</span>
                            </div>
                            <h4 className="report-title">{r.title}</h4>
                            <div className="report-meta">
                                <span>Asset: <strong>{r.asset_id}</strong></span>
                                <span>Line: <strong>{r.process_line}</strong></span>
                                <span>Category: <strong>{r.root_cause_category}</strong></span>
                            </div>
                            <div className="report-field">
                                <div className="report-field-label">Root Cause</div>
                                <div>{r.root_cause}</div>
                            </div>
                            <div className="report-field">
                                <div className="report-field-label">Resolution</div>
                                <div>{r.resolution}</div>
                            </div>
                            <div className="report-times">
                                <div className="time-compare">
                                    <span className="time-old">{r.diagnosis_time_traditional}min</span>
                                    <span className="time-arrow">→</span>
                                    <span className="time-new">{r.diagnosis_time_structured}min</span>
                                </div>
                                <span className="time-label">Traditional → Structured</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
