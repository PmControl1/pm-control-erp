# Bulgarian КСС comparison in an existing installation

The `bulgaria` rules compare a priced КСС with a linked количествена сметка
in the **same project**. They check descriptions, equivalent measurement
units, quantities rounded to 0.001, missing and extra work positions, and ДДС.
No comparison runs until you select the original bill in the priced bill's
header. Comparison is validation, so it does not overwrite either bill.

## Update the Windows Docker installation

Wait for the image build for the final merge to finish successfully in
GitHub Actions. Close any unsaved editor changes and take a backup using
your installation's existing backup process before updating.

In PowerShell, open your existing checkout (use its actual drive if you
moved it), then run:

```powershell
Set-Location C:\Users\User\pm-control-erp
git switch main
git pull --ff-only origin main
Set-Location deploy\pmpm
docker compose pull app
docker compose up -d --wait --wait-timeout 600
docker compose ps
```

Use the same Compose configuration and `.env` that run your current stack.
If `PMPM_IMAGE_TAG` pins an older commit, change it to the verified merge's
`sha-<commit>` image tag or `main` before pulling. Keep the database and
uploaded-file volumes; updating the image preserves them. Refresh the
browser after the application becomes healthy.

## Review an existing project's old DIN 276 settings

New Bulgarian projects receive the Bulgarian rules. Existing project
settings are preserved, so an old project can still require DIN 276 codes.
The repair command is an operator tool and requires access to the server;
it never runs automatically. It changes only selected projects' validation
settings and records the original values for rollback.

Preview Bulgarian projects, including their IDs, owners and proposed changes:

```powershell
docker compose exec -w /app/backend app python -m scripts.repair_bulgaria_validation
```

Copy the UUID of the intended project from that output:

```powershell
$projectId = "PUT-THE-PROJECT-UUID-HERE"
docker compose exec -w /app/backend app python -m scripts.repair_bulgaria_validation --project-id $projectId
docker compose exec -w /app/backend app python -m scripts.repair_bulgaria_validation --project-id $projectId --apply
```

The repair retains custom rule sets, keeps `boq_quality`, adds `bulgaria`,
and removes the carried `din276` rule set. Other projects, documents,
quantities, prices and markups are untouched. Projects that validate as
another country are refused. If any selected project is blocked, the whole
application of that command is refused.

If a project explicitly names the `din276` classification standard, the
command refuses to remove it by default. Keep DIN 276 when it is part of
your contract. If you confirm it was an inherited default and the project
uses ordinary Bulgarian КСС instead, preview and apply that deliberate change:

```powershell
docker compose exec -w /app/backend app python -m scripts.repair_bulgaria_validation --project-id $projectId --clear-din-standard
docker compose exec -w /app/backend app python -m scripts.repair_bulgaria_validation --project-id $projectId --clear-din-standard --apply
```

Reopen the project and click **Validate** on affected bills. Stored validation
reports from before the repair are historical; run validation again to get
the current result.

To undo the settings repair, first preview, then apply the saved original:

```powershell
docker compose exec -w /app/backend app python -m scripts.repair_bulgaria_validation --project-id $projectId --restore
docker compose exec -w /app/backend app python -m scripts.repair_bulgaria_validation --project-id $projectId --restore --apply
```

Restore refuses to overwrite validation settings changed since repair.
It does not restore or change any bill data. Revalidate after restoring too.

## Try the comparison

1. Use a test project or copies of your documents. Import the original
   количествена сметка and the priced КСС as **two separate bills in the
   same project**. Keep work descriptions, numbering, units and quantities.
2. Open the priced КСС. In its header, select the original bill under
   **Priced against** (the Bulgarian UI translates this label). Save any
   current edits and click **Validate**.
3. An unchanged bill should have no `bulgaria.kss_matches_tender_bill`
   failures. A unit such as `куб.м` is equivalent to `м3`, and `кв. м.` to
   `м2`. Description case and spacing do not affect the comparison.
4. Change one quantity, for example `1340.500` to `1300`, and validate.
   Expect a quantity mismatch showing the original and priced quantities.
   Restore it, change a work description, and validate again. Expect a
   description mismatch. Missing or additional work positions should fail too.
5. Review ДДС in the bill's markup panel. For a simple test use net work
   of `1000`, contingency `10%`, then ДДС `20%` on the cumulative subtotal:
   the subtotal is `1100`, ДДС `220`, and the total `1320`. Tax on direct
   work alone after contingency should fail the taxable-base check.
6. Revert the deliberate changes and validate once more. A warning about
   a missing or ambiguous tender bill means the comparison could not run;
   resolve the link or duplicate numbering before relying on the result.

An unpriced designer's bill can have zero rates; a priced КСС still needs
the normal price/quality validation. Passing these checks confirms only the
implemented comparison and arithmetic rules, not completeness of a tender
submission or professional approval of the construction scope.

## Excel source totals and live bill totals

New Bulgarian Excel imports capture the original work and contingency amounts,
ДДС row and grand total for `bulgaria.imported_vat_totals`. This checks the
uploaded spreadsheet in its source currency, including a BGN file whose live
rates are converted to EUR. A totals-only reimport refreshes this check even
when the work rows stay unchanged. Older imports need to be reimported to
capture the source snapshot.

The source check is separate from the live bill calculation: Excel summary
rows are not automatically turned into ERP markups. Configure the live bill's
ДДС markup in the markup panel to include tax in its ERP total. A missing
native ДДС warning can therefore remain even when the source spreadsheet's
tax arithmetic passes. Later price edits do not change the source audit.
An ambiguous recap, several tax blocks on one sheet, or incomplete source
parsing produces a review warning instead of a claimed successful check.

Repeated item numbers under different sections are stored with unique section
prefixes, while the comparison retains their source numbers. Duplicate numbers
within the same section still need correction in the source document.
