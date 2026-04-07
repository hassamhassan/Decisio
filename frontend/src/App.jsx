import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { getToken, getStoredUser, removeToken } from './services/api'
import LoginPage from './pages/LoginPage'
import AdminPortal from './pages/AdminPortal'
import IncidentConsole from './pages/IncidentConsole'
import ExpertConsole from './pages/ExpertConsole'
import SuperAdminDashboard from './pages/SuperAdminDashboard'

const LEGACY_EXPERT_ROLES = ['expert', 'escalation_owner']
function isEscalationType(t) { return (t && /^L\d+$/.test(t)) || LEGACY_EXPERT_ROLES.includes(t) }

function getHomePath(user) {
  if (!user?.user_type) return '/'
  if (user.user_type === 'super_admin') return '/super-admin'
  if (user.user_type === 'admin') return '/admin'
  return '/'
}

function App() {
  const [user, setUser] = useState(getStoredUser())
  const isLoggedIn = !!getToken() && !!user

  const handleLogin = (userData) => {
    setUser(userData)
  }

  const handleLogout = () => {
    removeToken()
    setUser(null)
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={isLoggedIn ? <Navigate to={getHomePath(user)} replace /> : <LoginPage onLogin={handleLogin} />}
        />
        <Route
          path="/super-admin"
          element={isLoggedIn ? <SuperAdminRoute user={user} onLogout={handleLogout} /> : <Navigate to="/login" />}
        />
        <Route
          path="/admin/*"
          element={isLoggedIn ? <AdminRedirect user={user} onLogout={handleLogout} /> : <Navigate to="/login" />}
        />
        <Route
          path="/*"
          element={isLoggedIn ? <ConsoleRedirect user={user} onLogout={handleLogout} /> : <Navigate to="/login" />}
        />
      </Routes>
    </BrowserRouter>
  )
}


function SuperAdminRoute({ user, onLogout }) {
  if (user?.user_type !== 'super_admin') {
    return <Navigate to={getHomePath(user)} replace />
  }
  return <SuperAdminDashboard />
}

function AdminRedirect({ user, onLogout }) {
  return <AdminPortal />
}

function ConsoleRedirect({ user, onLogout }) {
  const navigate = useNavigate()
  if (user?.user_type === 'super_admin') {
    return <Navigate to="/super-admin" replace />
  }
  if (user?.user_type === 'admin') {
    return <Navigate to="/admin" replace />
  }
  // Escalation-level roles (L1, L2, ...) or legacy expert/escalation_owner get the escalation inbox
  if (isEscalationType(user?.user_type)) {
    return (
      <ExpertConsole
        user={user}
        onLogout={onLogout}
        onAdmin={() => navigate('/admin')}
        onSuperAdmin={() => navigate('/super-admin')}
      />
    )
  }
  // Viewer role gets the chatbot
  if (user?.user_type === 'viewer') {
    return (
      <IncidentConsole
        user={user}
        onLogout={onLogout}
        onAdmin={() => navigate('/admin')}
        onSuperAdmin={() => navigate('/super-admin')}
      />
    )
  }
  // Other roles (operator, engineer) — no chatbot access
  return (
    <div className="app">
      <header className="header">
        <h1>⚙️ <span>Decisio</span></h1>
        <div className="header-status">
          <span className="header-username">{user?.full_name || user?.username}</span>
          <button className="btn btn-outline btn-sm btn-danger-outline" onClick={onLogout}>Logout</button>
        </div>
      </header>
      <div className="chat-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center', color: 'var(--text-dim)' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🔒</div>
          <p>Your account does not have access to the chatbot.</p>
        </div>
      </div>
    </div>
  )
}


export default App
