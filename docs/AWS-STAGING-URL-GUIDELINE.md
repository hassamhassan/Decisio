# AWS Staging URL — Step-by-Step (No Custom Domain)

You have AWS access but **no domain**. This guide gives you a **detailed, step-by-step** path to a public **staging URL** using only AWS (no domain or DNS).

**Recommended:** **AWS App Runner** → you get `https://xxxxx.awsapprunner.com` as your staging URL (HTTPS, no domain).

---

## Part 1: Prerequisites (do this first)

### Step 1.1 — Install and configure AWS CLI

1. Install AWS CLI v2 (if not installed):
   - **Linux/macOS:** https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html  
   - Or: `curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip awscliv2.zip && sudo ./aws/install`
2. Configure credentials:
   ```bash
   aws configure
   ```
3. Enter when prompted:
   - **AWS Access Key ID:** (from IAM user or SSO)
   - **AWS Secret Access Key:** (from IAM user)
   - **Default region name:** `us-east-1` (or your preferred region)
   - **Default output format:** `json`
4. Verify:
   ```bash
   aws sts get-caller-identity
   ```
   You should see your Account ID and User ARN.

### Step 1.2 — Install Docker (if not installed)

- **Linux:** `sudo apt-get update && sudo apt-get install -y docker.io` (or use Docker’s install script).
- **macOS:** Install Docker Desktop from https://docker.com.
- Verify: `docker --version`

### Step 1.3 — Choose a region and set variables

Pick one region (e.g. `us-east-1`) and use it everywhere. Set these in your terminal (or in a script):

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_REPO=decisi-staging
```

---

## Part 2: Create the database (RDS PostgreSQL)

App Runner does not run a database; you need RDS (or another Postgres) for staging.

### Step 2.1 — Open RDS in AWS Console

1. Log in to **AWS Console** → search for **RDS** → open **RDS**.
2. Make sure the region (top-right) is the one you chose (e.g. **us-east-1**).

### Step 2.2 — Create database

1. Click **Create database**.
2. **Engine type:** **PostgreSQL**.
3. **Engine version:** **PostgreSQL 16** (or latest 16.x).
4. **Templates:** Choose **Free tier** (for staging) or **Dev/Test**.
5. **Settings:**
   - **DB instance identifier:** `decisi-staging-db`
   - **Master username:** `postgres` (or keep default).
   - **Master password:** Choose a strong password and **write it down** (e.g. in a password manager). You will need it for `DATABASE_URL`.
6. **Instance configuration:**
   - **Free tier:** db.t3.micro (or db.t4g.micro if available).
   - Otherwise: **Burstable** → **db.t3.micro**.
7. **Storage:** Leave default (e.g. 20 GiB gp2).
8. **Connectivity:**
   - **Compute resource:** Don’t connect to EC2 (we’ll use public access for staging).
   - **VPC:** Default VPC.
   - **Public access:** **Yes** (so App Runner can reach it; for staging only).
   - **VPC security group:** Create new → name e.g. `decisi-staging-rds-sg`.
   - **Availability Zone:** No preference (or pick one).
9. **Database authentication:** **Password authentication**.
10. **Additional configuration** (expand):
    - **Initial database name:** `decisio` (must match what the app uses).
    - Rest leave default.
11. Click **Create database**. Wait 5–10 minutes until status is **Available**.

### Step 2.3 — Allow inbound traffic to RDS (security group)

1. In **RDS** → **Databases** → click your DB identifier (`decisi-staging-db`).
2. Under **Connectivity & security**, click the **VPC security group** link (e.g. `decisi-staging-rds-sg`).
3. **Security group** → **Inbound rules** → **Edit inbound rules**.
4. **Add rule:**
   - **Type:** PostgreSQL (or Custom TCP).
   - **Port:** 5432.
   - **Source:** **Anywhere-IPv4** (`0.0.0.0/0`) for staging. (Restrict in production.)
5. **Save rules**.

### Step 2.4 — Get the RDS endpoint and build DATABASE_URL

1. Back in **RDS** → **Databases** → click `decisi-staging-db`.
2. Under **Connectivity & security**, copy **Endpoint** (e.g. `decisi-staging-db.xxxxxx.us-east-1.rds.amazonaws.com`).
3. Build your connection string (replace with your password and endpoint):
   ```text
   postgresql://postgres:YOUR_RDS_PASSWORD@decisi-staging-db.xxxxxx.us-east-1.rds.amazonaws.com:5432/decisio
   ```
4. Save this as `DATABASE_URL`; you will use it in App Runner.

---

## Part 3: Build and push the Docker image to ECR

All commands below are from your **Decisio project root** (where `Dockerfile` and `api.py` are).

### Step 3.1 — Create ECR repository

```bash
aws ecr create-repository --repository-name $ECR_REPO --region $AWS_REGION
```

If you see "RepositoryAlreadyExistsException", the repo exists; continue.

### Step 3.2 — Log in Docker to ECR

```bash
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

