# Decisio — Operational Cost per Client (Monthly) — Gemini

**Scope:** Running costs only (no development/build). Assumes **Google Gemini API** for chat/completion and **Gemini Embedding** for retrieval.

**Model mix:** **Gemini 2.0 Pro** (or 2.5 Pro) for **all** chat agents; **Gemini Embedding** for vector search when enabled.

**Deployment assumption:** **Shared everything** — shared hosting, shared database, shared memory/storage, shared monitoring and DevOps. All infrastructure is multi-tenant; cost per client = total shared cost ÷ number of clients (e.g. 10–20 clients per server/DB). Lower per-client cost; no dedicated resources.

---

## Definitions: Fixed vs Usage-Based, Shared vs Dedicated

### Fixed cost
- **Meaning:** You pay the **same amount each month** regardless of how much the client uses the system.
- **Example:** A server that costs $80/month costs $80 whether the client has 10 incidents or 500 incidents.

### Usage-based cost
- **Meaning:** The bill **goes up or down with usage** (more usage → higher cost).
- **Example:** Gemini API: more incidents → more LLM calls → higher AI cost.

### Shared
- **Meaning:** **One server or database serves multiple clients.** Cost is divided across clients. **Lower per client**, no isolation.

### Dedicated
- **Meaning:** **One server or database per client.** **Higher per client**, isolated (performance, security, SLA).

---

## 1. Infrastructure Cost per Client (Shared Everything)

All infrastructure is **shared** across clients: one app server, one database, shared storage/memory. Per-client cost = total monthly cost of shared stack ÷ number of clients (e.g. 15 clients).

| Component | Description | Cost type | Shared total (example) | Per client (÷15 clients) |
|-----------|-------------|-----------|-------------------------|---------------------------|
| **Hosting** | App server (API + frontend) | **Fixed** | $50–80/month | **$3–6** |
| **Server usage / memory** | CPU, RAM (shared) | **Fixed** | Included in hosting | — |
| **Storage** | Logs, backups, assets (shared) | **Usage-based** (small) | $5–15/month | **$0.50–1.50** |
| **Database** | PostgreSQL (shared instance) | **Fixed** | $30–60/month | **$2–4** |

**Is the cost fixed or usage-based?**  
**Fixed (per client):** Your share of hosting and database is fixed each month for that client count. **Usage-based:** Storage and AI (Gemini) scale with usage.

**Infrastructure per client (monthly, shared everything):** **$6–12** (assuming 10–20 clients sharing one server + one DB).

---

## 2. AI Usage Cost (Gemini)

### 2.1 Assumed Gemini pricing (reference)

| Product | Model | Input (per 1M tokens) | Output (per 1M tokens) |
|---------|--------|------------------------|------------------------|
| Chat | **Gemini 2.0 Pro** / **2.5 Pro** (all agents) | $1.25 | $5.00 |
| Embedding | **gemini-embedding-001** | $0.15 | — |

*Source: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing). Verify current rates before finalizing pricing.*

### 2.2 Token estimates per agent call (same as OpenAI doc)

| Agent | Est. input (tokens) | Est. output (tokens) |
|-------|----------------------|----------------------|
| Incident intake | 800 | 250 |
| Screening | 600 | 150 |
| Question generation | 1,800 | 400 |
| Answer interpreter | 1,000 | 300 |
| Hypothesis update | 1,500 | 400 |
| Safety constraint | 1,500 | 350 |
| **Decision brief** | **2,200** | **700** |
| Escalation | 1,800 | 500 |
| Outcome capture | 1,200 | 350 |
| Memory write | 800 | 200 |
| Expert capture | 1,000 | 300 |

### 2.3 Cost per incident (Gemini Pro for all agents)

**Model:** **Gemini 2.0 Pro** (or 2.5 Pro) for **all** chat agents.

- **All chat (~22 calls, Pro):** ~22 × (1,400 × $1.25/1M + 350 × $5/1M) ≈ **$0.077** per incident (about **7.7 cents**).
- **Embedding (if used):** ~500 × $0.15/1M ≈ negligible.
- **Total AI per incident (Pro for all) ≈ $0.077** (round to **~$0.08**).

