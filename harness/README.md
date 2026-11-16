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

## What it uploads

Two kinds of files, neither stored in this repository:

- **Public samples** (`samples/manifest.json`): real IFC 2x3/4/4.3 models
  from buildingSMART, Autodesk's Revit sample projects, DWG from R14 to 2018
  and DXF (LibreDWG test data), LAS/LAZ/COPC and E57 point clouds, every EXIF
  photo orientation, HEIC, glTF and BCF. `samples/fetch.mjs` downloads them
  and checks each against its sha256 and size; CI caches them between runs.
  Each entry records its source and licence.
- **A synthetic pack** (`samples/generate.py`): Bulgarian КСС, contracts and
  protocols, an A1 drawing, a scanned PDF, names that break naive code
  (Cyrillic punctuation, `#%&;'`, emoji, 200 characters), empty, truncated,
  password-protected and disguised files, two files with the same name, a
  40-file batch and, nightly, uploads just under and over the 500 MB limit.

Each file goes through the upload path the Documents page would choose for
it (`lib/upload.ts` mirrors `useFileUpload.ts`), and the test checks what the
app made of it: a document must keep its name and download back byte for
byte, a BIM model must finish processing with elements, a drawing must
parse. A file meant to be refused must be refused with a reason. No file may
ever get a server error.

**Tiers.** Every pull request runs the `pr` tier (small, fast files). The
**Harness nightly** workflow (`.github/workflows/pmpm-harness-nightly.yml`)
runs everything against the image `main` last published, every night and on
demand from the Actions tab.

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
node harness/samples/fetch.mjs --tier pr                # or --tier nightly for everything
pip install -r harness/samples/requirements.txt && python3 harness/samples/generate.py --tier pr
cd harness && npm ci && npx playwright install chromium
npx playwright test            # HARNESS_TIER=nightly for the full set; --ui to watch it
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
| `samples/` | The public sample manifest, its downloader, and the synthetic pack generator |
| `tests/` | The checks |
| `scripts/summarize.mjs` | Turns a run into the job summary |

## Rules for changing the checks

New tests only add lines. A pull request that removes or rewrites lines in
`harness/tests` or `harness/lib` turns the **Existing harness checks
unchanged** check red, so those lines get read before merging: a check should
only get weaker on purpose. A bug is fixed in the app, with a test that fails
before the fix and passes after it, never by loosening a check.
