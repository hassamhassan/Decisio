# Decisio — Operational Cost per Client (Monthly)

**Scope:** Running costs only (no development/build). Assumes **OpenAI API** for both **chat/completion** and **embeddings**.

---

## Definitions: Fixed vs Usage-Based, Shared vs Dedicated

### Fixed cost
- **Meaning:** You pay the **same amount each month** regardless of how much the client uses the system.
- **Example:** A server that costs $80/month costs $80 whether the client has 10 incidents or 500 incidents. The capacity is reserved; the bill does not change with traffic (until you add/remove servers).

### Usage-based cost
- **Meaning:** The bill **goes up or down with usage** (more usage → higher cost).
- **Example:** OpenAI API: more incidents → more LLM calls → higher AI cost. Storage: more logs/data → slightly higher storage cost.

### Shared
- **Meaning:** **One server, database, or environment serves multiple clients.** You divide (or allocate) the total cost across those clients.
- **Example:** One PostgreSQL instance and one app server host 10 clients → each client might be charged 1/10 of the server cost (or a flat “shared” fee). **Lower cost per client**, but no isolation; one client’s load can affect others.

### Dedicated
- **Meaning:** **One server, database, or reserved capacity per client** (or per tier). No sharing with other clients.
- **Example:** Client A has their own app container and DB instance. **Higher cost per client**, but isolated (performance, security, compliance) and easier to guarantee SLAs.

---

## 1. Infrastructure Cost per Client

| Component | Description | Cost type | Estimated monthly (per client) |
|-----------|-------------|-----------|---------------------------------|
| **Hosting** | Single-tenant or shared app server (e.g. 2 vCPU, 4 GB RAM VPS or ECS task) | Largely **fixed** (allocated per client or amortized) | $15–40 (shared) / $40–80 (dedicated) |
| **Server usage** | CPU/memory for API + frontend (uvicorn + static) | **Fixed** (same capacity whether 10 or 1000 requests) | Included in hosting above |
| **Storage** | Logs, uploads (if any), frontend assets | **Usage-based** but small | $1–5 |
| **Database** | PostgreSQL (managed e.g. RDS, or shared instance) | **Fixed** (instance) or **usage** (storage) | $15–35 (shared) / $50–150 (dedicated) |

**Is the cost fixed or usage-based?**

- **Fixed:** Hosting (server) and database (instance) are **fixed**: you pay for capacity each month whether the client does 5 or 500 incidents. Same dollar amount per month for that client (or that environment).
- **Usage-based:** Storage (logs, backups) and any traffic/egress can be **usage-based**: slightly more usage → slightly higher bill. For Decisio, this part is usually small ($1–5/month per client).
- If you **auto-scale** (add more servers when load goes up), then part of hosting becomes usage-based; for a simple “cost per client” model we assume **stable allocation** (fixed).

**Infrastructure range per client (monthly):** **$30–80** (shared) to **$90–250** (dedicated). See Definitions above for shared vs dedicated.

---

## 2. AI Usage Cost (OpenAI)

### 2.1 Assumed OpenAI pricing (reference)

| Product | Model | Input (per 1M tokens) | Output (per 1M tokens) |
|---------|--------|------------------------|------------------------|
| Chat | **GPT-4o-mini** (recommended) | $0.15 | $0.60 |
| Chat | GPT-4o | $5.00 | $15.00 |
| Embedding | **text-embedding-3-small** | $0.02 | — |

