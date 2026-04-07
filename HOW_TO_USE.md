# Decisio: Complete Usage and Architecture Guide

Welcome to **Decisio**, an AI-powered operational decision-support system designed to diagnose machine issues, provide actionable decision briefs, and facilitate real-time escalation to human experts when the AI hits a safety limit or exhausts its knowledge.

This document explains **how the system works**, **the user roles**, **the incident flow**, and **how to run it**.

---

## 1. How to Run Decisio

Decisio is entirely containerized. It uses PostgreSQL (relational data), Redis (real-time WebSocket Pub/Sub), Qdrant (vector memory for past incidents), and a FastAPI + LangGraph backend, with a React + Vite frontend.

### Prerequisites
1. Docker and Docker Compose installed.
2. An **OpenAI API Key** for the LLM inference.

### Steps
1. Open the `.env` file and insert your OpenAI API key:
   ```env
   OPENAI_API_KEY=sk-your_actual_key_here
   ```
2. Start the entire system:
   ```bash
   docker-compose up -d --build
   ```
3. Access the application:
   - **Frontend App:** `http://localhost:8000`
   - **API Documentation (Swagger):** `http://localhost:8000/docs`

*(Note: The database schemas are automatically managed by Alembic upon startup).*

---

## 2. User Roles and The Admin Setup

Decisio is a multi-tenant system. Everything is isolated by `company_id`.

- **Super Admin (`super_admin`):** A system-level administrator who manages Companies.
- **Company Admin (`admin`):** Manages a specific company. They can create users, set up escalation matrices, and view KPIs/Metrics on the dashboard.
- **Operator / Technician (`operator`, `viewer`):** The person on the factory floor experiencing an issue. They trigger the diagnostic flow and answer the AI's questions.
- **Escalation Experts (`L1`, `L2`, `L3`):** Subject matter experts (e.g., Shift Engineers, OEM Reps) who receive notifications when an operator gets stuck. They jump into a live chat session to help.

### Setting Up Your Workspace
1. **Login as Admin:** (If you don't have one, the system usually provisions a default user or you can create one via the `/docs` API).
2. **Setup Escalation Levels:** Go to the "Escalation" tab in the Admin Portal and define your support tiers (e.g., L1 = Shift Engineer, L2 = Plant Maintenance).
3. **Create Experts:** Go to "Users" and create users assigned to those specific `L1`, `L2` roles.
4. **Create Operators:** Create standard `operator` users for the floor.

---

## 3. The Core Functionality: How It Works

Decisio's core value is its hybrid AI + Human workflow. Here is exactly what happens when an incident occurs.

### Step 1: Authentication & Incident Intake (The Operator)
Accessing Decisio requires strict authentication. Users must log in to receive a JWT access token, which is passed in the `Authorization` header for REST calls and as a query parameter (`?token=`) for WebSocket connections to maintain identity and `company_id` isolation across the system.

Once authenticated, an operator notices a machine fault (e.g., "The conveyor belt is jamming and smelling like burning rubber"). They open Decisio, select the affected Equipment, and describe the issue.
- **Behind the scenes:** The `incident_intake_agent` (LLM) extracts the asset ID, normalizes the summary, and assesses the initial safety risk.

### Step 2: AI Diagnostic Loop (LangGraph)
The AI enters a diagnostic Q&A loop.
- The `question_agent` formulates targeted troubleshooting questions (e.g., "Is the smell coming from the primary drive motor or the idler pulley?"). It follows a strict 10-step sequence.
- The operator answers via the UI.
- The `answer_interpreter_agent` extracts facts from the operator's response and dynamically determines if the diagnostic step is *cleared*.
- **Intelligent Progression:** If an operator's answer is vague, the AI will stay on the current step and ask a follow-up clarification question rather than prematurely moving to the next topic.
- The `hypothesis_agent` continuously ranks potential root causes based on these facts.
- **Retrieval:** If Qdrant is enabled, the AI fetches "Decision Memory" — historical incidents with similar symptoms to inform its hypotheses.

### Step 3: The Decision Brief
If the AI confidence exceeds 80%, or it asks too many questions, it generates a **Decision Brief**.
- The `decision_brief_agent` synthesizes the findings into 2-4 actionable decision options.
- **Safety Blocks:** Crucially, if the semantic analysis detects violation of custom Safety Rules (e.g., "Never open the electrical panel without Lockout/Tagout"), any high-risk option is programmatically blocked and marked "NOT RECOMMENDED".
- The brief is presented to the operator. They can choose to execute an option or manually Escalate.

### Step 4: Real-Time Escalation (The Experts)
If the AI fails, or the operator clicks "Escalate", the human experts are brought in.
- **Routing:** The system determines the necessary Escalation Level (e.g., L1) based on the asset and issue type.
- **Notification:** A WebSocket event is broadcast to all active L1 experts via **Redis Pub/Sub** (`notify_company`).
- **Expert Console:** The expert sees a pulsing "New Escalation" alert. They click it to join the **Escalation Chat**.
- **The Chatroom:** The Operator and the Expert(s) are placed in a live, real-time WebSocket chatroom. The expert can review the entire AI diagnostic history (facts, hypotheses, brief) to catch up instantly without asking the operator to repeat themselves.

### Step 5: Resolution and Memory Capture
Once the expert helps the operator fix the issue, the session is marked as "Resolved" (Success).
- **The Magic Step:** The `memory_write_agent` activates in the background. It reads the chat history and the final solution, extracts the *actual* root cause, and saves this pattern into **Qdrant**.
- The next time an operator reports a similar symptom, the AI will recall this exact expert intervention, potentially solving it autonomously!

### Step 6: Historic Analysis and Incident Reports
All structured incident data, diagnostic flow history, and final resolutions are aggregated.
- System Administrators and Management can view structured **Incident Cards** under the "Historical Incident Reports" tab in the Admin Portal.
- These reports provide a detailed, line-by-line summary including: Trigger Condition, Initial AI Assumption, Confirmed Root Cause, Resolution Action, and the Time to resolution.

---

## Technical Architecture Highlights

To ensure Decisio is enterprise-ready and scalable, it employs several modern patterns:

- **Strict Multi-Tenancy:** Every PostgreSQL query and Qdrant vector payload is hard-locked to the user's `company_id`.
- **Stateless WebSockets:** WebSockets are famously hard to scale across multiple servers. Decisio solves this by using **Redis**. When a user sends a chat message, it goes to Redis, which then fans it out to all open Uvicorn workers, ensuring messages arrive instantly regardless of which server node the expert is connected to.
- **Alembic Migrations:** Database schema changes are versioned. On boot, `alembic upgrade head` runs automatically to ensure the database matches the code.
- **Resilient Frontend:** The React frontend uses Exponential Backoff with Jitter for WebSockets. If your server goes offline for 5 minutes, 1,000 operator tablets won't DDOS the server the second it comes back online; they will stagger their reconnect attempts.
