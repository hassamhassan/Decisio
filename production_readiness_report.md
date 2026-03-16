# Decisio Production Readiness & Bug Report

Based on a deep architectural and code-level audit, the application is **NOT yet fully ready for production deployment at scale**. While the core logic, LLM agent graphs, and security foundations (parameterized queries, input sanitization) are solid, there are several critical infrastructure, concurrency, and operational bugs that must be addressed before launch.

Below is the comprehensive list of every bug, architectural flaw, and missing production necessity found in the codebase.

---

## 🛑 HIGH SEVERITY: Must Fix Before Launch

### 1. In-Memory WebSocket Manager (Multi-Worker Failure)
**Location:** `src/websocket/manager.py`
**Bug:** The `WebSocketManager` stores active connections and expert presence in local Python memory dictionaries (`_connections`, `_notify_connections`, `_expert_presence`).
**Impact:** If deployed to production using multiple workers (e.g., Gunicorn with 4 Uvicorn workers), a user connected to Worker A will **not** be able to chat with an expert connected to Worker B. Notifications will also only reach experts connected to the same worker that triggered the event.
**Remediation:** Replace the in-memory dictionaries with **Redis Pub/Sub** and a Redis-backed set for presence tracking.

### 2. No Database Migration Strategy
**Location:** `src/db/session.py`
**Bug:** The application relies on `Base.metadata.create_all(bind=engine)` upon startup to create database tables.
**Impact:** This cannot handle schema changes (adding/removing columns or tables) on an existing database containing live customer data. Running `create_all` will not alter existing tables, leading to crashes when new features are deployed.
**Remediation:** Introduce **Alembic** to manage database schema migrations version control.

### 3. Asynchronous Task Leaks (Orphaned Heartbeats)
**Location:** `src/websocket/router.py` (lines 245-280)
**Bug:** The `receive_task` and `heartbeat_task` use `asyncio.wait(return_when=asyncio.FIRST_COMPLETED)`. However, if the WebSocket disconnects ungracefully or throws a non-standard exception, the cancellation of the background `heartbeat_task` is not guaranteed in the `finally` block.
**Impact:** Over time, thousands of ghost `asyncio.sleep` tasks will accumulate in the event loop, causing a severe memory leak and CPU degradation until the server crashes.
**Remediation:** Ensure all spawned tasks are tracked and strictly cancelled in the `finally` block:
```python
finally:
    heartbeat_task.cancel()
    if 'receive_task' in locals(): receive_task.cancel()
    await ws_manager.notify_disconnect(...)
```

---

## ⚠️ MEDIUM SEVERITY: Operational & Performance Risks

### 4. Unpaginated Message History
**Location:** `api.py` -> `list_escalation_messages`
**Bug:** `result.scalars().all()` is called on the `EscalationMessage` table without any `LIMIT` or pagination.
**Impact:** For long-running escalation sessions with hundreds of messages, this will cause massive JSON payloads, slowing down the API response and causing frontend rendering lag.
**Remediation:** Implement cursor-based or limit/offset pagination on the `/api/escalation/sessions/{session_id}/messages` endpoint.

### 5. Escalation Session Creation Silently Swallowed
**Location:** `api.py` -> `_ensure_escalation_session`
**Bug:** The entire database creation and expert assignment block is wrapped in a generic `try...except Exception as e: logger.warning(...)`.
**Impact:** If the database momentarily drops connection, the creation fails silently. The user is told "Escalating...", but no session is actually created, leaving them permanently hanging.
**Remediation:** Catch specific exceptions for the notification failure (which is fine to swallow), but bubble up or properly retry database insertion errors.

### 6. Aggressive Reconnection Storms (Frontend)
**Location:** `frontend/src/ExpertConsole.jsx`
**Bug:** When the WebSocket disconnects, the frontend blindly blindly attempts to reconnect exactly every 5000ms.
**Impact:** If the backend restarts or goes down, all active tabs for all users will bombard the server with identical reconnect requests exactly every 5 seconds, causing a Thundering Herd problem that can crash the server the moment it comes back online.
**Remediation:** Implement **Exponential Backoff with Jitter** for WebSocket reconnections (e.g., trying at 2s, 4s, 8s, 16s + random milliseconds).

### 7. Database Hit on Every Protected Route
**Location:** `api.py` -> `require_auth`
**Bug:** The JWT validation `require_auth` queries `crud.get_user_by_username()` from the PostgreSQL database on *every single API request*.
**Impact:** Under heavy load, the database will become the bottleneck just serving authentication queries.
**Remediation:** The JWT signature is already cryptographically secure. Rely on the `user_id`, `company_id`, and `user_type` directly from the validated token payload instead of hitting the database, unless you specifically need to verify if the account was recently deactivated (for which checking a Redis blacklist is faster).

---

## 🟡 LOW SEVERITY: UX & Code Quality

### 8. Frontend `useEffect` Race Conditions
**Location:** `frontend/src/AdminPortal.jsx` & `frontend/src/ExpertConsole.jsx`
**Bug:** In `loadSessions()` and similar data fetching hooks, if the component unmounts before a slow API request finishes, the `.then(data => setSessions(data))` will attempt to update state on an unmounted component.
**Impact:** Causes harmless but noisy React memory leak warnings in the console (`Can't perform a React state update on an unmounted component`).
**Remediation:** Add an `isMounted` ref or use an `AbortController` in the `useEffect` hooks.

### 9. Hardcoded Polling Intervals
**Location:** `frontend/src/ExpertConsole.jsx`
**Bug:** The UI polls `/api/escalation/sessions` every 15 seconds, *even though* it is also connected to the WebSocket notification channel `notify_company` which pushes updates instantly.
**Impact:** Unnecessary server load.
**Remediation:** the 15-second polling can be removed entirely, relying solely on the `session_closed` and `new_escalation` WebSocket events to trigger a refresh. If a fallback is desired, it should be polled every 60s or 120s instead.

### 10. Empty Exception Blocks (`except: pass`)
**Location:** `api.py:476`, `api.py:384`
**Bug:** `memory_write_agent` and `decision_brief_agent` failing are caught by bare `except Exception: pass`.
**Impact:** If developers break the LLM prompt or the API key expires, it will fail 100% of the time in production, but there will be zero logs to indicate why memory isn't being written.
**Remediation:** Always log errors (`logger.error(..., exc_info=True)`) before passing.

---

## Summary Verdict
**Status: Not Production Ready**
The application requires the replacement of the in-memory WebSocket manager with Redis (Issue #1) and the setup of Alembic migrations (Issue #2) before it can safely handle concurrent multi-user production traffic. The task leak (Issue #3) should also be fixed to prevent server crashes over time. Fixing these 3 items will clear the path for a stable V1 launch.
