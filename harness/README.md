# End-to-end harness

A real browser (Playwright, Chromium) working through the app the way a
person does, against a throwaway copy of the production stack:

- the **production image** with **`deploy/pmpm/docker-compose.yml`** unchanged,
  including Postgres and the Caddy proxy (upload limits, timeouts and headers
  are the real ones);
- a **fresh database** every run, with **synthetic data only**;
- **Mailpit** catching every email the app sends, so tests can follow invite
  and password-reset links;
- a **stand-in AI** (`stack/fake_ai.py`) answering the app's DeepSeek calls,
  so AI features run with no key and nothing leaves the machine.

On every pull request and every push to `main`, CI builds the image and runs
this harness against it (the `Docker image` job in
`.github/workflows/pmpm-ci.yml`). On `main`, a red harness stops the image
from being published.

## Reading a run

The job summary lists each failed test with its error and, for every server
error the test hit, the server's own log lines for that request (matched by
`X-Request-ID`). The `harness-report` artifact has the full HTML report, a
trace and video of each failure, and every container's log.

Besides its own checks, every test has a watchdog: it fails the test if the
page threw an uncaught error, any `/api` call returned 5xx, or the crash
screen is showing. Console errors and 4xx answers are recorded, not failed on.

## Running it on your own machine

Needs Docker, Node 24 and Python 3. It uses its own project name
(`pmpm-harness`) and ports 18080, 18025 and 18001 on localhost, and never
reads `deploy/pmpm/.env`, so it cannot touch a real installation running on
the same machine.

```bash
bash harness/stack/stack.sh up ghcr.io/pmcontrol1/pm-control-erp:main   # or any image:tag
cd harness && npm ci && npx playwright install chromium
npx playwright test            # npx playwright test --ui to watch it
npx playwright show-report results/html
cd .. && bash harness/stack/stack.sh down   # deletes the copy and its data
```

While the stack is up: the app is at http://localhost:18080 (the owner's
generated sign-in is in `harness/.state/owner.json`), every email at
http://localhost:18025, and every AI request at
http://localhost:18001/_harness/requests.

## Layout

| Path | What it is |
| --- | --- |
| `stack/stack.sh` | Starts, logs and stops the test stack |
| `stack/docker-compose.harness.yml` | The few overrides on top of the production Compose file |
| `stack/bootstrap.py` | A firm's first day: the owner's account, pinned as platform owner, AI on |
| `stack/fake_ai.py` | The stand-in AI |
| `lib/` | The watchdog, API, Mailpit and environment helpers |
| `tests/` | The checks |
| `scripts/summarize.mjs` | Turns a run into the job summary |

## Rules for changing the checks

New tests only add lines. A pull request that removes or rewrites lines in
`harness/tests` or `harness/lib` turns the **Existing harness checks
unchanged** check red, so those lines get read before merging: a check should
only get weaker on purpose. A bug is fixed in the app, with a test that fails
before the fix and passes after it, never by loosening a check.
