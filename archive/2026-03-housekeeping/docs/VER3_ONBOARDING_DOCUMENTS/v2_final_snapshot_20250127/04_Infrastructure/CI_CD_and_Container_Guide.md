# CI/CD & Container Guide – REC.IO v2

## Purpose
Define the build, test, and deployment flow for REC.IO v2, optimized for local-first development and production deployment on DigitalOcean. Prepares the path for v3 containerization while maintaining current v2 processes.

---

## 1. Development Workflow (Local-First)
1. **Clone Repo** → Work in feature branch from `main`
2. **Local Environment**:
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   export APP_ENV=local
   source v2_final_snapshot_20250127/02_Config/env_files/local.env
   supervisord -c supervisor.conf
   ```
3. **Run Unit Tests** (pytest or equivalent)
4. **Manual Integration Test**: Start services via supervisor, confirm:
   - Main app loads (port 3000)
   - BTC price feed active
   - Kalshi API reachable

---

## 2. CI/CD Flow (v2 DigitalOcean Deployment)
**Trigger:** Manual (BMAD operator) after PR merge to `main`

**Steps:**
1. **Push Code** → GitHub main branch
2. **Build Artifacts** (optional Docker step for v2)
3. **SSH Deploy to DigitalOcean Droplet**:
   ```bash
   ssh user@droplet-ip
   cd /opt/rec_io_v2
   git pull origin main
   source venv/bin/activate
   pip install -r requirements.txt --upgrade
   supervisorctl reread && supervisorctl update && supervisorctl restart all
   ```
4. **Verify** using Health Checks (see Deployment Playbook)

---

## 3. DigitalOcean Droplet Setup (v2)
- **OS:** Ubuntu LTS
- **Users:** `svc_rec` for running services (non-root)
- **Python:** Installed via apt + venv
- **Supervisor:** `/etc/supervisor/conf.d/*.conf` from `04_Infrastructure/supervisor/`
- **PostgreSQL:** Managed instance or local (v2 uses local unless specified)
- **Firewall:** Allow required ports only (main_app, SSH, any APIs needed for external access)

---

## 4. Optional Docker Packaging (for v2 → v3 transition)
While v2 does not require containers, BMAD may package the app for portability:
**Dockerfile Example**:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV APP_ENV=production
CMD ["supervisord", "-c", "/app/supervisor.conf"]
```

**Build & Run Locally**:
```bash
docker build -t rec_io_v2 .
docker run -d --env-file v2_final_snapshot_20250127/02_Config/env_files/local.env -p 3000:3000 rec_io_v2
```

---

## 5. v3-Ready CI/CD Considerations
- **GitHub Actions / CI Pipelines**:
  - Lint & test on push/PR
  - Build Docker image on merge
  - Push to private container registry
- **Deployment Options**:
  - DigitalOcean App Platform (direct from repo or registry)
  - Fly.io or Render as alternatives
- **Local-first parity**: Containers run locally the same way they do in prod

---

## 6. Rollback Strategy (DigitalOcean)
- Keep last 2 releases in `/opt/releases`
- Symlink `/opt/rec_io_v2` → current release
- To rollback:
  ```bash
  ln -sfn /opt/releases/<previous_release> /opt/rec_io_v2
  supervisorctl restart all
  ```

---

## 7. Checklist Before Deploy
- [ ] All tests pass locally
- [ ] `.env` files updated & committed to secure store
- [ ] Supervisor configs match manifest/config
- [ ] Droplet storage & memory usage < 80%
- [ ] DB backup completed in last 24h
