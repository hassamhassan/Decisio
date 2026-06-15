const API_BASE = '/api';

// ── Token management ───────────────────────────────────────────────

export function getToken() {
    return localStorage.getItem('decisio_token');
}

export function setToken(token) {
    localStorage.setItem('decisio_token', token);
}

export function removeToken() {
    localStorage.removeItem('decisio_token');
    localStorage.removeItem('decisio_user');
}

export function getStoredUser() {
    const u = localStorage.getItem('decisio_user');
    return u ? JSON.parse(u) : null;
}

export function setStoredUser(user) {
    localStorage.setItem('decisio_user', JSON.stringify(user));
}

function authHeaders() {
    const token = getToken();
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

async function apiFetch(url, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...authHeaders(),
        ...(options.headers || {}),
    };
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
        // Login/register can legitimately return 401 for wrong credentials;
        // do not force a full-page redirect in that case.
        const isAuthEndpoint =
            url.includes('/auth/login') ||
            url.includes('/auth/register') ||
            url.includes('/auth/me') && !getToken();

        if (isAuthEndpoint) {
            // Prefer a clean, user-facing message.
            throw new Error('Username or password incorrect');
        }

        // Otherwise, treat as session expiry for authenticated calls.
        removeToken();
        window.location.href = '/login';
        throw new Error('Session expired');
    }
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body.detail;
        let message = `Error: ${res.status}`;
        if (typeof detail === 'string') message = detail;
        else if (Array.isArray(detail) && detail.length > 0) message = detail[0].msg || detail[0].message || JSON.stringify(detail[0]);
        else if (detail && typeof detail === 'object') message = detail.msg || detail.message || JSON.stringify(detail);
        throw new Error(message);
    }
    return res.json();
}

// ── Auth API ───────────────────────────────────────────────────────

export async function login(email, password) {
    const data = await apiFetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
    });
    setToken(data.access_token);
    setStoredUser(data.user);
    return data;
}

export async function register(username, email, password, fullName) {
    const data = await apiFetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        body: JSON.stringify({
            username, email, password, full_name: fullName, user_type: 'admin',
        }),
    });
    setToken(data.access_token);
    setStoredUser(data.user);
    return data;
}

export async function getMe() {
    return apiFetch(`${API_BASE}/auth/me`);
}

export function logout() {
    removeToken();
    window.location.href = '/login';
}

// ── Admin API ──────────────────────────────────────────────────────

export async function getDashboard() {
    return apiFetch(`${API_BASE}/admin/dashboard`);
}

export async function listUsers() {
    return apiFetch(`${API_BASE}/admin/users`);
}

