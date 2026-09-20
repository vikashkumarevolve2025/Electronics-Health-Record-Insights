# EHR Data Ingestion Runbook

End-to-end steps for standing up the AWS infrastructure and ingesting baseline data, based on this project's setup. Follow in order for a clean setup; use the troubleshooting table at the end if something breaks.

---

## Part A — AWS Infrastructure Setup

### A1. Launch the EC2 instance

AWS Console → **EC2 → Instances → Launch instances**:
- **Name**: e.g. `test-EHR-Demo`
- **AMI**: Ubuntu Server 24.04 LTS (`ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-...`)
- **Instance type**: e.g. `c7i.flex.large` (size to your workload)
- **Key pair**: create or select an existing key pair (e.g. `test-EHR-key.pem`) — download and keep it safe, you need it for direct SSH access.
- **Network settings**: use an existing VPC/subnet, or default. Ensure **Auto-assign public IP** is enabled (or attach an Elastic IP after launch).
- **Security group**: create a new one (e.g. `EHR-Demo`) — rules configured in step A2.
- **Storage**: default is fine for testing.
- Click **Launch instance**.

### A2. Configure the security group

AWS Console → **EC2 → Security Groups** → select the group created above (e.g. `sg-08c148014fc125633`) → **Inbound rules → Edit inbound rules**. Add:

| Type | Protocol | Port | Source | Purpose |
|---|---|---|---|---|
| SSH | TCP | 22 | `<your-public-ip>/32` | Direct SSH from your machine |
| SSH | TCP | 22 | `18.206.107.24/29` (region-specific, this is `us-east-1`) | AWS EC2 Instance Connect (browser SSH) — optional |
| PostgreSQL | TCP | 5432 | `<your-public-ip>/32` | DB access from your machine |

Find your current public IP any time with:
```powershell
curl.exe -s https://api.ipify.org
```

**Note:** home/office IPs change periodically. If connections start timing out later, re-check your IP and update these rules — see the troubleshooting table.

Outbound rules can stay at the default (`All traffic` to `0.0.0.0/0`).

### A3. (Optional) Attach an Elastic IP

If you want a stable public IP across instance stops/starts: **EC2 → Elastic IPs → Allocate Elastic IP address**, then **Actions → Associate Elastic IP address** and select your instance. This project uses `52.72.181.18` as a fixed Elastic IP.

### A4. Connect to the instance

**Option A — Direct SSH with key pair (recommended, simplest):**
```powershell
ssh -i C:\path\to\test-EHR-key.pem ubuntu@<instance-public-ip>
```

**Option B — EC2 Instance Connect (browser-based, no key needed):**
EC2 Console → select instance → **Connect → EC2 Instance Connect → Connect**.
This requires:
- The IAM role/user has the `ec2-instance-connect:SendSSHPublicKey` permission (often *not* granted by default DevOps roles).
- The security group allows the AWS EC2 Instance Connect IP range (see A2) on port 22, since the key push originates from AWS's service IPs, not your laptop's IP.

If you get `AccessDeniedException` or `SendSSHPublicKey failed`, just use Option A instead.

### A5. Install and configure PostgreSQL on the instance

Once SSH'd in:

```bash
sudo apt update && sudo apt install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
sudo sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
sudo apt update
sudo apt install -y postgresql-14 postgresql-contrib-14
```

Create the database, user, and grant privileges:

```bash
sudo -u postgres psql -c "CREATE DATABASE ehr_db;"
sudo -i -u postgres psql
```
Inside the `psql` prompt:
```sql
CREATE USER fde_admin WITH PASSWORD 'YourSecurePasswordHere';
ALTER ROLE fde_admin SET client_encoding TO 'utf8';
ALTER ROLE fde_admin SET default_transaction_isolation TO 'read committed';
ALTER ROLE fde_admin SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE ehr_db TO fde_admin;
\c ehr_db
GRANT ALL ON SCHEMA public TO fde_admin;
\q
```

### A6. Allow remote connections to PostgreSQL

Edit the config files:
```bash
sudo nano /etc/postgresql/14/main/postgresql.conf
```
Set:
```
listen_addresses = '*'
```

```bash
sudo nano /etc/postgresql/14/main/pg_hba.conf
```
Add a line to allow remote password-authenticated connections:
```
host    all             all             0.0.0.0/0               scram-sha-256
```
(Prefer restricting to a specific CIDR instead of `0.0.0.0/0` where possible.)

**Restart is required** — editing config alone does not apply changes to the already-running server:
```bash
sudo systemctl restart postgresql@14-main
sudo ss -tlnp | grep 5432   # should show 0.0.0.0:5432, not 127.0.0.1:5432
```

### A7. Install pgvector extension (for embeddings)