Expected: `Login Succeeded`.

### Step 3.3 — Build the image

From the **project root** (where `Dockerfile` is):

```bash
docker build -t decisio:latest .
```

Wait for the build to finish (several minutes). Fix any build errors (e.g. missing files, failed npm/pip steps).

### Step 3.4 — Tag the image for ECR

```bash
docker tag decisio:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest
```

### Step 3.5 — Push the image to ECR

```bash
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest
```

Wait for the push to complete. You can confirm in the console: **ECR** → **Repositories** → `decisi-staging` → **Images**.

---

## Part 4: Create the App Runner service

### Step 4.1 — Open App Runner

1. In **AWS Console**, search for **App Runner** → open **App Runner**.
2. Region = same as above (e.g. **us-east-1**).

### Step 4.2 — Create service

1. Click **Create service**.

### Step 4.3 — Source and deployment

1. **Repository type:** **Container registry**.
2. **Provider:** **Amazon ECR**.
3. **Container image URI:** Click **Browse** and select:
   - **Image repository:** `decisi-staging`
   - **Image tag:** `latest`
   (Or paste the full URI: `ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/decisi-staging:latest`.)
4. **Deployment settings:** **Automatic** (deploy on image push). Or **Manual** for now.
5. Click **Next**.

### Step 4.4 — Configure service

1. **Service name:** `decisi-staging` (or any name).
2. **Virtual CPU:** **1 vCPU** (or 0.5 for light staging).
3. **Virtual memory:** **2 GB** (or 1 GB for light staging).
4. **Environment variables** — Click **Add environment variable** and add **each** of these (replace placeholders with your real values):

   | Key | Value |
   |-----|--------|
   | `DATABASE_URL` | `postgresql://postgres:YOUR_RDS_PASSWORD@YOUR_RDS_ENDPOINT:5432/decisio` |
   | `JWT_SECRET_KEY` | Output of: `openssl rand -hex 32` |
   | `OPENAI_API_KEY` | Your OpenAI API key (if using OpenAI) |
   | or `GROQ_API_KEY` | Your Groq API key (if using Groq) |

   **Important:** For `DATABASE_URL`, use the exact endpoint and password from Part 2. No spaces; one line.

   **WS_BASE_URL:** Leave empty for the first deploy. After you get the App Runner URL, you can redeploy and set:
   `WS_BASE_URL` = `https://YOUR_APP_RUNNER_DEFAULT_DOMAIN`

5. **Leave** other settings as default (no VPC connector for the simple staging setup with public RDS).
6. Click **Next**.

### Step 4.5 — Auto scaling (optional)

- **Min size:** 1 (so the app is always running).
- **Max size:** 2 or 3 for staging.
- Click **Next**.

### Step 4.6 — Review and create

1. Review **Summary**.
2. Click **Create & deploy service**.
3. Wait until **Status** is **Running** (about 5–10 minutes). You can watch **Deployments** for the latest deployment status.

### Step 4.7 — Get your staging URL

1. In **App Runner** → **Services** → click **decisi-staging**.
2. On the service page, find **Default domain** (e.g. `abc123xyz.us-east-1.awsapprunner.com`).
3. Your **staging URL** is: **https://** + that domain (e.g. `https://abc123xyz.us-east-1.awsapprunner.com`).
4. Copy this URL and share it with your manager. It is **HTTPS** and works without any domain.

### Step 4.8 — (Optional) Set WS_BASE_URL for WebSocket

1. In the same service → **Configuration** tab → **Edit** (under “Configure service”).
2. Add (or edit) environment variable: **Key:** `WS_BASE_URL`, **Value:** `https://YOUR_DEFAULT_DOMAIN` (e.g. `https://abc123xyz.us-east-1.awsapprunner.com` — no trailing slash).
3. Save. App Runner will redeploy; wait until **Running** again.

---

## Part 5: Create the first user (staging)

Once the App Runner service is **Running** and the default domain opens in the browser:

1. On your **local machine** (from the Decisio project root), run (replace with your real staging URL and password):
   ```bash
   API_URL=https://YOUR_APP_RUNNER_DEFAULT_DOMAIN ./scripts/seed-initial-admin.sh admin YourStagingPassword
   ```
   Example:
   ```bash
   API_URL=https://abc123xyz.us-east-1.awsapprunner.com ./scripts/seed-initial-admin.sh admin MyStagingPass123
   ```