export async function createUser(data) {
    return apiFetch(`${API_BASE}/admin/users`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function updateUser(userId, data) {
    return apiFetch(`${API_BASE}/admin/users/${userId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}

export async function deleteUser(userId) {
    return apiFetch(`${API_BASE}/admin/users/${userId}`, {
        method: 'DELETE',
    });
}

// ── Admin Equipment CRUD ───────────────────────────────────────────

export async function createEquipment(data) {
    return apiFetch(`${API_BASE}/admin/equipment`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function updateEquipment(equipmentId, data) {
    return apiFetch(`${API_BASE}/admin/equipment/${equipmentId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}

export async function deleteEquipment(equipmentId) {
    return apiFetch(`${API_BASE}/admin/equipment/${equipmentId}`, {
        method: 'DELETE',
    });
}

export async function uploadEquipmentManual(equipmentId, file) {
    const token = getToken();
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/admin/equipment/${equipmentId}/manual`, {
        method: 'POST',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        body: formData,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail || `Upload failed (${res.status})`);
    return data;
}

export async function deleteEquipmentManual(equipmentId) {
    return apiFetch(`${API_BASE}/admin/equipment/${equipmentId}/manual`, {
        method: 'DELETE',
    });
}

export async function getEquipmentManualStatus(equipmentId) {
    return apiFetch(`${API_BASE}/admin/equipment/${equipmentId}/manual/status`);
}



export async function createSafetyRule(data) {
    return apiFetch(`${API_BASE}/admin/safety-rules`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function updateSafetyRule(ruleId, data) {
    return apiFetch(`${API_BASE}/admin/safety-rules/${ruleId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}

export async function deleteSafetyRule(ruleId) {
    return apiFetch(`${API_BASE}/admin/safety-rules/${ruleId}`, {
        method: 'DELETE',
    });
}

// ── Admin Escalation CRUD ──────────────────────────────────────────

export async function createEscalationLevel(data) {
    return apiFetch(`${API_BASE}/admin/escalation-levels`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function updateEscalationLevel(levelId, data) {
    return apiFetch(`${API_BASE}/admin/escalation-levels/${levelId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}

export async function deleteEscalationLevel(levelId) {
    return apiFetch(`${API_BASE}/admin/escalation-levels/${levelId}`, {
        method: 'DELETE',
    });
}

export async function createEscalationRule(data) {
    return apiFetch(`${API_BASE}/admin/escalation-rules`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function updateEscalationRule(ruleId, data) {
    return apiFetch(`${API_BASE}/admin/escalation-rules/${ruleId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}

export async function deleteEscalationRule(ruleId) {
    return apiFetch(`${API_BASE}/admin/escalation-rules/${ruleId}`, {
        method: 'DELETE',
    });
}

// ── Incident API ───────────────────────────────────────────────────

export async function createIncident(report, language = 'en') {
    return apiFetch(`${API_BASE}/incidents`, {
        method: 'POST',
        body: JSON.stringify({ report, language }),
    });
}

export async function submitAnswer(incidentId, answer, language = 'en') {
    return apiFetch(`${API_BASE}/incidents/${incidentId}/answer`, {
        method: 'POST',
        body: JSON.stringify({ answer, language }),
    });
}

export async function generateBrief(incidentId, language = 'en') {
    return apiFetch(`${API_BASE}/incidents/${incidentId}/brief`, {
        method: 'POST',
        body: JSON.stringify({ language }),
    });
}

export async function submitOutcome(incidentId, outcome, selectedOptionId = null, language = 'en', outcomeNotes = null) {
    const body = { outcome, language };
    if (selectedOptionId != null) body.selected_option_id = selectedOptionId;
    if (outcomeNotes && outcomeNotes.trim()) body.outcome_notes = outcomeNotes.trim();
    return apiFetch(`${API_BASE}/incidents/${incidentId}/outcome`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export async function getIncident(incidentId) {
    return apiFetch(`${API_BASE}/incidents/${incidentId}`);
}

export async function listIncidents() {
    return apiFetch(`${API_BASE}/incidents`);
}

// ── Operational Data API ───────────────────────────────────────────

export async function listEquipment() {
    return apiFetch(`${API_BASE}/equipment`);
}

export async function listSafetyRules(equipmentType) {
    const q = equipmentType ? `?equipment_type=${equipmentType}` : '';
    return apiFetch(`${API_BASE}/safety-rules${q}`);
}

export async function getEscalationMatrix() {
    return apiFetch(`${API_BASE}/escalation-matrix`);
}

export async function listIncidentReports() {
    return apiFetch(`${API_BASE}/incident-reports`);
}

// ── Password Change ──────────────────────────────────────────────

export async function changePassword(currentPassword, newPassword) {
    return apiFetch(`${API_BASE}/auth/change-password`, {
        method: 'PUT',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
}

// ── KPI Stats ────────────────────────────────────────────────────

export async function getKpiStats() {
    return apiFetch(`${API_BASE}/admin/stats/kpis`);
}

// ── Super Admin API ───────────────────────────────────────────────

export async function superAdminListCompanies() {
    return apiFetch(`${API_BASE}/super-admin/companies`);
}

export async function superAdminCreateCompany(data) {
    return apiFetch(`${API_BASE}/super-admin/companies`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function superAdminUpdateCompany(companyId, data) {
    return apiFetch(`${API_BASE}/super-admin/companies/${companyId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}

export async function superAdminCreateCompanyAdmin(companyId, data) {
    return apiFetch(`${API_BASE}/super-admin/companies/${companyId}/admins`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function superAdminListAdmins() {
    return apiFetch(`${API_BASE}/super-admin/admins`);
}

export async function superAdminDeactivateAdmin(userId) {
    return apiFetch(`${API_BASE}/super-admin/admins/${userId}/deactivate`, {
        method: 'POST',
    });
}

export async function superAdminUpdateAdmin(userId, data) {
    return apiFetch(`${API_BASE}/super-admin/admins/${userId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
    });
}

export async function superAdminDeactivateCompany(companyId) {
    return apiFetch(`${API_BASE}/super-admin/companies/${companyId}/deactivate`, {
        method: 'POST',
    });
}

export async function superAdminActivateCompany(companyId) {
    return apiFetch(`${API_BASE}/super-admin/companies/${companyId}/activate`, {
        method: 'POST',
    });
}

// ── Escalation Chat API ──────────────────────────────────────────

export async function checkExpertsAvailable() {
    return apiFetch(`${API_BASE}/escalation/experts/available`);
}

export async function getEscalationSessions() {
    return apiFetch(`${API_BASE}/escalation/sessions`);
}

export async function getEscalationMessages(sessionId) {
    return apiFetch(`${API_BASE}/escalation/sessions/${sessionId}/messages`);
}

export async function closeEscalationSession(sessionId) {
    return apiFetch(`${API_BASE}/escalation/sessions/${sessionId}/close`, {
        method: 'POST',
    });
}

export function getWsBaseUrl() {
    const loc = window.location;
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${loc.host}`;
}

// ── Admin Notifications API ──────────────────────────────────────

export async function getAdminNotifications(unreadOnly = false) {
    return apiFetch(`${API_BASE}/admin/notifications${unreadOnly ? '?unread_only=true' : ''}`);
}

export async function getAdminNotificationCount() {
    return apiFetch(`${API_BASE}/admin/notifications/count`);
}

export async function markNotificationRead(notificationId) {
    return apiFetch(`${API_BASE}/admin/notifications/${notificationId}/read`, { method: 'POST' });
}

export async function markAllNotificationsRead() {
    return apiFetch(`${API_BASE}/admin/notifications/read-all`, { method: 'POST' });
}

// ── Admin Knowledge Base API ─────────────────────────────────────

export async function listKnowledgeEntries() {
    return apiFetch(`${API_BASE}/admin/knowledge`);
}

export async function createKnowledgeEntry(data) {
    return apiFetch(`${API_BASE}/admin/knowledge`, {
        method: 'POST',
        body: JSON.stringify(data),
    });
}

export async function deleteKnowledgeEntry(entryId) {
    return apiFetch(`${API_BASE}/admin/knowledge/${entryId}`, {
        method: 'DELETE',
    });
}
