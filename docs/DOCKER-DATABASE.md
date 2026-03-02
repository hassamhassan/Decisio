# Database in Docker and Adding Data

## 1. Database in Docker

The database is **PostgreSQL** and is already defined in `docker-compose.yml`:

- **Service:** `postgres`
- **Image:** `postgres:16-alpine`
- **Database name:** `decisio`
- **User / password:** `postgres` / `postgres`
- **Port:** `5432` (mapped to host)
- **Data:** Stored in Docker volume `postgres_data` (persists across restarts)

When you run `docker compose up -d`, Postgres starts and creates the `decisio` database. The **API container** runs `alembic upgrade head` on startup, which creates/updates all tables (users, companies, incidents, equipment, escalation levels, etc.).

You don’t need to “add” the database manually; it’s created when the stack starts.

---

## 2. Adding Data

### Option A: First user (super admin) via script

After the stack is running, create the first user (super_admin) once:

```bash
# Default: username admin, password admin
./scripts/seed-initial-admin.sh

# Or with custom username and password
./scripts/seed-initial-admin.sh myadmin mypassword
```

This calls `POST /api/auth/register`, which creates the default company and the first super_admin. Then log in at http://localhost:8000 and use the Super Admin dashboard to create companies and company admins.

### Option B: First user via curl

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@localhost","password":"admin","full_name":"Super Admin"}'
```

### Option C: Load custom SQL (bulk data)

To run your own SQL (e.g. seed data, fixes):

```bash
# From host, pipe a SQL file into Postgres
docker exec -i decisio-postgres psql -U postgres -d decisio < my-data.sql
```

Or open a shell and run `psql`:

```bash
docker exec -it decisio-postgres psql -U postgres -d decisio
```

### Option D: Init script on first DB creation (optional)

If you want SQL to run **only the first time** the Postgres volume is created, you can mount a script into the Postgres image’s init directory. Add to the `postgres` service in `docker-compose.yml`:

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data
  - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/01-init.sql
```

Create `scripts/init-db.sql` with your SQL (e.g. extra roles or extensions). This runs only when the data directory is empty. **Tables** are still created by the API’s Alembic migrations, so use init SQL only for things that must exist before the API starts (e.g. extensions), not for app tables.

---

## 3. Connect from your machine

- **From host:** `psql -h localhost -p 5432 -U postgres -d decisio` (password: `postgres`)
- **From another container on the same compose network:** use hostname `postgres`, port `5432`, same user/pass and database name.

---

## 4. Summary

| Step | Action |
|------|--------|
| Start stack | `docker compose up -d` |
| Tables created | Automatically by API on startup (`alembic upgrade head`) |
| First user | Run `./scripts/seed-initial-admin.sh` (or curl above) |
| Custom SQL | `docker exec -i decisio-postgres psql -U postgres -d decisio < file.sql` |
