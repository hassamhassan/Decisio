# Decisio — Operational Cost per Client (Monthly) — Gemini

> **Billing model:** We charge **per client** (company). Each client can have **many users** — the cost stays the same regardless of users within a client.  
> **LLM:** Google **Gemini 2.0 Pro / 2.5 Pro** (all agents) + **gemini-embedding-001** (retrieval).  
> **Deployment:** One **shared stack** for all clients.

---

## Part A — Mandatory Fixed Costs (You Pay These No Matter What)

These costs exist as soon as your stack is running, even with **zero clients**. They do **not** change with client count or usage.

| # | Item | What It Covers | Monthly Cost |
|---|------|---------------|-------------|
| 1 | **App Server (Hosting)** | API + frontend server | $50–80 |
| 2 | **Database (PostgreSQL)** | Shared DB instance | $30–60 |
| 3 | **Vector Database** | Qdrant for RAG embeddings | $20–50 |
| 4 | **Monitoring & Alerts** | Logging, metrics, alerting tools | $20–50 |
| 5 | **CI/CD Tooling** | GitHub Actions / pipeline runner costs | $10–30 |
| 6 | **Other (Backups, SSL, DNS)** | Backups, certificates, domain | $10–20 |
| | **Total Fixed (Base Overhead)** | | **≈ $140–290/month** |

> **Simplified base:** For calculations below we use **≈ $200/month** as the midpoint base overhead.

---

## Part B — Per-Client Variable Costs (Scale With Number of Clients)

These costs **increase** as you add more clients. They fall into two categories:

### B1. Extra Infrastructure per Client

Each additional client adds a small load to the shared stack (more CPU/RAM, more storage).

| Item | Per Client / Month |
|------|-------------------|
| Extra CPU / RAM share | ~$3–5 |
| Extra storage (logs, backups, assets) | ~$1–3 |
| **Subtotal extra infra per client** | **≈ $5/month** |

### B2. AI Cost per Client (Gemini — Usage-Based)

AI cost depends on how many **incidents** a client generates per month.

**Gemini pricing reference:**

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|----------------------|
| Gemini 2.0 Pro / 2.5 Pro | $1.25 | $5.00 |
| gemini-embedding-001 | $0.15 | — |

**Cost per incident:** Each incident triggers ~22 agent calls → **≈ $0.08 per incident**.

| Usage Level | Incidents / Month | AI Cost / Month |
|-------------|-------------------|----------------|
| **Low** | 20 | **~$1.54** |
| **Medium** | 80 | **~$6.16** |
| **High** | 250 | **~$19.25** |

### B3. Support Cost per Client

| Usage Level | Support Hours / Month | Cost @ $40–60/hr | Support Cost / Month |
|-------------|----------------------|------------------|---------------------|
| **Low** | 0.5–1 hr | $40–60 | **$20–60** |
| **Medium** | 1–2 hr | $40–60 | **$40–120** |
| **High** | 2–4 hr | $40–60 | **$80–240** |

---

## Cost Summary — Per Client at Different Client Counts

### Formula

```
Per-client cost = (Base Overhead ÷ N clients) + Extra Infra per client + AI cost + Support cost
```

Using: Base = $200/month, Extra infra = $5/client

---

### Low Usage (20 incidents/month, minimal support)

| Clients | Infra+Ops Share | AI Cost | Support | **Total / Client / Month** |
|---------|----------------|---------|---------|---------------------------|
| **0** | $200 total (idle stack, no clients) | — | — | **$200 total overhead** |
| **5** | $45.00 | $1.54 | $20–60 | **$67 – $107** |
| **10** | $25.00 | $1.54 | $20–60 | **$47 – $87** |
| **20** | $15.00 | $1.54 | $20–60 | **$37 – $77** |
| **50** | $9.00 | $1.54 | $20–60 | **$31 – $71** |
| **100** | $7.00 | $1.54 | $20–60 | **$29 – $69** |

---

### Medium Usage (80 incidents/month, moderate support)

| Clients | Infra+Ops Share | AI Cost | Support | **Total / Client / Month** |
|---------|----------------|---------|---------|---------------------------|
| **0** | $200 total (idle stack, no clients) | — | — | **$200 total overhead** |
| **5** | $45.00 | $6.16 | $40–120 | **$91 – $171** |
| **10** | $25.00 | $6.16 | $40–120 | **$71 – $151** |
| **20** | $15.00 | $6.16 | $40–120 | **$61 – $141** |
| **50** | $9.00 | $6.16 | $40–120 | **$55 – $135** |
| **100** | $7.00 | $6.16 | $40–120 | **$53 – $133** |

---

### High Usage (250 incidents/month, heavy support)

| Clients | Infra+Ops Share | AI Cost | Support | **Total / Client / Month** |
|---------|----------------|---------|---------|---------------------------|
| **0** | $200 total (idle stack, no clients) | — | — | **$200 total overhead** |
| **5** | $45.00 | $19.25 | $80–240 | **$144 – $304** |
| **10** | $25.00 | $19.25 | $80–240 | **$124 – $284** |
| **20** | $15.00 | $19.25 | $80–240 | **$114 – $274** |
| **50** | $9.00 | $19.25 | $80–240 | **$108 – $268** |
| **100** | $7.00 | $19.25 | $80–240 | **$106 – $266** |

---

## Quick Reference — Cost Type Cheat Sheet

| Cost | Fixed or Variable? | Shared or Per-Client? |
|------|-------------------|----------------------|
| App Server / Hosting | ✅ Fixed | Shared — split across clients |
| Database (PostgreSQL) | ✅ Fixed | Shared — split across clients |
| Vector Database | ✅ Fixed | Shared — split across clients |
| Monitoring & Alerts | ✅ Fixed | Shared — split across clients |
| CI/CD Tooling | ✅ Fixed | Shared — split across clients |
| Backups, SSL, DNS | ✅ Fixed | Shared — split across clients |
| Extra CPU/RAM per client | 📈 Scales with clients | Per client (~$5) |
| AI (Gemini) | 📈 Scales with usage | Per client (by incidents) |
| Support | 📈 Scales with usage | Per client (by hours) |

---

## Key Takeaways

1. **With 0 clients** you still pay **~$200/month** if the stack is running (turn it off to pay $0).
2. **The more clients you have, the cheaper it gets per client** — the fixed $200 base gets split.
3. **AI cost is very cheap** (~$0.08/incident) — even at 250 incidents/month it's only ~$19.
4. **Support is the largest variable cost** — optimize it with self-service tools, good docs, and automation.
5. **At 100 clients (medium usage)**, you're looking at roughly **$53–$133 per client/month**.
6. **One client = one company** with unlimited users. We don't charge per user.

---

## Appendix — Token Estimates per Agent Call

| Agent | Input Tokens | Output Tokens |
|-------|-------------|--------------|
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

---

*All pricing and token estimates are indicative. Verify with your actual usage and current [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) before finalizing commercial pricing.*
