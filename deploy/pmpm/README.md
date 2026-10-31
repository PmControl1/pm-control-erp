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

- **Size:** 4 vCPU, 8 GB RAM, 80 GB+ disk is plenty for the pilot. Ubuntu 24.04.
- **Where:** in the EU (the firm's data stays under GDPR without extra
  paperwork). Any provider works; Hetzner (Germany/Finland) and the Bulgarian
  hosts are the usual choices.
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

The repository is private, so its images are too. Give the server read access
once with a GitHub **classic** personal access token that has only the
`read:packages` scope (github.com → Settings → Developer settings → Personal
access tokens → Tokens (classic)):

```bash
docker login ghcr.io -u PmControl1     # paste the token as the password
```

Start it:

```bash
./deploy.sh
```

Then **immediately** open `https://<your domain>` and register your own
account. The first account becomes the admin; after that, sign-up is closed
and you add the firm's people from the admin pages.

## 3. Backups (do this before any real project goes in)

1. Create a storage bucket somewhere other than the server: Hetzner Object
   Storage, Backblaze B2 (EU region), or any S3-compatible service. Create an
   access key limited to that bucket.
2. Fill in the `RESTIC_*` and `AWS_*` lines in `.env`. Generate
   `RESTIC_PASSWORD` with `openssl rand -base64 32` and **save a copy in your
   password manager**: without it the backups cannot be read, and a copy that
   only lives on the server dies with the server.
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
   throwaway database and compares it with the live one. It does not touch the
   live platform:
   ```bash
   ./restore.sh --test
   ```
   Repeat this every month or so. A backup nobody has restored is a hope.
6. Optional but recommended: create a free check at healthchecks.io, put its
   URL in `BACKUP_PING_URL`, and you'll get an email when a night is missed.

What is backed up: the whole database and the files volume (uploaded
documents, drawings, generated PDFs). Kept: 14 daily, 8 weekly, 12 monthly
snapshots, encrypted. Logs of each run: `journalctl -u pmpm-backup`.

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
`docker compose up -d` in this folder. Caddy serves `https://localhost` with
its own local certificate (the browser warns once).

## Licence

The platform is AGPL-3.0. Once anyone outside the firm uses this server, they
must be able to get its source code: make the repository public, or give them
access to it, and set `BRAND_SOURCE_URL` in `frontend/src/shared/brand.ts`.
