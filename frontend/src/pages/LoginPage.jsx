import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../services/api'

function getHomePath(user) {
    if (!user?.user_type) return '/'
    if (user.user_type === 'super_admin') return '/super-admin'
    if (user.user_type === 'admin') return '/admin'
    return '/'
}

export default function LoginPage({ onLogin }) {
    const navigate = useNavigate()
    const [mode, setMode] = useState('login') // login | register
    const [username, setUsername] = useState('')
    const [email, setEmail] = useState('')
    const [password, setPassword] = useState('')
    const [fullName, setFullName] = useState('')
    const [error, setError] = useState('')
    const [passwordError, setPasswordError] = useState('')
    const [loading, setLoading] = useState(false)

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError('')
        setPasswordError('')
        setLoading(true)

        try {
            if (mode === 'login') {
                const data = await login(email, password)
                onLogin(data.user)
                navigate(getHomePath(data.user), { replace: true })
            } else {
                const data = await register(username || email, email, password, fullName)
                onLogin(data.user)
                navigate(getHomePath(data.user), { replace: true })
            }
        } catch (err) {
            const msg = err?.message
            const text = typeof msg === 'string' ? msg : 'Authentication failed'
            if (mode === 'login' && /username or password incorrect/i.test(text)) {
                setPasswordError('Username or password incorrect')
            } else {
                setError(text)
            }
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="login-page">
            <div className="login-card">
                <div className="login-header">
                    <div className="login-logo">⚙️</div>
                    <h1>Decisio</h1>
                    <p>Operational Decision Support System</p>
                </div>

                <div className="login-tabs">
                    <button
                        className={`login-tab ${mode === 'login' ? 'active' : ''}`}
                        onClick={() => setMode('login')}
                    >
                        Sign In
                    </button>
                    <button
                        className={`login-tab ${mode === 'register' ? 'active' : ''}`}
                        onClick={() => setMode('register')}
                    >
                        First Setup
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="login-form">
                    <div className="form-group">
                        <label htmlFor="email">Email</label>
                        <input
                            id="email"
                            type="email"
                            value={email}
                            onChange={(e) => { setEmail(e.target.value); setError(''); setPasswordError('') }}
                            placeholder={mode === 'login' ? 'you@example.com' : 'admin@decisio.io'}
                            required
                            autoFocus
                        />
                    </div>

                    {mode === 'register' && (
                        <>
                            <div className="form-group">
                                <label htmlFor="username">Username</label>
                                <input
                                    id="username"
                                    type="text"
                                    value={username}
                                    onChange={(e) => { setUsername(e.target.value); setError(''); setPasswordError('') }}
                                    placeholder="admin"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label htmlFor="fullName">Full Name</label>
                                <input
                                    id="fullName"
                                    type="text"
                                    value={fullName}
                                    onChange={(e) => { setFullName(e.target.value); setError(''); setPasswordError('') }}
                                    placeholder="Admin User"
                                />
                            </div>
                        </>
                    )}

                    <div className="form-group">
                        <label htmlFor="password">Password</label>
                        <input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(e) => { setPassword(e.target.value); setError(''); setPasswordError('') }}
                            placeholder="Enter password"
                            required
                        />
                        {passwordError && <div className="login-error" style={{ marginTop: 8 }}>{passwordError}</div>}
                    </div>

                    {error && <div className="login-error">{error}</div>}

                    <button type="submit" className="login-btn" disabled={loading}>
                        {loading ? 'Authenticating...' : mode === 'login' ? 'Sign In' : 'Create Admin Account'}
                    </button>
                </form>

                {mode === 'register' && (
                    <div className="login-note">
                        ℹ️ First setup creates an admin account. Subsequent users are created from the admin portal.
                    </div>
                )}
            </div>
        </div>
    )
}