2. If you see “Success”, open the staging URL in a browser and log in with **admin** / **YourStagingPassword**.
3. Share the **staging URL** and **login credentials** with your manager securely (e.g. password manager or secure channel).

---

## Part 6: Optional — EC2 path (HTTP only, single server)

If you prefer **one EC2** with Docker Compose and are OK with **HTTP** and an **IP:port** URL:

### Step 6.1 — Launch EC2

1. **EC2** → **Launch instance**.
2. **Name:** `decisi-staging`.
3. **AMI:** **Amazon Linux 2023** or **Ubuntu 22.04 LTS**.
4. **Instance type:** **t3.small** (or t3.micro for light use).
5. **Key pair:** Create new or select existing; **download .pem** and keep it safe.
6. **Network settings:** Create security group; allow:
   - **SSH (22)** from your IP (or 0.0.0.0/0 for staging).
   - **Custom TCP 8000** from **0.0.0.0/0** (so the app is reachable).
7. **Storage:** 20 GiB gp3.
8. **Launch instance**.

### Step 6.2 — Allocate Elastic IP (so URL does not change)

1. **EC2** → **Elastic IPs** → **Allocate Elastic IP address** → **Allocate**.
2. Select the new IP → **Actions** → **Associate Elastic IP address** → choose instance `decisi-staging` → **Associate**.
3. Note the **Public IPv4** (e.g. `54.123.45.67`). Staging URL will be `http://54.123.45.67:8000`.

### Step 6.3 — SSH and install Docker

```bash
ssh -i /path/to/your-key.pem ec2-user@YOUR_EC2_PUBLIC_IP
```

(For Ubuntu, user is often `ubuntu` instead of `ec2-user`.)

**Amazon Linux 2023:**

```bash
sudo yum update -y
sudo yum install -y docker
sudo systemctl start docker && sudo systemctl enable docker
sudo usermod -aG docker ec2-user
exit
```

Log in again via SSH so the `docker` group applies. Verify: `docker run hello-world`.

### Step 6.4 — Copy project and run with Docker Compose

**Option A — Clone from Git (if project is in a repo):**

```bash
sudo yum install -y git
git clone YOUR_REPO_URL decisio && cd decisio
```

**Option B — Copy files from your machine (rsync):**

From your **local** machine (not on EC2):

```bash
rsync -avz -e "ssh -i /path/to/your-key.pem" --exclude node_modules --exclude venv --exclude .git . ec2-user@YOUR_EC2_PUBLIC_IP:~/decisio/
```

Then on EC2:

```bash
cd ~/decisio
```

**Create .env on the server:**

```bash
nano .env
```

Add (adjust keys as needed):

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/decisio
JWT_SECRET_KEY=your-strong-secret-here
OPENAI_API_KEY=your-openai-key
```

Save (Ctrl+O, Enter, Ctrl+X).

**Run the stack (no vector store):**

```bash
docker compose -f docker-compose.no-vectorstore.yml up -d --build
```

Wait for containers to be up: `docker compose -f docker-compose.no-vectorstore.yml ps`.

### Step 6.5 — Open the app and create first user

- **Staging URL:** `http://YOUR_ELASTIC_IP:8000` (e.g. `http://54.123.45.67:8000`).
- From your **local** machine:
  ```bash
  API_URL=http://YOUR_ELASTIC_IP:8000 ./scripts/seed-initial-admin.sh admin YourPassword
  ```
- Share the URL and credentials with your manager. This is **HTTP only**.

---

## Quick reference

| Step | What you do | Result |
|------|-------------|--------|
| 1 | Prerequisites | AWS CLI, Docker, region set |
| 2 | RDS | PostgreSQL DB + endpoint + security group |
| 3 | ECR + Docker | Image in `decisi-staging` repo |
| 4 | App Runner | Service with env vars → **Default domain** |
| 5 | Seed user | First login for staging |
| **Staging URL** | **https://YOUR_APP_RUNNER_DEFAULT_DOMAIN** | Share with manager |

---

## Troubleshooting

- **App Runner: “Service unavailable” or 500:** Check **Logs** in App Runner (CloudWatch). Often `DATABASE_URL` wrong or RDS not reachable (security group / public access).
- **Can’t connect to RDS:** Ensure RDS has **Public access = Yes** and security group allows **5432** from **0.0.0.0/0** for staging.
- **Login fails after seed:** Confirm `API_URL` used in `seed-initial-admin.sh` is exactly the App Runner default domain (with `https://`).
- **EC2: “Connection refused” on 8000:** Check security group allows **8000** from 0.0.0.0/0 and containers are running: `docker compose ps`.

---

*Use the same region everywhere. Replace placeholders (YOUR_RDS_PASSWORD, YOUR_APP_RUNNER_DEFAULT_DOMAIN, etc.) with your actual values.*
