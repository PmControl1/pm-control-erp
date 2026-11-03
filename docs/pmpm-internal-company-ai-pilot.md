# Company AI on an internal PM installation

The owner selects the provider, model and key once in **Settings → AI → Company AI**.
Approved employees use the existing AI tools with that configuration. The grant
allows the employee to use the company provider wherever their existing ERP
permissions allow. It does not grant access to projects, folders or documents.
This pilot is for one company on a closed installation. Use synthetic inputs
for the DeepSeek pilot.

## Enable owner management

Use an ERP image built from this branch or a release containing these changes.
From the existing installation's `deploy/pmpm` directory, find your own
administrator account UUID. This read-only command lists active administrators.

```powershell
docker compose exec postgres psql -U oe -d openestimate -c "SELECT id, email FROM oe_users_user WHERE role = 'admin' AND is_active ORDER BY email"
```

In the host's private `deploy/pmpm/.env`, set these values, replacing the UUID
placeholder with your account ID. Keep the provider key for entry in the UI.

```dotenv
PMPM_INTERNAL_AI_PILOT=true
PMPM_AI_OWNER_USER_ID=<your-administrator-account-uuid>
PMPM_REGISTRATION_MODE=closed
```

The PM compose file already sets `SEED_DEMO=false`. Recreate the application
container to load the owner setting with the intended image.

```powershell
docker compose up -d --no-deps --force-recreate app
```

1. Sign in as the designated owner. Open **Settings → AI → Company AI**.
2. Select **OpenAI** or **DeepSeek**, enter a model ID available to your provider
   account and the corresponding API key, save, then test the saved connection.
   Leave the key blank to keep it when editing the model. Switching providers
   requires its own key.
3. Under **Team access**, find a team by project and team name. Grant access
   to its current eligible members. New and re-added members are pending until
   the owner approves the current roster again. Removing a member or revoking a
   team ends access through that team on the next request. Another approved team
   may still grant that employee access. Viewer and inactive accounts are ineligible.
4. Sign in as an approved employee and try an existing AI feature using a sample
   project. Repeat with an unapproved account, then revoke the first team's
   access and try a new request. Employees never enter the company key.

The provider must support the feature being used. For example, the existing
audio transcription integration uses OpenAI; with DeepSeek selected the manual
transcript path is still available.

## Credentials and backups

The saved key is encrypted with the ERP's secret encryption mechanism and
stored under `OE_DATA_DIR/.pmpm/company-ai.sqlite3` (normally
`/data/.pmpm/company-ai.sqlite3` in the PM container). Team approvals are
stored in the application database. Keep the app data volume, the database
backup, and the corresponding JWT encryption secret recoverable. Keep the
secret separate from the backups. To rotate a provider key, save and test the
new key before retiring the old one at the provider.

## Existing local installations

The feature is off by default. On an installation that has never saved an owner
configuration, leaving the owner UUID empty lets the earlier DeepSeek pilot continue
to support administrator grants per user via **User Management** and `PMPM_INTERNAL_DEEPSEEK_API_KEY`. Owner-managed mode uses its
team approvals instead. Personal keys are not overwritten and are not used for
managed requests. Remove the legacy environment key when moving to owner
management if it should no longer be available. After saving an owner configuration,
removing the owner UUID while the pilot is active locks managed access. Restore
the binding to regain access.

This change supplies shared credentials within one installation. It does not
introduce cross-company tenancy, subscription billing or a spending cap.