### 2.4 Average cost per request and requests per client per month

**Average cost per (LLM) request** with Gemini Pro for all: **~$0.0035** per call (blended).

| Scenario | Incidents/month | Chat calls (approx) | Embedding calls (approx) |
|----------|------------------|----------------------|---------------------------|
| **Low** | 20 | ~500 | ~20 |
| **Medium** | 80 | ~2,000 | ~80 |
| **High** | 250 | ~6,000 | ~250 |

### 2.5 Estimated total AI cost per client per month (Gemini)

**Model:** Gemini 2.0 Pro (or 2.5 Pro) for **all** chat agents; gemini-embedding-001 when retrieval is used.

| Scenario | Incidents | Cost per incident (AI) | Total AI/month |
|----------|-----------|--------------------------|----------------|
| Low | 20 | ~$0.08 | **~$1.54** |
| Medium | 80 | ~$0.08 | **~$6.16** |
| High | 250 | ~$0.08 | **~$19.25** |

---

## 3. Support Cost

| Item | Low | Medium | High |
|------|-----|--------|------|
| **Support hours per client/month** | 0.5–1 | 1–2 | 2–4 |
| **Cost per hour (fully loaded)** | $40–60 | $40–60 | $40–60 |
| **Support cost per client/month** | **$20–60** | **$40–120** | **$80–240** |

---

## 4. Ongoing Operational Maintenance (Shared)

Monitoring, updates, DevOps, and other ops are **shared** across all clients (one team, one tooling stack). Per-client share = total ops cost ÷ number of clients.

| Item | Description | Shared total (example) | Per client (÷15 clients) |
|------|-------------|--------------------------|---------------------------|
| **Monitoring** | Logging, metrics, alerts (one account) | $20–50/month | **$1.50–3.50** |
| **Updates** | OS, deps, security (one stack) | Included in DevOps | — |
| **DevOps** | CI/CD, releases, incident response (amortized) | $100–200/month | **$7–14** |
| **Other** | Backups, SSL, DNS | $10–20/month | **$1–1.50** |

**Total ongoing ops (per client, shared):** **$10–20/month**.

---

## 5. Total Monthly Cost per Client — Summary (Gemini, Shared Everything)

**Pricing basis:** Gemini 2.0 Pro (or 2.5 Pro) for **all** chat agents; Gemini Embedding when retrieval is used. **Infrastructure and ops:** shared hosting, shared DB, shared memory/storage, shared monitoring and DevOps (per-client share as above, ~15 clients).

| Cost category | Low usage | Medium usage | High usage |
|---------------|-----------|--------------|------------|
| Infrastructure (shared) | $6–12 | $6–12 | $6–12 |
| AI (Gemini) | ~$1.54 | ~$6.16 | ~$19.25 |
| Support | $20–60 | $40–120 | $80–240 |
| Ongoing ops (shared) | $10–20 | $10–20 | $10–20 |
| **Total per client/month** | **$38–93** | **$63–158** | **$116–292** |

---

## 6. Model Assumption for This Pricing (Gemini)

| Use case | Model | Note |
|----------|--------|------|
| **All agents (chat)** | **Gemini 2.0 Pro** or **2.5 Pro** | Single model for all agents (intake, screening, questions, answer interpreter, hypothesis, safety, decision brief, escalation, outcome, memory, expert capture). |
| **Embedding (retrieval)** | **gemini-embedding-001** | When vector store is enabled; cost small at typical volumes. |

---

## Quick reference (Shared Everything)

| Cost category | Fixed or usage-based? | In this doc |
|----------------------|------------------------|--------------|
| **Hosting / server** | Fixed | **Shared** — per client $3–6 |
| **Database** | Fixed | **Shared** — per client $2–4 |
| **Storage / memory** | Usage-based (small) | **Shared** — per client ~$0.50–1.50 |
| **AI (Gemini)** | Usage-based | By usage (same as before) |
| **Support** | By your model | Unchanged |
| **Monitoring / DevOps** | Fixed (amortized) | **Shared** — per client $10–20 |

---

*Pricing and token estimates are indicative. Recalculate using your actual usage and current [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).*
