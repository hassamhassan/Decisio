import { useState, useEffect } from 'react'
import {
    superAdminListCompanies,
    superAdminCreateCompany,
    superAdminUpdateCompany,
    superAdminCreateCompanyAdmin,
    superAdminListAdmins,
    superAdminDeactivateAdmin,
    superAdminUpdateAdmin,
    superAdminDeactivateCompany,
    superAdminActivateCompany,
    logout,
    getStoredUser,
} from '../services/api'

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

export default function SuperAdminDashboard() {
    const user = getStoredUser()
    const [companies, setCompanies] = useState([])
    const [admins, setAdmins] = useState([])
    const [loading, setLoading] = useState(true)
    const [adminsLoading, setAdminsLoading] = useState(true)
    const [error, setError] = useState('')
    const [success, setSuccess] = useState('')

    // Create company modal
    const [showCreateCompany, setShowCreateCompany] = useState(false)
    const [companyForm, setCompanyForm] = useState({ name: '' })

    // Create admin modal
    const [showCreateAdmin, setShowCreateAdmin] = useState(false)
    const [selectedCompanyId, setSelectedCompanyId] = useState('')
    const [adminForm, setAdminForm] = useState({ username: '', email: '', password: '', full_name: '' })
    const [sidebarOpen, setSidebarOpen] = useState(false)

    // Edit company modal
    const [showEditCompany, setShowEditCompany] = useState(false)
    const [editCompanyForm, setEditCompanyForm] = useState({ id: null, name: '' })

    // Edit admin modal
    const [showEditAdmin, setShowEditAdmin] = useState(false)
    const [editAdminForm, setEditAdminForm] = useState({ id: null, company_id: '', email: '', full_name: '', password: '' })

    const loadCompanies = () => {
        setLoading(true)
        setError('')
        superAdminListCompanies()
            .then(d => setCompanies(d.companies || []))
            .catch(err => setError(err.message))
            .finally(() => setLoading(false))
    }

    const loadAdmins = () => {
        setAdminsLoading(true)
        superAdminListAdmins()
            .then(d => setAdmins(d.admins || []))
            .catch(() => setAdmins([]))
            .finally(() => setAdminsLoading(false))
    }

    useEffect(() => {
        loadCompanies()
    }, [])

    useEffect(() => {
        loadAdmins()
    }, [])

    const handleCreateCompany = async (e) => {
        e.preventDefault()
        setError('')
        setSuccess('')
        try {
            await superAdminCreateCompany(companyForm.name.trim())
            setSuccess('Company created successfully.')
            setCompanyForm({ name: '' })
            setShowCreateCompany(false)
            loadCompanies()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    const handleCreateAdmin = async (e) => {
        e.preventDefault()
        setError('')
        setSuccess('')
        const cid = parseInt(selectedCompanyId, 10)
        if (!cid) {
            setError('Select a company.')
            return
        }

        const emailRegex = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/
        if (!emailRegex.test(adminForm.email.trim())) {
            setError('Email is not valid ')
            return
        }
        if (adminForm.password.length < 8) {
            setError('Password must have at least 8 characters')
            return
        }
        try {
            await superAdminCreateCompanyAdmin(cid, {
                username: adminForm.username.trim(),
                email: adminForm.email.trim(),
                password: adminForm.password,
                full_name: adminForm.full_name.trim(),
            })
            setSuccess(`Admin created for company.`)
            setAdminForm({ username: '', email: '', password: '', full_name: '' })
            setSelectedCompanyId('')
            setShowCreateAdmin(false)
            loadAdmins()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    const handleDeleteAdmin = async (admin) => {
        if (!confirm(`Remove admin "${admin.username}"? This will DELETE the admin user and deactivate all other users in company "${admin.company_name}". Assign a new admin to the company to reactivate users.`)) return
        setError('')
        setSuccess('')
        try {
            await superAdminDeactivateAdmin(admin.id)
            setSuccess('Admin removed and other company users deactivated.')
            loadAdmins()
            loadCompanies()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    const handleDeactivateCompany = async (company) => {
        if (!confirm(`Deactivate company "${company.name}" and all its users?`)) return
        setError('')
        setSuccess('')
        try {
            await superAdminDeactivateCompany(company.id)
            setSuccess('Company and all its users deactivated.')
            loadCompanies()
            loadAdmins()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    const handleActivateCompany = async (company) => {
        if (!confirm(`Activate company "${company.name}" and all its users?`)) return
        setError('')
        setSuccess('')
        try {
            await superAdminActivateCompany(company.id)
            setSuccess('Company and all its users activated.')
            loadCompanies()
            loadAdmins()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    const openEditCompany = (company) => {
        setEditCompanyForm({ id: company.id, name: company.name })
        setShowEditCompany(true)
        setError('')
    }

    const handleUpdateCompany = async (e) => {
        e.preventDefault()
        setError('')
        setSuccess('')
        try {
            await superAdminUpdateCompany(editCompanyForm.id, { name: editCompanyForm.name.trim() })
            setSuccess('Company updated.')
            setShowEditCompany(false)
            loadCompanies()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    const openEditAdmin = (admin) => {
        setEditAdminForm({
            id: admin.id,
            company_id: admin.company_id ? String(admin.company_id) : '',
            email: admin.email,
            full_name: admin.full_name || '',
            password: '',
        })
        setShowEditAdmin(true)
        setError('')
    }

    const handleUpdateAdmin = async (e) => {
        e.preventDefault()
        setError('')
        setSuccess('')
        const payload = { email: editAdminForm.email.trim(), full_name: editAdminForm.full_name.trim() }
        const cid = parseInt(editAdminForm.company_id, 10)

        const emailRegex = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/
        if (!emailRegex.test(payload.email)) {
            setError('Email is not valid')
            return
        }
        if (editAdminForm.password && editAdminForm.password.length < 8) {
            setError('Password must have at least 8 characters')
            return
        }

        if (cid) payload.company_id = cid
        if (editAdminForm.password) payload.password = editAdminForm.password
        try {
            await superAdminUpdateAdmin(editAdminForm.id, payload)
            setSuccess('Admin updated.')
            setEditAdminForm({ id: null, company_id: '', email: '', full_name: '', password: '' })
            setShowEditAdmin(false)
            loadAdmins()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    return (
        <div className={`admin-layout ${sidebarOpen ? 'admin-sidebar-open' : ''}`}>
            <div className="admin-sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
            <header className="admin-mobile-header">
                <h2>🔐 Decisio</h2>
                <button type="button" className="admin-sidebar-toggle" onClick={() => setSidebarOpen(true)} aria-label="Open menu">☰</button>
            </header>
            <aside className="admin-sidebar super-admin-sidebar">
                <div className="sidebar-header">
                    <h2>🔐 Decisio</h2>
                    <span className="sidebar-subtitle">Super Admin</span>
                </div>
                <nav className="sidebar-nav">
                    <button type="button" className="sidebar-item active">
                        <span className="sidebar-icon">🏢</span>
                        <span className="sidebar-label">Companies & Admins</span>
                    </button>
                </nav>
                <div className="sidebar-footer">
                    <div className="sidebar-user">
                        <div className="sidebar-user-name">{user?.full_name || user?.username}</div>
                        <div className="sidebar-user-type">
                            <span className="user-type-badge" style={{ background: '#7c3aed' }}>super_admin</span>
                        </div>
                    </div>
                    <div className="sidebar-actions">
                        <button className="sidebar-btn danger" onClick={logout}>Logout</button>
                    </div>
                </div>
            </aside>

            <main className="admin-main">
                <div className="admin-section">
                    <h2 className="admin-title">Super Admin Dashboard</h2>
                    <p className="admin-description">
                        Create companies and assign an admin to each company. Company admins can then manage users, equipment, and settings for their tenant.
                    </p>

                    {error && !showCreateCompany && !showCreateAdmin && !showEditCompany && !showEditAdmin && <div className="form-error" style={{ marginBottom: 12 }}>{error}</div>}
                    {success && <div className="form-success" style={{ marginBottom: 12, color: '#10b981', fontWeight: 600 }}>{success}</div>}

                    {/* Companies */}
                    <div className="admin-header-row">
                        <h3 className="admin-subtitle">Companies</h3>
                        <button className="admin-btn primary" onClick={() => { setShowCreateCompany(true); setError(''); setCompanyForm({ name: '' }) }}>
                            + Create Company
                        </button>
                    </div>

                    {loading ? (
                        <div className="admin-loading">Loading companies...</div>
                    ) : (
                        <div className="admin-table-wrap">
                            <table className="admin-table">
                                <thead>
                                    <tr>
                                        <th>ID</th>
                                        <th>Name</th>

                                        <th>Status</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {companies.length === 0 ? (
                                        <tr><td colSpan={5} className="td-empty">No companies yet. Create one to get started.</td></tr>
                                    ) : companies.map(c => (
                                        <tr key={c.id}>
                                            <td className="td-mono">{c.id}</td>
                                            <td className="td-bold">{c.name}</td>

                                            <td><span className={`status-badge ${c.is_active ? 'active' : 'inactive'}`}>{c.is_active ? 'Active' : 'Inactive'}</span></td>
                                            <td>
                                                <button type="button" className="admin-btn" style={{ padding: '4px 10px', fontSize: 12, marginRight: 6 }} onClick={() => openEditCompany(c)}>Edit</button>
                                                {c.is_active ? (
                                                    <button type="button" className="admin-btn danger" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => handleDeactivateCompany(c)}>Deactivate</button>
                                                ) : (
                                                    <button type="button" className="admin-btn primary" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => handleActivateCompany(c)}>Activate</button>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {/* Create admin for company */}
                    <div className="admin-header-row" style={{ marginTop: 32 }}>
                        <h3 className="admin-subtitle">Create Company Admin</h3>
                        <button
                            className="admin-btn primary"
                            onClick={() => {
                                setShowCreateAdmin(true)
                                setError('')
                                setAdminForm({ username: '', email: '', password: '', full_name: '' })
                                const withoutAdmin = companies.find(c => !admins.some(a => a.company_id === c.id))
                                setSelectedCompanyId(withoutAdmin?.id ? String(withoutAdmin.id) : '')
                            }}
                            disabled={companies.length === 0}
                        >
                            + Create Admin for Company
                        </button>
                    </div>
                    {companies.length === 0 && (
                        <p style={{ color: '#94a3b8', fontSize: 14, marginTop: 8 }}>Create a company first, then you can add an admin for it.</p>
                    )}

                    {/* All Admins */}
                    <div className="admin-header-row" style={{ marginTop: 32 }}>
                        <h3 className="admin-subtitle">All Admins</h3>
                    </div>
                    {adminsLoading ? (
                        <div className="admin-loading">Loading admins...</div>
                    ) : (
                        <div className="admin-table-wrap">
                            <table className="admin-table">
                                <thead>
                                    <tr>
                                        <th>ID</th>
                                        <th>Username</th>
                                        <th>Email</th>
                                        <th>Full Name</th>
                                        <th>Company</th>
                                        <th>Status</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {admins.length === 0 ? (
                                        <tr><td colSpan={7} className="td-empty">No company admins yet. Create one above.</td></tr>
                                    ) : admins.map(a => (
                                        <tr key={a.id}>
                                            <td className="td-mono">{a.id}</td>
                                            <td className="td-bold">{a.username}</td>
                                            <td>{a.email}</td>
                                            <td>{a.full_name || '—'}</td>
                                            <td>{a.company_name}</td>
                                            <td><span className={`status-badge ${a.is_active ? 'active' : 'inactive'}`}>{a.is_active ? 'Active' : 'Inactive'}</span></td>
                                            <td>
                                                {a.is_active && (
                                                    <>
                                                        <button type="button" className="admin-btn" style={{ padding: '4px 10px', fontSize: 12, marginRight: 6 }} onClick={() => openEditAdmin(a)}>Edit</button>
                                                        <button type="button" className="admin-btn danger" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => handleDeleteAdmin(a)}>Delete</button>
                                                    </>
                                                )}
                                                {!a.is_active && <span style={{ color: '#94a3b8', fontSize: 12 }}>—</span>}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </main>

            {showCreateCompany && (
                <Modal title="Create Company" error={error} onClose={() => { setShowCreateCompany(false); setError(''); }}>
                    <form onSubmit={handleCreateCompany}>
                        <div className="form-group">
                            <label>Company Name</label>
                            <input
                                value={companyForm.name}
                                onChange={e => setCompanyForm({ ...companyForm, name: e.target.value })}

                                required
                            />
                        </div>

                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => { setShowCreateCompany(false); setError(''); }}>Cancel</button>
                            <button type="submit" className="admin-btn primary">Create Company</button>
                        </div>
                    </form>
                </Modal>
            )}

            {showCreateAdmin && (
                <Modal title="Create Admin for Company" error={error} onClose={() => { setShowCreateAdmin(false); setError(''); }}>
                    <form onSubmit={handleCreateAdmin}>
                        <div className="form-group">
                            <label>Company (only companies without an admin)</label>
                            <select
                                value={selectedCompanyId}
                                onChange={e => setSelectedCompanyId(e.target.value)}
                                required
                            >
                                <option value="">Select company...</option>
                                {companies.filter(c => !admins.some(a => a.company_id === c.id)).map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </select>
                            {companies.filter(c => !admins.some(a => a.company_id === c.id)).length === 0 && companies.length > 0 && (
                                <span style={{ fontSize: 12, color: 'var(--warning)' }}>All companies already have an admin. Edit an admin to change organization.</span>
                            )}
                        </div>
                        <div className="form-group">
                            <label>Username</label>
                            <input
                                value={adminForm.username}
                                onChange={e => setAdminForm({ ...adminForm, username: e.target.value })}
                                required
                            />
                        </div>
                        <div className="form-group">
                            <label>Email</label>
                            <input
                                type="email"
                                value={adminForm.email}
                                onChange={e => setAdminForm({ ...adminForm, email: e.target.value })}
                                required
                            />
                        </div>
                        <div className="form-group">
                            <label>Password</label>
                            <input
                                type="password"
                                value={adminForm.password}
                                onChange={e => setAdminForm({ ...adminForm, password: e.target.value })}
                                required

                            />
                        </div>
                        <div className="form-group">
                            <label>Full Name</label>
                            <input
                                value={adminForm.full_name}
                                onChange={e => setAdminForm({ ...adminForm, full_name: e.target.value })}
                                placeholder="Optional"
                            />
                        </div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => { setShowCreateAdmin(false); setError(''); }}>Cancel</button>
                            <button type="submit" className="admin-btn primary">Create Admin</button>
                        </div>
                    </form>
                </Modal>
            )}

            {showEditCompany && (
                <Modal title="Edit Company" error={error} onClose={() => { setShowEditCompany(false); setError(''); }}>
                    <form onSubmit={handleUpdateCompany}>
                        <div className="form-group">
                            <label>Company Name</label>
                            <input
                                value={editCompanyForm.name}
                                onChange={e => setEditCompanyForm({ ...editCompanyForm, name: e.target.value })}

                                required
                            />
                        </div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => { setShowEditCompany(false); setError(''); }}>Cancel</button>
                            <button type="submit" className="admin-btn primary">Update Company</button>
                        </div>
                    </form>
                </Modal>
            )}

            {showEditAdmin && (
                <Modal title="Edit Admin" error={error} onClose={() => { setShowEditAdmin(false); setError(''); }}>
                    <form onSubmit={handleUpdateAdmin}>
                        <div className="form-group">
                            <label>Organization (Company)</label>
                            <select
                                value={editAdminForm.company_id}
                                onChange={e => setEditAdminForm({ ...editAdminForm, company_id: e.target.value })}
                                required
                            >
                                <option value="">Select company...</option>
                                {companies.map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </select>
                        </div>
                        <div className="form-group">
                            <label>Email</label>
                            <input
                                type="email"
                                value={editAdminForm.email}
                                onChange={e => setEditAdminForm({ ...editAdminForm, email: e.target.value })}
                                required
                            />
                        </div>
                        <div className="form-group">
                            <label>Full Name</label>
                            <input
                                value={editAdminForm.full_name}
                                onChange={e => setEditAdminForm({ ...editAdminForm, full_name: e.target.value })}
                                placeholder="Optional"
                            />
                        </div>
                        <div className="form-group">
                            <label>New Password (leave blank to keep current)</label>
                            <input
                                type="password"
                                value={editAdminForm.password}
                                onChange={e => setEditAdminForm({ ...editAdminForm, password: e.target.value })}

                            />
                        </div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => { setShowEditAdmin(false); setError(''); }}>Cancel</button>
                            <button type="submit" className="admin-btn primary">Update Admin</button>
                        </div>
                    </form>
                </Modal>
            )}
        </div>
    )
}