```bash
sudo apt install -y postgresql-14-pgvector
sudo -u postgres psql -d ehr_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```
`CREATE EXTENSION` confirms success. A `could not change directory to "/home/ubuntu": Permission denied` line before it is a harmless warning (the `postgres` user can't `cd` into your home dir) and can be ignored.

Once enabled, you can add vector columns, e.g.:
```sql
ALTER TABLE patient_encounters ADD COLUMN IF NOT EXISTS clinical_embedding vector(768);
```

---

## Part B — Local Project Setup

### B1. Fix `requirements.txt` version conflicts

Already applied in this repo, but if you touch `requirements.txt` again, be aware:
- `nemoguardrails==0.24.1` does not exist on PyPI → use `nemoguardrails==0.17.0`.
- `pandas==3.0.5` conflicts with `nemoguardrails`/`streamlit` (`pandas<3` required) → use `pandas==2.2.3`.

### B2. Ensure `pip` is installed inside the venv

A fresh venv created with some tools (e.g. `uv`) may only contain `python.exe`, not `pip.exe`. If `pip install` inside the activated venv silently installs to your **global** Python instead of the venv, check:

```powershell
Get-ChildItem ehr-env/Scripts
```

If `pip.exe` is missing, bootstrap it:

```powershell
ehr-env/Scripts/python.exe -m ensurepip --upgrade
```

Always install using the venv's python explicitly to avoid ambiguity:

```powershell
ehr-env/Scripts/python.exe -m pip install -r requirements.txt
```

### B3. Configure `.env`

Create/confirm `.env` at the repo root (gitignored — never commit it):
```
DB_HOST=<instance-public-ip>
DB_PORT=5432
DB_NAME=ehr_db
DB_USER=fde_admin
DB_PASSWORD=<password>
```

### B4. SQLAlchemy driver fix

`create_engine("postgresql://...")` defaults to the `psycopg2` driver, but this project installs `psycopg` (v3) and `psycopg-binary`, not `psycopg2`. All scripts in `scripts/` (`01_ingest_baseline_data.py`, `02_verify_ingestion.py`, `03_apply_vector_schema.py`, and any new ones) must use the explicit driver:
```python
db_url = f"postgresql+psycopg://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
```

---

## Part C — Run the Ingestion

### C1. Run the ingestion script
```powershell
ehr-env/Scripts/python.exe scripts/01_ingest_baseline_data.py
```
This executes `src/database/schema.sql`, loads `data/MIMIC_IV_Trasncript.csv`, and inserts all rows into `patient_encounters` in a single transaction — no rows are visible until the whole insert completes; this is expected for large CSVs.

### C2. Verify ingestion
```powershell
ehr-env/Scripts/python.exe scripts/02_verify_ingestion.py
```
Or check the row count directly:
```powershell
ehr-env/Scripts/python.exe -c "import psycopg; conn = psycopg.connect('host=<ip> port=5432 dbname=ehr_db user=fde_admin password=<password>'); cur = conn.cursor(); cur.execute('SELECT count(*) FROM patient_encounters;'); print(cur.fetchone()); conn.close()"
```

### C3. Browse the data in VS Code

Use the **SQLTools** + **SQLTools PostgreSQL Driver** extensions (connection pre-configured in `.vscode/settings.json`, which is gitignored since it contains the DB password):
- Open the SQLTools icon in the Activity Bar → connect to "EHR AWS Postgres" → expand `ehr_db` → `public` → `patient_encounters` → right-click → **Show Table Records**.

## Troubleshooting quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'pandas'` after `pip install` | An earlier package in `requirements.txt` failed to resolve, aborting the whole install | Fix the failing pin, re-run install |
| `pip install` runs but packages aren't found later | `pip` was missing from the venv, install fell back to global Python | `ensurepip`, then install explicitly with venv's `python.exe -m pip` |
| `ModuleNotFoundError: No module named 'psycopg2'` | SQLAlchemy defaulted to psycopg2 dialect | Use `postgresql+psycopg://` in the connection string |
| `Test-NetConnection`/socket connect times out | Security group doesn't allow your current IP | Re-check IP with `curl.exe -s https://api.ipify.org`, update SG inbound rule |
| Socket connect refused (not timeout) | Security group is fine, but Postgres isn't listening on the public interface, or config wasn't reloaded | Check `listen_addresses`, restart `postgresql@14-main` |
| `SendSSHPublicKey` `AccessDeniedException` / "SendSSHPublicKey failed" | IAM role lacks `ec2-instance-connect:SendSSHPublicKey`, or SG doesn't allow the EC2 Instance Connect IP range on port 22 | Use direct SSH with `.pem` key instead (Part A4, Option A) |
| SOC/security team flags a `SendSSHPublicKey` denied event | Expected if you tried EC2 Instance Connect without the IAM permission | Respond confirming it was you, explain it was a denied troubleshooting attempt, and that you used the pre-issued key pair instead |
| `Test-NetConnection`/socket connect times out | Security group doesn't allow your current IP | Re-check IP, update SG inbound rule |
| Socket connect refused (not timeout) | Security group is fine, but Postgres isn't listening on the public interface, or hasn't been restarted after config change | Check `listen_addresses`, restart `postgresql@14-main` |
| `SendSSHPublicKey` `AccessDeniedException` | IAM role lacks `ec2-instance-connect:SendSSHPublicKey` | Use direct SSH with `.pem` key instead |
