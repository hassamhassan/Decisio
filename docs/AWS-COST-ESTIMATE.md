# Decisio — Approximate AWS Cost Estimate

Rough monthly (USD) costs for running Decisio on AWS. Prices are **approximate** and vary by region (e.g. us-east-1 vs eu-west-1). Use the [AWS Pricing Calculator](https://calculator.aws/) for your region and usage.

---

## Your stack (from docker-compose)

| Component   | Role                          |
|------------|---------------------------------|
| **API**    | FastAPI + React frontend, LLM (Groq), sentence-transformers |
| **Postgres** | PostgreSQL 16                 |
| **Qdrant** | Vector store (Decision Memory) |

**External (not AWS):** GROQ API for LLM — check [Groq pricing](https://groq.com/) separately.

---

## Option A: Single EC2 (simplest, lowest cost)

Run `docker compose` on one EC2 instance.

| Resource        | Example      | Approx. monthly (us-east-1) |
|-----------------|-------------|-----------------------------|
| EC2             | t3.medium (2 vCPU, 4 GB) | ~\$30 |
| EBS             | 30 GB gp3   | ~\$2.50                     |
| Elastic IP      | 1           | \$0 (while attached)        |
| **Subtotal**    |             | **~\$32–35**                |

- **Pros:** Simple, one machine, easy to match current Docker setup.
- **Cons:** No managed DB backups, single point of failure, you manage OS/patches.
- **Good for:** Dev, staging, or low-traffic production.

---

## Option B: ECS Fargate + RDS (managed, more scalable)

API and Qdrant as Fargate tasks; Postgres on RDS.

| Resource        | Example                    | Approx. monthly (us-east-1) |
|-----------------|----------------------------|-----------------------------|
| **Fargate – API**  | 1 vCPU, 2 GB (sentence-transformers) | ~\$36 |
| **Fargate – Qdrant** | 0.25 vCPU, 0.5 GB         | ~\$9  |
| **RDS PostgreSQL**  | db.t3.micro (1 vCPU, 1 GB) | ~\$22 (or Free Tier year 1) |
| **ALB**         | 1                          | ~\$16–20                    |
| **EBS (RDS)**   | 20 GB                      | ~\$2–3                      |
| **Subtotal**    |                            | **~\$85–90**                |

- **Pros:** Managed DB (backups, patches), scalable containers, no EC2 to maintain.
- **Cons:** Higher cost, more setup (VPC, ECS, RDS, ALB).
- **Good for:** Production with growth or compliance needs.

---

## Option C: Lightsail (fixed price, simple)

| Resource     | Example                    | Approx. monthly |
|-------------|----------------------------|------------------|
| Lightsail   | \$20 or \$40 box (2 GB / 4 GB) | \$20 or \$40   |
| Managed DB  | PostgreSQL \$15 plan (1 GB RAM) | \$15 (optional) |
| **Subtotal**|                            | **~\$35–55**     |

- **Pros:** Predictable price, simple, good for small apps.
- **Cons:** Less flexible than EC2/RDS; you still run Docker (or similar) yourself.

---

## What’s not included above

- **Data transfer:** Out to internet (e.g. ~\$0.09/GB after first 1 GB). Usually \$5–15/month for low traffic.
- **GROQ API:** Billed by Groq (not AWS); can be free tier or pay-per-use.
- **HTTPS:** Use ACM (free) with ALB or CloudFront.
- **Domain/DNS:** Route 53 ~\$0.50/month per hosted zone.
- **Secrets:** AWS Secrets Manager adds a few dollars per secret per month if you use it.

---

## Summary (approximate)

| Setup              | Approx. monthly (USD) | Best for              |
|--------------------|------------------------|------------------------|
| **Single EC2**     | **~\$32–40**           | Dev, staging, low traffic |
| **ECS + RDS**      | **~\$85–100**          | Production, scaling    |
| **Lightsail**      | **~\$35–55**           | Simple, fixed budget   |

All figures are **before** tax and are **estimates**; always confirm with [AWS Pricing](https://aws.amazon.com/pricing/) and the [AWS Pricing Calculator](https://calculator.aws/).
