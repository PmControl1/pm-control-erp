# Running PM Project Management on a server

This folder is everything the production server needs. The server never
builds anything: GitHub Actions builds the image on every merge to `main`
(`.github/workflows/pmpm-ci.yml`) and the server pulls it.

| File | What it does |
|---|---|
| `docker-compose.yml` | Database, app and Caddy (HTTPS). Bulgaria pack on, demo data off. |
| `Caddyfile` | HTTPS with an automatic Let's Encrypt certificate. |
| `.env.example` | Every setting. Copy to `.env` on the server. |
| `deploy.sh` | Back up, pull the newest image, restart, wait until it answers. |
| `backup.sh` | Database dump + uploaded files into an encrypted off-server backup. |
| `restore.sh` | List backups, test-restore one safely, or restore for real. |
| `systemd/` | Runs `backup.sh` every night. |

## 1. The server

- **Size:** start with 4 vCPU, 8 GB RAM and 80 GB+ disk on Ubuntu 24.04;
  monitor disk space and memory as documents and BIM models accumulate.
- **Architecture:** choose an **x86-64 / amd64** server. The CI image is built
  for `linux/amd64`; Hetzner's ARM servers require a separately verified ARM
  image.
- **Where:** select a Hetzner location in Germany or Finland, and an EU region
  for the backup bucket. EU hosting alone does **not** establish GDPR
  compliance. Conclude Hetzner's [data processing agreement](https://docs.hetzner.com/general/company-and-policy/data-protection-at-hetzner/)
  when processing personal data on the firm's behalf. Before real documents,
  assess the lawful basis, notices, retention, access rights, breach response
  and contracts for every processor (including email, backups and AI). See
  the [European Commission's obligations guidance](https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/obligations_en).
  This runbook verifies deployment mechanics, not legal compliance.
- **Domain:** pick the address people will use, e.g. `app.pmpm.bg`, and create
  a DNS **A record** pointing it at the server's IP. Do this first: the HTTPS
  certificate can only be issued once the name resolves.

## 2. First setup (about 20 minutes)

On the server, as root:

```bash
# Docker
curl -fsSL https://get.docker.com | sh

# Firewall: SSH, HTTP (certificate checks and the redirect), HTTPS
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

mkdir -p /opt/pmpm
```

From your PC (PowerShell, in the repository folder), copy this folder up:

```powershell
scp -r deploy/pmpm/* deploy/pmpm/.env.example root@SERVER_IP:/opt/pmpm/
```

Back on the server:

```bash
cd /opt/pmpm
chmod +x *.sh
cp .env.example .env && chmod 600 .env
nano .env        # fill in domain, emails, and two secrets: openssl rand -hex 32
```

The shell scripts source `.env` as shell assignments. Single-quote values
containing spaces or shell characters, for example
`SMTP_PASSWORD='literal password with $ signs'`. Do not put commands in `.env`.

The repository is private, so its images are too. Give the server read access
once with a GitHub **classic** personal access token that has only the
`read:packages` scope (github.com → Settings → Developer settings → Personal
access tokens → Tokens (classic)):

```bash
docker login ghcr.io -u PmControl1     # paste the token as the password
```

Bootstrap the administrator **before Caddy exposes the app publicly**. The
closed registration mode still allows the first account to become admin.
Leave `PMPM_PLATFORM_OWNER_USER_IDS` blank for this private step: no account
can manage Workspace AI until the server operator explicitly configures it.
Start only the database and app; neither publishes a host port:

```bash
docker compose pull
docker compose up -d --wait --wait-timeout 600 postgres app
docker compose exec app python -c '
import getpass, json, urllib.request
email = input("Administrator email: ").strip()
name = input("Administrator full name: ").strip()
password = getpass.getpass("Administrator password (at least 12 characters): ")
payload = json.dumps({"email": email, "full_name": name, "password": password, "locale": "bg"}).encode()
request = urllib.request.Request("http://localhost:8080/api/v1/users/auth/register/", data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=60) as response:
    user = json.load(response)
assert user["role"] == "admin", "Bootstrap did not create an administrator"
print("Administrator created. Set PMPM_PLATFORM_OWNER_USER_IDS=" + user["id"] + " in .env before public deployment.")
'

# Paste the printed UUID into PMPM_PLATFORM_OWNER_USER_IDS. The UUID, not the
# email address or administrator role alone, identifies the platform owner.
nano .env
./deploy.sh
```

If registration is rejected, correct the supplied account details and repeat
the registration command before starting Caddy. Once the administrator exists,
open `https://<your domain>` and sign in; add the firm's people from the admin
pages. Confirm a second public registration is refused.

`deploy.sh` recreates the app with the configured UUID list and verifies that
at least one listed account is an active administrator before starting Caddy.
Only those accounts can read or change Workspace AI settings; other staff
administrators can still use the shared AI. Keep at least one active listed
owner. The allowlist is a server setting, not a setting editable by staff.
Use comma-separated UUIDs to appoint more than one owner.

### Existing installations and owner recovery

The previous `PMPM_PLATFORM_OWNER_EMAILS` setting no longer grants ownership.
Before updating, stop the public proxy and find the intended existing owner
account's UUID privately:

```bash
docker compose stop caddy
docker compose exec app python -c '
import asyncio
from app.database import async_session_factory
from app.modules.users.repository import UserRepository

email = input("Existing owner administrator email: ").strip()
async def lookup():
    async with async_session_factory() as session:
        user = await UserRepository(session).get_by_email(email)
        if user is None or not user.is_active or user.role != "admin":
            raise SystemExit("Choose an existing active administrator account.")
        print("PMPM_PLATFORM_OWNER_USER_IDS=" + str(user.id))
asyncio.run(lookup())
'
nano .env          # add the printed UUID; remove PMPM_PLATFORM_OWNER_EMAILS
./deploy.sh
```

If no active administrator remains, use the existing server CLI to recover
the intended existing account before the lookup:
`docker compose exec app python -m app.cli promote-admin owner@firm.bg`.
For a wrong or missing UUID list, correct `.env` and run `./deploy.sh` again.
Changing an account email does not transfer ownership; deleting and recreating
an account produces a different UUID and requires the operator to update the
list. A blank or malformed list grants ownership to nobody. The existing
shared AI continues serving employees even when no owner is configured.

## 3. Backups (do this before any real project goes in)

1. Create a storage bucket somewhere other than the server: Hetzner Object
   Storage, Backblaze B2 (EU region), or any S3-compatible service. Create an
   access key limited to that bucket.
2. Fill in the `RESTIC_*` and `AWS_*` lines in `.env`. Generate
   `RESTIC_PASSWORD` with `openssl rand -base64 32` and **save a copy in your
   password manager**: without it the backups cannot be read, and a copy that
   only lives on the server dies with the server.
   Keep an encrypted off-server copy of `.env` and the deployment files as
   well: the data backup does not contain the database password, JWT secret,
   bucket credentials or other server configuration.
3. Run the first backup by hand. It creates the backup repository:
   ```bash
   ./backup.sh
   ```
4. Run it every night:
   ```bash
   cp systemd/pmpm-backup.* /etc/systemd/system/
   systemctl daemon-reload && systemctl enable --now pmpm-backup.timer
   systemctl list-timers pmpm-backup.timer      # shows the next run
   ```
5. **Prove a restore works.** This restores the newest backup into a
   throwaway database, checks its files, and prints restored/live counts for
   inspection. It does not change the live database or files; counts may differ
   if data changed since the backup:
   ```bash
   ./restore.sh --test
   ```
   Repeat this every month or so. A backup nobody has restored is a hope.
6. Optional but recommended: create a free check at healthchecks.io, put its
   URL in `BACKUP_PING_URL`, and you'll get an email when a night is missed.

What is backed up: the whole database and the files volume (uploaded
documents, drawings, generated PDFs). Kept: 14 daily, 8 weekly, 12 monthly
snapshots, encrypted. Logs of each run: `journalctl -u pmpm-backup`.
The app is stopped while the database and files are captured and uploaded
together; downtime depends on data size and upload speed. It restarts before
retention and integrity checks. Deploy, backup and restore share a maintenance
lock so they cannot modify the stack concurrently.

## 4. Updating

Merge to `main` → CI tests it and pushes the image → on the server:

```bash
cd /opt/pmpm && ./deploy.sh
```

`deploy.sh` backs up first. Each image is also tagged with its commit, so to
go back to an earlier build:

```bash
./deploy.sh sha-<commit>      # e.g. the previous merge's commit hash
```

If the bad version changed data, restore the backup `deploy.sh` took before
the update: `./restore.sh --list`, then `./restore.sh <ID>`.

## 5. Everyday commands

```bash
docker compose ps                  # what is running
docker compose logs -f app         # the app's log
./restore.sh --list                # the backups there are
docker compose exec app python -m app.cli promote-admin someone@firm.bg
```

## Running the same stack on your PC

With Docker Desktop, set `PMPM_DOMAIN=localhost` in `.env` and run
the same private administrator bootstrap, then set `PMPM_PLATFORM_OWNER_USER_IDS`
before starting Caddy. Caddy serves
`https://localhost` with its own local certificate (the browser warns once).

## Pilot checks on the real server

CI tests the production image against PostgreSQL and verifies the bundled UI.
Before real project data, also verify DNS and a valid HTTPS certificate on the
actual domain, login and a second sign-up refusal, SMTP delivery/password reset,
an upload that survives an app recreation, and an off-server backup followed by
`./restore.sh --test`. Import a representative firm КСС into an EUR project and
compare quantities, units, totals and the retained BGN rates with the workbook.
Keep the development AI phase limited to synthetic documents; verify the
chosen production provider and its data-processing terms before enabling AI
for real documents.

Also confirm the designated owner can save/test Workspace AI, while a staff
administrator and an ordinary employee can use AI but cannot read or change
the owner configuration. This is the single-company pilot's owner boundary;
separate customer isolation remains tracked in issue #28.

## Licence

The platform is AGPL-3.0. Once anyone outside the firm uses this server, they
must be able to get its source code: make the repository public, or give them
access to it, and set `BRAND_SOURCE_URL` in `frontend/src/shared/brand.ts`.
