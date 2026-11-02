# PM Project Management — internal shared AI pilot

**Scope: single-company installation, synthetic data only. NOT a multi-tenant
SaaS launch and NOT suitable for external customer accounts.**

## What works in this first slice

- One server-managed DeepSeek API credential, available to individually
  approved internal user accounts only; users cannot view/download the key.
- Explicit administrator grant/revoke in **User Management**. A Viewer may not
  be granted, because the existing `ai.use` permission starts at Editor.
- Existing per-user API keys continue to work. Shared credentials are only
  used if the user has no usable personal key.
- Fail-closed when the internal mode is disabled, registration is not `closed`,
  demo seeding is enabled, a user has no grant or the credential is missing.
- Regular global environment-based provider fallbacks are blocked while this
  internal pilot mode is enabled, so they cannot bypass the grant list.
- DeepSeek's model identifier defaults to the current `deepseek-flash`.

## Configure the isolated local Docker deployment

In `deploy/pmpm/.env` on the trusted host, set:

```dotenv
PMPM_INTERNAL_AI_PILOT=true
PMPM_INTERNAL_DEEPSEEK_API_KEY=PUT_YOUR_DEEPSEEK_KEY_HERE
PMPM_REGISTRATION_MODE=closed
```

**Do not commit this file, paste its contents into chat, or share the output of
`docker compose config`**: Docker Compose interpolates the plaintext key.
The production compose sets `SEED_DEMO=false` and passes the two pilot values
to the backend process. Limit access to the host and its backups.

Apply without deleting database volumes:

```powershell
cd $HOME\pm-control-erp\deploy\pmpm
git pull origin main
docker compose pull app
docker compose up -d --no-deps --force-recreate app
docker compose ps
```

The company-admin logs into the ERP, opens **User Management**, and finds
**Shared company AI — internal test**. Enable individual active Editor/Manager
accounts. The key is not inserted in the employee's per-user settings row.
When revoked, the shared credential is no longer resolved on new AI requests.

The account's own `ai.use` permission is still required by API routes.
Review and test unusual AI modules separately before expanding pilot access.

## Known limitations / commercialization blockers

1. This installation does not yet have genuine organizations, memberships or
   tenant-scoped authorization. All users on the instance are assumed to be
   internal employees. **Never create external client accounts on this pilot.**
2. Existing AI request rate limiting and some estimate token/cost records are
   not a durable per-company metering/budget service. There are no guaranteed
   monthly spending caps or customer invoices in this PR.
3. AI modules beyond the primary client may use their own provider paths.
   Verify every AI path before promising a company-wide quota or cost cap.
4. The company key is a backend environment variable, not a separate vault,
   and is available to anyone with Docker/host admin access. Secure backups,
   workstation, environment and key rotation.
5. There is no automatic classification of synthetic vs real inputs. Users must
   follow the synthetic-only data policy for DeepSeek.
6. The existing ERP still needs a verified migration/recovery plan, project and
   document isolation tests, and GDPR assessment for genuine company data.

## Commercial design, next milestones

Before opening registration to unrelated paying customers:

1. Create Organizations and Memberships (role within organization), propagate
   `organization_id` from authenticated membership rather than trusting a
   client-controlled header, and default-deny missing membership.
2. Scope all projects, documents, searches, agents and AI settings to an
   organization; add negative cross-organization IDOR, storage and search tests.
3. Store encrypted per-organization AI credentials (with a managed platform
   provider and optional customer BYOK), rotate them independently of JWT.
4. Route ALL provider calls through one server-side gateway with atomic,
   persistent per-user/organization usage reservations, reconciled actual
   token/cost records, quotas, provider budgets and audit logs.
5. Add subscription metering/invoicing, customer limits, consent/processor
   controls, regional provider policy and separation of dev/synthetic from
   prod/customer documents. Roll out behind a feature flag.
