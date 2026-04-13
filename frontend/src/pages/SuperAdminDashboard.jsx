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
import LanguageToggle from '../components/LanguageToggle'
import { useI18n } from '../i18n'

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
    const { dir, lang, t, toggleLang } = useI18n()
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
    const [confirmAction, setConfirmAction] = useState(null) // { action: 'delete_admin'|'deactivate_company'|'activate_company', payload: any }

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
            setSuccess(t('superAdmin.messages.companyCreated'))
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
            setError(t('superAdmin.messages.selectCompany'))
            return
        }

        const emailRegex = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/
        if (!emailRegex.test(adminForm.email.trim())) {
            setError(t('superAdmin.messages.invalidEmail'))
            return
        }
        if (adminForm.password.length < 8) {
            setError(t('superAdmin.messages.passwordMinLength'))
            return
        }
        try {
            await superAdminCreateCompanyAdmin(cid, {
                username: adminForm.username.trim(),
                email: adminForm.email.trim(),
                password: adminForm.password,
                full_name: adminForm.full_name.trim(),
            })
            setSuccess(t('superAdmin.messages.adminCreated'))
            setAdminForm({ username: '', email: '', password: '', full_name: '' })
            setSelectedCompanyId('')
            setShowCreateAdmin(false)
            loadAdmins()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    const handleDeleteAdmin = (admin) => {
        setError('')
        setSuccess('')
        setConfirmAction({ action: 'delete_admin', payload: admin })
    }

    const handleDeactivateCompany = (company) => {
        setError('')
        setSuccess('')
        setConfirmAction({ action: 'deactivate_company', payload: company })
    }

    const handleActivateCompany = (company) => {
        setError('')
        setSuccess('')
        setConfirmAction({ action: 'activate_company', payload: company })
    }

    const confirmExecute = async () => {
        if (!confirmAction) return
        setError('')
        setSuccess('')
        try {
            if (confirmAction.action === 'delete_admin') {
                await superAdminDeactivateAdmin(confirmAction.payload.id)
                setSuccess(t('superAdmin.messages.adminRemoved') || 'Admin removed and other company users deactivated.')
            } else if (confirmAction.action === 'deactivate_company') {
                await superAdminDeactivateCompany(confirmAction.payload.id)
                setSuccess(t('superAdmin.messages.companyDeactivated') || 'Company and all its users deactivated.')
            } else if (confirmAction.action === 'activate_company') {
                await superAdminActivateCompany(confirmAction.payload.id)
                setSuccess(t('superAdmin.messages.companyActivated') || 'Company and all its users activated.')
            }
            setConfirmAction(null)
            loadAdmins()
            loadCompanies()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err?.message || 'Failed')
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
            setSuccess(t('superAdmin.messages.companyUpdated'))
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
            setError(t('superAdmin.messages.invalidEmail'))
            return
        }
        if (editAdminForm.password && editAdminForm.password.length < 8) {
            setError(t('superAdmin.messages.passwordMinLength'))
            return
        }

        if (cid) payload.company_id = cid
        if (editAdminForm.password) payload.password = editAdminForm.password
        try {
            await superAdminUpdateAdmin(editAdminForm.id, payload)
            setSuccess(t('superAdmin.messages.adminUpdated'))
            setEditAdminForm({ id: null, company_id: '', email: '', full_name: '', password: '' })
            setShowEditAdmin(false)
            loadAdmins()
            setTimeout(() => setSuccess(''), 3000)
        } catch (err) {
            setError(err.message)
        }
    }

    return (
        <div className={`admin-layout ${sidebarOpen ? 'admin-sidebar-open' : ''}`} dir={dir}>
            <div className="admin-sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
            <header className="admin-mobile-header">
                <h2>🔐 Decisio</h2>
                <button type="button" className="admin-sidebar-toggle" onClick={() => setSidebarOpen(true)} aria-label={t('superAdmin.sidebar.openMenu')}>☰</button>
            </header>
            <aside className="admin-sidebar super-admin-sidebar">
                <div className="sidebar-header">
                    <h2>🔐 Decisio</h2>
                    <span className="sidebar-subtitle">{t('superAdmin.sidebar.title')}</span>
                </div>
                <nav className="sidebar-nav">
                    <button type="button" className="sidebar-item active">
                        <span className="sidebar-icon">🏢</span>
                        <span className="sidebar-label">{t('superAdmin.sidebar.companiesAdmins')}</span>
                    </button>
                </nav>
                <div className="sidebar-footer">
                    <div className="sidebar-user">
                        <div className="sidebar-user-name">{user?.full_name || user?.username}</div>
                        <div className="sidebar-user-type">
                            <span className="user-type-badge" style={{ background: '#7c3aed' }}>{t('superAdmin.sidebar.role')}</span>
                        </div>
                    </div>
                    <div className="sidebar-language-toggle">
                        <LanguageToggle lang={lang} onToggle={toggleLang} t={t} />
                    </div>
                    <div className="sidebar-actions">
                        <button className="sidebar-btn danger" onClick={logout}>{t('common.logout')}</button>
                    </div>
                </div>
            </aside>

            <main className="admin-main">
                <div className="admin-section">
                    <h2 className="admin-title">{t('superAdmin.dashboardTitle')}</h2>
                    <p className="admin-description">
                        {t('superAdmin.description')}
                    </p>

                    {confirmAction && (
                        <Modal
                            title={t('common.confirm')}
                            onClose={() => setConfirmAction(null)}
                        >
                            <div style={{ padding: '0 10px 10px 10px' }}>
                                {confirmAction.action === 'delete_admin' && (
                                    <p style={{ margin: '0 0 20px 0', fontSize: '15px' }}>
                                        {t('superAdmin.confirm.removeAdmin', { username: confirmAction.payload.username, company: confirmAction.payload.company_name })}
                                    </p>
                                )}
                                {confirmAction.action === 'deactivate_company' && (
                                    <p style={{ margin: '0 0 20px 0', fontSize: '15px' }}>
                                        {t('superAdmin.confirm.deactivateCompany', { name: confirmAction.payload.name })}
                                    </p>
                                )}
                                {confirmAction.action === 'activate_company' && (
                                    <p style={{ margin: '0 0 20px 0', fontSize: '15px' }}>
                                        {t('superAdmin.confirm.activateCompany', { name: confirmAction.payload.name })}
                                    </p>
                                )}
                                <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                                    <button className="admin-btn" onClick={() => setConfirmAction(null)}>{t('common.cancel')}</button>
                                    <button
                                        className={`admin-btn ${confirmAction.action === 'activate_company' ? 'primary' : 'danger'}`}
                                        onClick={confirmExecute}
                                        style={confirmAction.action === 'activate_company' ? { background: '#10b981', color: 'white', border: 'none' } : {}}
                                    >
                                        {confirmAction.action === 'delete_admin'
                                            ? t('common.delete')
                                            : confirmAction.action === 'deactivate_company'
                                                ? t('common.deactivate')
                                                : t('common.activate')}
                                    </button>
                                </div>
                            </div>
                        </Modal>
                    )}

                    {error && !showCreateCompany && !showCreateAdmin && !showEditCompany && !showEditAdmin && <div className="form-error" style={{ marginBottom: 12 }}>{error}</div>}
                    {success && <div className="form-success" style={{ marginBottom: 12, color: '#10b981', fontWeight: 600 }}>{success}</div>}

                    {/* Companies */}
                    <div className="admin-header-row">
                        <h3 className="admin-subtitle">{t('superAdmin.companies')}</h3>
                        <button className="admin-btn primary" onClick={() => { setShowCreateCompany(true); setError(''); setCompanyForm({ name: '' }) }}>
                            {t('superAdmin.actions.createCompany')}
                        </button>
                    </div>

                    {loading ? (
                        <div className="admin-loading">{t('superAdmin.loadingCompanies')}</div>
                    ) : (
                        <div className="admin-table-wrap">
                            <table className="admin-table">
                                <thead>
                                    <tr>
                                        <th>{t('superAdmin.table.id')}</th>
                                        <th>{t('superAdmin.table.name')}</th>

                                        <th>{t('superAdmin.table.status')}</th>
                                        <th>{t('superAdmin.table.actions')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {companies.length === 0 ? (
                                        <tr><td colSpan={5} className="td-empty">{t('superAdmin.emptyCompanies')}</td></tr>
                                    ) : companies.map(c => (
                                        <tr key={c.id}>
                                            <td className="td-mono">{c.id}</td>
                                            <td className="td-bold">{c.name}</td>

                                            <td><span className={`status-badge ${c.is_active ? 'active' : 'inactive'}`}>{c.is_active ? t('common.active') : t('common.inactive')}</span></td>
                                            <td>
                                                <button type="button" className="admin-btn" style={{ padding: '4px 10px', fontSize: 12, marginInlineEnd: 6 }} onClick={() => openEditCompany(c)}>{t('common.edit')}</button>
                                                {c.is_active ? (
                                                    <button type="button" className="admin-btn danger" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => handleDeactivateCompany(c)}>{t('common.deactivate')}</button>
                                                ) : (
                                                    <button type="button" className="admin-btn primary" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => handleActivateCompany(c)}>{t('common.activate')}</button>
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
                        <h3 className="admin-subtitle">{t('superAdmin.createCompanyAdmin')}</h3>
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
                            {t('superAdmin.actions.createAdminForCompany')}
                        </button>
                    </div>
                    {companies.length === 0 && (
                        <p style={{ color: '#94a3b8', fontSize: 14, marginTop: 8 }}>{t('superAdmin.createCompanyFirst')}</p>
                    )}

                    {/* All Admins */}
                    <div className="admin-header-row" style={{ marginTop: 32 }}>
                        <h3 className="admin-subtitle">{t('superAdmin.allAdmins')}</h3>
                    </div>
                    {adminsLoading ? (
                        <div className="admin-loading">{t('superAdmin.loadingAdmins')}</div>
                    ) : (
                        <div className="admin-table-wrap">
                            <table className="admin-table">
                                <thead>
                                    <tr>
                                        <th>{t('superAdmin.table.id')}</th>
                                        <th>{t('superAdmin.adminTable.username')}</th>
                                        <th>{t('superAdmin.adminTable.email')}</th>
                                        <th>{t('superAdmin.adminTable.fullName')}</th>
                                        <th>{t('superAdmin.adminTable.company')}</th>
                                        <th>{t('superAdmin.table.status')}</th>
                                        <th>{t('superAdmin.table.actions')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {admins.length === 0 ? (
                                        <tr><td colSpan={7} className="td-empty">{t('superAdmin.emptyAdmins')}</td></tr>
                                    ) : admins.map(a => (
                                        <tr key={a.id}>
                                            <td className="td-mono">{a.id}</td>
                                            <td className="td-bold">{a.username}</td>
                                            <td>{a.email}</td>
                                            <td>{a.full_name || '—'}</td>
                                            <td>{a.company_name}</td>
                                            <td><span className={`status-badge ${a.is_active ? 'active' : 'inactive'}`}>{a.is_active ? t('common.active') : t('common.inactive')}</span></td>
                                            <td>
                                                {a.is_active && (
                                                    <>
                                                        <button type="button" className="admin-btn" style={{ padding: '4px 10px', fontSize: 12, marginInlineEnd: 6 }} onClick={() => openEditAdmin(a)}>{t('common.edit')}</button>
                                                        <button type="button" className="admin-btn danger" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => handleDeleteAdmin(a)}>{t('common.delete')}</button>
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
                <Modal title={t('superAdmin.modals.createCompany.title')} error={error} onClose={() => { setShowCreateCompany(false); setError(''); }}>
                    <form onSubmit={handleCreateCompany}>
                        <div className="form-group">
                            <label>{t('superAdmin.modals.createCompany.companyName')}</label>
                            <input
                                value={companyForm.name}
                                onChange={e => setCompanyForm({ ...companyForm, name: e.target.value })}

                                required
                            />
                        </div>

                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => { setShowCreateCompany(false); setError(''); }}>{t('common.cancel')}</button>
                            <button type="submit" className="admin-btn primary">{t('superAdmin.actions.createCompany')}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {showCreateAdmin && (
                <Modal title={t('superAdmin.modals.createAdmin.title')} error={error} onClose={() => { setShowCreateAdmin(false); setError(''); }}>
                    <form onSubmit={handleCreateAdmin}>
                        <div className="form-group">
                            <label>{t('superAdmin.modals.createAdmin.companyLabel')}</label>
                            <select
                                value={selectedCompanyId}
                                onChange={e => setSelectedCompanyId(e.target.value)}
                                required
                            >
                                <option value="">{t('superAdmin.modals.createAdmin.selectCompany')}</option>
                                {companies.filter(c => !admins.some(a => a.company_id === c.id)).map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </select>
                            {companies.filter(c => !admins.some(a => a.company_id === c.id)).length === 0 && companies.length > 0 && (
                                <span style={{ fontSize: 12, color: 'var(--warning)' }}>{t('superAdmin.modals.createAdmin.allHaveAdmin')}</span>
                            )}
                        </div>
                        <div className="form-group">
                            <label>{t('superAdmin.adminTable.username')}</label>
                            <input
                                value={adminForm.username}
                                onChange={e => setAdminForm({ ...adminForm, username: e.target.value })}
                                required
                            />
                        </div>
                        <div className="form-group">
                            <label>{t('superAdmin.adminTable.email')}</label>
                            <input
                                type="email"
                                value={adminForm.email}
                                onChange={e => setAdminForm({ ...adminForm, email: e.target.value })}
                                required
                            />
                        </div>
                        <div className="form-group">
                            <label>{t('common.password')}</label>
                            <input
                                type="password"
                                value={adminForm.password}
                                onChange={e => setAdminForm({ ...adminForm, password: e.target.value })}
                                required

                            />
                        </div>
                        <div className="form-group">
                            <label>{t('superAdmin.adminTable.fullName')}</label>
                            <input
                                value={adminForm.full_name}
                                onChange={e => setAdminForm({ ...adminForm, full_name: e.target.value })}
                                placeholder={t('common.optional')}
                            />
                        </div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => { setShowCreateAdmin(false); setError(''); }}>{t('common.cancel')}</button>
                            <button type="submit" className="admin-btn primary">{t('superAdmin.actions.createAdmin')}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {showEditCompany && (
                <Modal title={t('superAdmin.modals.editCompany.title')} error={error} onClose={() => { setShowEditCompany(false); setError(''); }}>
                    <form onSubmit={handleUpdateCompany}>
                        <div className="form-group">
                            <label>{t('superAdmin.modals.createCompany.companyName')}</label>
                            <input
                                value={editCompanyForm.name}
                                onChange={e => setEditCompanyForm({ ...editCompanyForm, name: e.target.value })}

                                required
                            />
                        </div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => { setShowEditCompany(false); setError(''); }}>{t('common.cancel')}</button>
                            <button type="submit" className="admin-btn primary">{t('superAdmin.actions.updateCompany')}</button>
                        </div>
                    </form>
                </Modal>
            )}

            {showEditAdmin && (
                <Modal title={t('superAdmin.modals.editAdmin.title')} error={error} onClose={() => { setShowEditAdmin(false); setError(''); }}>
                    <form onSubmit={handleUpdateAdmin}>
                        <div className="form-group">
                            <label>{t('superAdmin.modals.editAdmin.organization')}</label>
                            <select
                                value={editAdminForm.company_id}
                                onChange={e => setEditAdminForm({ ...editAdminForm, company_id: e.target.value })}
                                required
                            >
                                <option value="">{t('superAdmin.modals.createAdmin.selectCompany')}</option>
                                {companies.map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </select>
                        </div>
                        <div className="form-group">
                            <label>{t('superAdmin.adminTable.email')}</label>
                            <input
                                type="email"
                                value={editAdminForm.email}
                                onChange={e => setEditAdminForm({ ...editAdminForm, email: e.target.value })}
                                required
                            />
                        </div>
                        <div className="form-group">
                            <label>{t('superAdmin.adminTable.fullName')}</label>
                            <input
                                value={editAdminForm.full_name}
                                onChange={e => setEditAdminForm({ ...editAdminForm, full_name: e.target.value })}
                                placeholder={t('common.optional')}
                            />
                        </div>
                        <div className="form-group">
                            <label>{t('superAdmin.modals.editAdmin.newPassword')}</label>
                            <input
                                type="password"
                                value={editAdminForm.password}
                                onChange={e => setEditAdminForm({ ...editAdminForm, password: e.target.value })}

                            />
                        </div>
                        <div className="form-actions">
                            <button type="button" className="admin-btn" onClick={() => { setShowEditAdmin(false); setError(''); }}>{t('common.cancel')}</button>
                            <button type="submit" className="admin-btn primary">{t('superAdmin.actions.updateAdmin')}</button>
                        </div>
                    </form>
                </Modal>
            )}
        </div>
    )
}
