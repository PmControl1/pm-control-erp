# Bulgaria product cleanup — recovery checkpoint

Branch: `feat/bulgaria-focused-product`

Base: `1e581fd04a9f2b95cae22613420c0b5f062b22a8`

Recovered checkpoint: `93ecf4d` (9 November 2026). Earlier interrupted sessions
left the implementation uncommitted in this checkout. Continue this branch;
do not reconstruct the work by fetching source files individually.

## Implemented

- New public project requests default to BG/EUR/Bulgarian, with the Bulgarian
  pack active even when no pack was selected previously.
- Country setup, pack offers, reference catalogues, classifications, markups,
  the cost advisor and property-development defaults use the Bulgarian market.
- Bulgarian and English remain available as interface languages.
- Removed 33 bundled foreign catalogue files and unused foreign price-system
  screens. The reference database is Sofia; its original BGN rates keep their
  currency information for EUR conversion.
- Bulgarian PDF and Excel headings, ДДС totals and spreadsheet reimport use
  the existing calculation and import/export engines.
- Shared pack discovery, schemas, currency metadata, import readers and
  existing project/cost data remain available. This change does not migrate
  or delete stored business data. Applying a ДДС template remains explicit.

## Verification on the recovered branch

Fresh local checks on 9 November 2026:

| Check | Result |
| --- | --- |
| Changed backend suites and Bulgarian regressions, PostgreSQL | 552 passed, 7 skipped |
| Focused frontend suites | 198 passed across 30 files |
| Backend Ruff lint and formatting | Passed |
| Changed frontend ESLint | Passed; source i18n module has the existing lint exclusion |
| Repository hygiene and package-data references | Passed |
| Deployment script tests | 20 passed |
| Strict TypeScript, all application/E2E/config projects | Passed |
| Production Vite build | Incomplete: environment killed the process, exit 137 |

The final test-only type guards and unused-binding cleanup also passed all
18 tests in the three affected frontend suites and changed-file ESLint.
TypeScript batches 1–5 passed in the first fresh run; after fixing the two
new-test type errors, batches 6–9 and the E2E/config projects passed on rerun.

The PostgreSQL workflow test creates a project without market selections,
imports a synthetic BGN КСС, applies the Bulgarian ДДС template, verifies
230 EUR direct cost and 276 EUR with ДДС, checks PDF and Excel output, and
reimports the workbook without duplicate positions or changed totals:

```bash
cd backend
pytest tests/integration/test_bulgaria_product_workflow.py -q
```

Run it with disposable PostgreSQL through `DATABASE_URL` and
`DATABASE_SYNC_URL`, as in `.github/workflows/pmpm-ci.yml`. That workflow now
includes the Bulgarian workflow test in its PostgreSQL regression step.

## Remaining release gate

Push this branch and open a review PR once publication is authorized. Full
GitHub CI, the production Docker build and its smoke test still need to pass.
The local environment has no Docker executable. No build checks have been
disabled to work around the memory limit, and no running ERP installation
has been updated by this cleanup.
