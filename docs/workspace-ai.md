# Workspace AI

The platform owner sets the AI once. Every signed-in employee on this single-company
installation then uses it in every AI feature: the assistant, estimates, takeoff,
meetings, translation and the rest. Nobody else enters or sees a key.

## Set it up

1. Set `PMPM_PLATFORM_OWNER_USER_IDS` in `deploy/pmpm/.env` to the owner
   administrator account UUID(s), separated by commas, and recreate the app
   container. Other deployments set `PLATFORM_OWNER_USER_IDS` in the backend environment.
   Sign in with one of these active administrator accounts and open
   **Settings → AI → Workspace AI**.
2. Choose the provider (DeepSeek for now), paste the API key, and optionally a
   model (empty uses the provider default, `deepseek-flash` for DeepSeek).
3. Optionally write a **system prompt**. It is put in front of every AI request
   in the app, for example the company context, the language to answer in, or
   house rules.
4. Click **Save**, then **Test Connection**.

To switch to Claude later, pick **Anthropic Claude**, paste that key and enter
the model ID (for example `claude-opus-5-5`). Nothing else changes.

**Turn off workspace AI** deletes the saved key, and users go back to entering
their own keys.

## Who counts as the owner

`PLATFORM_OWNER_USER_IDS` (in `deploy/pmpm/.env` it is `PMPM_PLATFORM_OWNER_USER_IDS`)
is a comma-separated list of immutable account UUIDs that may change workspace AI. An owner
must also be an active administrator in the database; a token's role alone does
not grant access. UUID entries are trimmed and normalized; a malformed entry
invalidates the entire list. The former `PLATFORM_OWNER_EMAILS` setting no
longer grants access. Email changes do not transfer ownership, and deleting
and recreating the same email produces a different account UUID.
Other administrators have the same shared-AI access as employees.

An empty or missing list grants owner access to nobody. Existing workspace AI
continues serving employees, but private settings, connection tests and mutations
remain protected. Only the server operator can set or change this list; there is
no first-caller claim or automatic grant to the first administrator.

For a fresh installation, start only the private database and app services with
the list blank, then register the first administrator. Copy its UUID, printed
by the bootstrap command, into the list and recreate the app. The existing
first-user administrator bootstrap still works; see
[`deploy/pmpm/README.md`](../deploy/pmpm/README.md). `deploy.sh` verifies an active
configured owner before starting the public proxy.

For an existing installation, list the existing owner administrator account UUID, then
run `./deploy.sh` to recreate the app with that environment. Keep at least one
listed active administrator. The deployment runbook includes a private UUID
lookup for existing accounts. Recover a wrong list by editing the server `.env`
and recreating the app, rather than granting every administrator owner access.
If the intended existing account needs administrator recovery, use the existing
server CLI: `docker compose exec app python -m app.cli promote-admin owner@firm.bg`.

## What employees see

While workspace AI is enabled, ordinary accounts see AI availability and their
own assistant memories. The selected provider, exact model, keys, owner system
prompt, provider costs and runtime diagnostics are not included in their settings
responses. The owner retains the full configuration and connection test under
**Settings → AI → Workspace AI**. Personal connection tests and runtime changes
are restricted to the owner while shared AI is active.

Estimate history, agent results and streamed errors also omit runtime identifiers.
Detailed failures remain in server-side audit records or logs. AI-generated
answers remain labelled as AI; this does not rewrite user documents or generated
answer text. Browser-delivered frontend code remains inspectable, and model
identity can still be inferred from behaviour or the content of an AI answer.
Configure `PMPM_PLATFORM_OWNER_USER_IDS` before inviting staff administrators.

## Memory

With **Assistant memory** on, the assistant remembers facts and preferences
across conversations, for example when a user says "remember that I prefer short
answers". Each user sees, adds and deletes their own memories under
**Settings → AI**. No user can see another user's memories. The newest 60 are
given to the assistant in every chat.

## How it works

- The settings are stored in `oe_ai_workspace_config`, with the key encrypted
  with the server's secret. Each server process keeps a copy in memory and
  re-reads it every 10 seconds.
- `ai_client.resolve_provider_and_key`, which every AI feature calls, returns the
  workspace provider and key whenever workspace AI is set up. Users' personal
  keys, models and self-hosted endpoints are ignored while it is on.
- `call_ai` and `call_ai_tools` add the owner's system prompt, so every
  feature gets it.
- Memories are stored in `oe_ai_memory`, one row per memory per user. The chat
  adds them to its system prompt and has a `save_memory` tool.
- The assistant already has a per-user daily token limit
  (`ERPCHAT_DAILY_TOKEN_BUDGET`, default 500,000 tokens).

## Not covered yet

Separating customer companies from each other (#28), and billing with usage
quotas per customer (#29). Until #28 is done, everyone on one installation is
one company.
