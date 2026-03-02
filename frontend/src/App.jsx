import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { getToken, getStoredUser, removeToken } from './api'
import LoginPage from './LoginPage'
import AdminPortal from './AdminPortal'
import IncidentConsole from './IncidentConsole'
import SuperAdminDashboard from './SuperAdminDashboard'

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
  return (
    <IncidentConsole
      user={user}
      onLogout={onLogout}
      onAdmin={() => navigate('/admin')}
      onSuperAdmin={() => navigate('/super-admin')}
    />
  )
}


export default App
