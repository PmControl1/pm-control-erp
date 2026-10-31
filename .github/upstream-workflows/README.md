# Switched-off automation from OpenConstructionERP

These files are the original project's GitHub automation: its CI matrix
(Linux, Windows and macOS), CodeQL, desktop builds, PyPI and release
publishing, Terraform, Dependabot and the sponsorship button. They are kept
here, outside `.github/workflows/`, so GitHub does not run them on this fork.

They were written for the upstream repository, its secrets and its release
process. On this fork they queued 100+ runs per push against the private
repository's Actions minutes and opened Dependabot pull requests for
dependency bumps the upstream project manages itself.

This fork's CI is `.github/workflows/pmpm-ci.yml`. The gitleaks secret scan
(`.github/workflows/secret-scan.yml`) is the one upstream workflow left on.

## After merging an upstream release

`git merge upstream/main` follows these renames, so upstream edits to a
workflow land in the copy here. A workflow upstream adds after this point
lands in `.github/workflows/` and will run. Check that folder after every
upstream merge and move anything new in here:

```bash
git mv .github/workflows/<new-file>.yml .github/upstream-workflows/
```