*Source: OpenAI pricing pages; verify at [platform.openai.com](https://platform.openai.com/docs/pricing).*

### 2.2 Token estimates per Decisio “request” (one LLM call)

Approximate tokens per agent call (system prompt + user context + JSON response):

| Agent | Est. input (tokens) | Est. output (tokens) |
|-------|----------------------|----------------------|
| Incident intake | 800 | 250 |
| Screening | 600 | 150 |
| Question generation | 1,800 | 400 |
| Answer interpreter | 1,000 | 300 |
| Hypothesis update | 1,500 | 400 |
| Safety constraint | 1,500 | 350 |
| Decision brief | 2,200 | 700 |
| Escalation | 1,800 | 500 |
| Outcome capture | 1,200 | 350 |
| Memory write | 800 | 200 |
| Expert capture | 1,000 | 300 |

### 2.3 Cost per “incident” (one full flow to decision brief)

Rough flow:

- **Create incident:** intake (1) + screening (1) + question_generation (1) → **3 calls**
- **Per answer (e.g. 4 answers):** answer_interpreter (4) + hypothesis_update (4) + safety_constraint (4) + question_generation (3) → **15 calls**
- **Before brief:** post_qa_retrieval uses **embedding** once (e.g. 500 tokens) → **1 embedding call**
- **Brief + optional escalation:** decision_brief (1) + escalation (0 or 1) → **1–2 calls**
- **Outcome:** outcome_capture (1) + optional memory_write (1) + optional expert_capture (1) → **1–3 calls**

**Total per incident (typical):** ~22–26 **chat** calls + 1 **embedding** call.

**Assumed model mix (pricing basis):** **GPT-4o for Decision Brief only**, **GPT-4o-mini for all other agents.**

- **Decision brief (1 call):** 2,200 input × $5/1M + 700 output × $15/1M = **~$0.022** per incident.
- **All other chat (~21 calls, GPT-4o-mini):** ~21 × (1,400 × $0.15/1M + 350 × $0.60/1M) ≈ **$0.009** per incident.
- **Embedding:** 1 × 500 × $0.02/1M ≈ negligible.
- **Total AI per incident (mixed) ≈ $0.031** (round to **~$0.03**).

Alternative for reference:

- **GPT-4o-mini only (all agents):** ~$0.01 per incident.
- **GPT-4o only (all agents):** ~$2.75 per incident.

### 2.4 Average cost per request and requests per client per month

**Average cost per (LLM) request** with mixed model (GPT-4o for decision brief, GPT-4o-mini for rest): **~$0.0014** per call (blended across ~22 calls per incident, one of which is GPT-4o).

| Scenario | Incidents/month | Chat calls (approx) | Embedding calls (approx) |
|----------|------------------|----------------------|---------------------------|
| **Low** | 20 | ~500 | ~20 |
| **Medium** | 80 | ~2,000 | ~80 |
| **High** | 250 | ~6,000 | ~250 |

### 2.5 Estimated total AI cost per client per month (OpenAI)

**Model mix used for pricing:** **GPT-4o for Decision Brief only**, **GPT-4o-mini for all other agents**, **text-embedding-3-small** for embeddings.

| Scenario | Incidents | Cost per incident (AI) | Total AI/month |
|----------|-----------|--------------------------|----------------|
| Low | 20 | ~$0.03 | **~$0.60** |
| Medium | 80 | ~$0.03 | **~$2.40** |
| High | 250 | ~$0.03 | **~$7.50** |

**Embedding:** text-embedding-3-small cost remains negligible at these volumes.

---

## 3. Support Cost

| Item | Low | Medium | High |
|------|-----|--------|------|
| **Support hours per client/month** | 0.5–1 | 1–2 | 2–4 |
| **Cost per hour (fully loaded)** | $40–60 | $40–60 | $40–60 |
| **Support cost per client/month** | **$20–60** | **$40–120** | **$80–240** |

*Adjust hours and rate to your actual support model.*

---

## 4. Ongoing Operational Maintenance

| Item | Description | Estimated monthly (per client or shared) |
|------|-------------|------------------------------------------|
| **Monitoring** | Logging, metrics, alerts (e.g. Datadog, CloudWatch, Sentry) | $5–15 (shared) / $20–50 (per-tenant) |
| **Updates** | OS, dependencies, security patches | Often included in DevOps; else $10–20/client |
| **DevOps** | CI/CD, releases, incident response (amortized) | $20–50 per client (shared team) |
| **Other** | Backups, SSL, DNS, minor ops | $5–15 |

**Total ongoing ops (per client, amortized):** **$40–95/month**.

---

## 5. Total Monthly Cost per Client — Summary

**Pricing basis:** GPT-4o for Decision Brief only, GPT-4o-mini for all other agents, text-embedding-3-small for embeddings.

| Cost category | Low usage | Medium usage | High usage |
|---------------|-----------|--------------|------------|
| Infrastructure | $30–80 | $30–80 | $50–120 |
| AI (OpenAI) | ~$0.60 | ~$2.40 | ~$7.50 |
| Support | $20–60 | $40–120 | $80–240 |
| Ongoing ops | $40–95 | $40–95 | $50–110 |
| **Total per client/month** | **$91–236** | **$113–298** | **$187–478** |

---

## 6. Model Assumption for This Pricing

| Use case | Model | Note |
|----------|--------|------|
| **Decision Brief agent** | **GPT-4o** | Higher quality for critical recommendations; ~$0.02 per incident. |
| **All other agents (chat)** | **GPT-4o-mini** | Cost-effective; structured extraction and short reasoning. |
| **Embedding (retrieval)** | **text-embedding-3-small** | Negligible cost at Decisio volumes. |

---

---

## Quick reference: Fixed vs usage-based, shared vs dedicated

| Cost category        | Fixed or usage-based? | Often shared or dedicated? |
|----------------------|------------------------|----------------------------|
| **Hosting / server** | Fixed (same $/month)   | Shared (multi-tenant) or dedicated (per client) |
| **Database**         | Fixed (instance fee)   | Shared (one DB, many clients) or dedicated (one DB per client) |
| **Storage**          | Usage-based (GB used) | Usually shared |
| **AI (OpenAI)**      | Usage-based (tokens)   | N/A (billed to you by OpenAI; you assign cost to clients by usage) |
| **Support**          | Fixed (planned hours) or usage-based (tickets) | N/A |
| **Monitoring / DevOps** | Usually fixed (subscription or allocated hours) | Shared across clients |

*Pricing and token estimates are indicative; recalc using your actual usage and current OpenAI price list.*
