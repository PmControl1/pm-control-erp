#!/usr/bin/env python3
"""Apply the PM Project Management brand to an OpenConstructionERP checkout.

Run from anywhere:   python3 branding/apply_branding.py [--name "PM Project Management"]

It is idempotent, so re-run it after merging a new upstream release. What it does:

1. Renames the product in user-visible text (UI strings in all languages,
   page titles, emails, PDF/Excel footers) from "OpenConstructionERP"/"OCERP"
   to the brand name. URLs, code identifiers, comment lines, copyright headers
   and the upstream provenance markers are left alone.
2. Replaces the split "Open|Construction|ERP" wordmark in JSX with BRAND_NAME
   and removes the small "by OpenConstructionERP" line under a custom logo
   (the upstream credit lives on the About page instead).
3. Turns off upstream's own prompts (support-us/donate, release news, rate-us)
   and the update check against upstream's GitHub releases.
4. Hides links that lead to the upstream site, repo and community chats.
5. Installs the logo/favicon/app icons from branding/assets and gives
   index.html a plain head (no upstream SEO/marketing tags).

What it deliberately keeps: LICENSE, NOTICE, COPYRIGHT, copyright headers in
source files, the invisible "ddc:*" provenance markers, the third-party
licence list, and functional URLs (e.g. converter downloads).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "assets"
FRONT = ROOT / "frontend"
SRC = FRONT / "src"

# ── 1. product-name text pass ──────────────────────────────────────────────

# Not part of a URL, path, e-mail, domain or identifier.
# ASCII classes on purpose: in Korean, Japanese, Hungarian, Hebrew... the name is
# glued to the surrounding word ("OpenConstructionERPへ", "ל-OpenConstructionERP").
NAME_RE = re.compile(r"(?<![A-Za-z0-9_./@:#])OpenConstructionERP(?![A-Za-z0-9_/])(?!\.(?:com|io)\b)")
SHORT_RE = re.compile(r"(?<![A-Za-z0-9_./@:#])OCERP(?![A-Za-z0-9_/])(?!\.\w)")
# Outside the translation files a trailing hyphen means an identifier, file name
# or user agent ("OpenConstructionERP-pg-", "...-converter-installer"): keep those.
NAME_RE_CODE = re.compile(r"(?<![A-Za-z0-9_./@:#-])OpenConstructionERP(?![A-Za-z0-9_/-])(?!\.(?:com|io)\b)")

COMMENT_PREFIXES = ("//", "*", "/*", "#", "<!--", "{/*")
# Lines carrying upstream provenance markers are kept verbatim.
PROVENANCE_TOKENS = ("DDC-CWICR", "DDC_ORIGIN", "ddc:", "·CWICR·", "CWICR·OpenConstructionERP", "provenance",
                     # authorship credits and upstream origin strings stay upstream's
                     "DataDrivenConstruction", "Core Team", "author=", "_ORIGIN", "x-ddc",
                     # file markers written into existing settings files
                     "_SETTINGS_BEGIN", "_SETTINGS_END")
# Lines that build file-system paths or data-dir names keep the upstream name,
# so existing installs keep finding their data.
PATH_TOKENS = ("Path(", "path.join", "os.path", '/ "OpenConstructionERP"', "\\OpenConstructionERP", "LOCALAPPDATA", "APPDATA", "XDG_")

TEXT_SUFFIXES = {".ts", ".tsx", ".json", ".md", ".py", ".html", ".j2", ".jinja", ".jinja2", ".txt", ".webmanifest"}

SKIP_PARTS = ("node_modules", "__tests__", "/tests/", "/e2e", "/legal", "license", "LICENSE")
SKIP_FILES = {
    SRC / "shared" / "brand.ts",
    SRC / "shared" / "lib" / "ddc-integrity.ts",
    SRC / "features" / "about" / "AboutPage.tsx",
    SRC / "features" / "about" / "ThirdPartyLicenses.tsx",
}


def is_test(p: Path) -> bool:
    n = p.name
    return ".test." in n or ".spec." in n or n.startswith("test_") or n.endswith("_test.py")


def text_targets() -> list[Path]:
    roots = [SRC, ROOT / "backend" / "app"]
    files: list[Path] = []
    for r in roots:
        for p in r.rglob("*"):
            if not p.is_file() or p.suffix not in TEXT_SUFFIXES:
                continue
            s = p.as_posix()
            if any(part in s for part in SKIP_PARTS) or is_test(p) or p in SKIP_FILES:
                continue
            files.append(p)
    files += [FRONT / "vite.config.ts", FRONT / "public" / "splash.html"]
    return [f for f in files if f.exists()]


def rename_in_line(line: str, name: str, short: bool = True, locale: bool = False) -> str:
    stripped = line.lstrip()
    if stripped.startswith(COMMENT_PREFIXES) or any(t in line for t in PROVENANCE_TOKENS + PATH_TOKENS):
        return line
    line = (NAME_RE if locale else NAME_RE_CODE).sub(name, line)
    if short:  # "OCERP" is also a Python identifier (procurement order owner)
        line = SHORT_RE.sub(name, line)
    # French/Italian elision before a vowel-initial name ("d'OpenConstructionERP").
    return re.sub(rf"\b([dDlL])'{re.escape(name)}", lambda m: ("de " if m.group(1) in "dD" else "") + name, line)


def text_pass(name: str) -> tuple[int, int]:
    changed_files = hits = 0
    for f in text_targets():
        try:
            original = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "OpenConstructionERP" not in original and "OCERP" not in original:
            continue
        lines = original.splitlines(keepends=True)
        is_locale = "/locales/" in f.as_posix()
        out = [rename_in_line(ln, name, short=f.suffix != ".py", locale=is_locale) for ln in lines]
        new = "".join(out)
        if new != original:
            hits += sum(a != b for a, b in zip(lines, out))
            changed_files += 1
            f.write_text(new, encoding="utf-8")
    return changed_files, hits


# Backend tests that check what a user is shown: the product name in emails,
# reports, the CLI banner and the settings default. They assert the upstream
# name, so they are renamed along with the app; the rest of the test tree is
# left as upstream wrote it (see SKIP_PARTS).
BRAND_TESTS = [
    ROOT / "backend" / "tests" / "unit" / name
    for name in (
        "test_every_email_carries_the_brand.py",
        "test_email_service.py",
        "test_config.py",
        "test_cli_version_flag_matches_the_version_command.py",
        "test_a_generated_report_is_written_in_the_readers_language.py",
        "test_converter_install_integrity.py",
        "test_notification_email_links.py",
        "test_notification_email_locale.py",
        "test_portal_login_email.py",
        "test_pdf_letterhead.py",
        "test_pdf_appearance_reaches_the_renderer.py",
        "test_outgoing_documents_print_the_company_letterhead.py",
        "test_version_fallback_names_a_version.py",
        "test_pack_install_says_what_it_did.py",
    )
]


def brand_tests_pass(name: str) -> int:
    changed = 0
    for f in BRAND_TESTS:
        if not f.exists():
            continue
        original = f.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        new = "".join(rename_in_line(ln, name, short=False) for ln in lines)
        if new != original:
            f.write_text(new, encoding="utf-8")
            changed += 1
    return changed


# ── 2. JSX wordmark + "by OpenConstructionERP" attribution ─────────────────

WORDMARK_RE = re.compile(
    r'Open<span className="[^"]*">Construction</span>\s*<span className="[^"]*">ERP</span>'
)
BY_ATTRIBUTION_RE = re.compile(
    r"(?:\{/\*(?:(?!\*/).)*?\*/\}\s*)?"  # an immediately preceding JSX comment
    r'<span\s+className="[^"]*"(?:\s+style=\{\{(?:(?!\}\}).)*\}\})?\s*>\s*'
    r"by\{' '\}\s*<span className=\"font-semibold tracking-tight\">\s*\{BRAND_NAME\}\s*</span>\s*</span>",
    re.S,
)
BRAND_IMPORT = "import { BRAND_NAME } from '@/shared/brand';\n"


def ensure_import(src: str, line: str, symbol: str) -> str:
    if re.search(rf"import\s*\{{[^}}]*\b{symbol}\b[^}}]*\}}\s*from '@/shared/brand'", src):
        return src
    m = re.search(r"^import [^\n]*\n(?!\s)", src, re.M)
    # insert after the last top-level import statement
    last = None
    for m in re.finditer(r"^import [\s\S]*?;\n", src, re.M):
        last = m
    pos = last.end() if last else 0
    return src[:pos] + line + src[pos:]


def jsx_pass() -> int:
    n = 0
    for f in SRC.rglob("*.tsx"):
        if is_test(f) or "__tests__" in f.as_posix() or f in SKIP_FILES:
            continue
        s = f.read_text(encoding="utf-8")
        new = WORDMARK_RE.sub("{BRAND_NAME}", s)
        new = BY_ATTRIBUTION_RE.sub("", new)
        if new != s:
            if "BRAND_NAME" in new:
                new = ensure_import(new, BRAND_IMPORT, "BRAND_NAME")
            f.write_text(new, encoding="utf-8")
            n += 1
    return n


# ── 3. upstream prompts and update check ───────────────────────────────────

GATES = [
    (SRC / "app" / "layout" / "SupportUsButton.tsx", "export function SupportUsButton("),
    (SRC / "shared" / "ui" / "HeaderNewsButton.tsx", "export function HeaderNewsButton("),
    (SRC / "shared" / "ui" / "ReviewPromptCard.tsx", "export function ReviewPromptCard("),
    # Its form files issues on upstream's GitHub tracker.
    (SRC / "shared" / "ui" / "FeedbackDialog.tsx", "export function FeedbackDialog("),
]
GUARD = "  if (!UPSTREAM_PROMPTS_ENABLED) return null;\n"
GATE_IMPORT = "import { UPSTREAM_PROMPTS_ENABLED } from '@/shared/brand';\n"


def gate_pass() -> int:
    n = 0
    for f, sig in GATES:
        if not f.exists():
            print(f"  ! missing {f.relative_to(ROOT)} (upstream moved it?)")
            continue
        s = f.read_text(encoding="utf-8")
        if "UPSTREAM_PROMPTS_ENABLED) return null" in s:
            continue
        i = s.find(sig)
        if i < 0:
            print(f"  ! signature not found in {f.name}: {sig}")
            continue
        j = s.find("{\n", s.find(")", i)) + 2
        s = s[:j] + GUARD + s[j:]
        s = ensure_import(s, GATE_IMPORT, "UPSTREAM_PROMPTS_ENABLED")
        f.write_text(s, encoding="utf-8")
        n += 1
    upd = SRC / "shared" / "ui" / "UpdateChecker.tsx"
    if upd.exists():
        s = upd.read_text(encoding="utf-8")
        new = re.sub(
            r"const UPDATE_CHECK_DISABLED = (?!true;)[^;]+;",
            "const UPDATE_CHECK_DISABLED = true; // PM Project Management: no upstream update check",
            s,
        )
        if new != s:
            upd.write_text(new, encoding="utf-8")
            n += 1
    return n


# ── 4. hide links to upstream site / repo / community ──────────────────────

CSS_MARK = "/* pmpm-branding: hide upstream links */"
CSS_RULE = f"""
{CSS_MARK}
/* Links to the upstream project's website, repository and community chats are
   hidden in this distribution. The credit on the About page carries
   data-upstream-credit and stays visible. */
a[href*="datadrivenconstruction" i]:not([data-upstream-credit]),
a[href*="openconstructionerp" i]:not([data-upstream-credit]) {{
  display: none !important;
}}
"""


def css_pass() -> int:
    css = SRC / "index.css"
    s = css.read_text(encoding="utf-8")
    if CSS_MARK in s:
        return 0
    css.write_text(s.rstrip("\n") + "\n" + CSS_RULE, encoding="utf-8")
    return 1


# ── 5. assets and index.html ───────────────────────────────────────────────

def assets_pass() -> int:
    pub = FRONT / "public"
    logo = ASSETS / "pmpm-logo.svg"
    fav = ASSETS / "favicon.svg"
    mask = ASSETS / "pmpm-icon-maskable.svg"
    (pub / "brand").mkdir(exist_ok=True)
    copies = [
        (logo, pub / "brand" / "pmpm-logo.svg"),
        (logo, pub / "logo.svg"),
        (fav, pub / "favicon.svg"),
        (logo, pub / "pwa" / "icon-192.svg"),
        (logo, pub / "pwa" / "icon-256.svg"),
        (logo, pub / "pwa" / "icon-384.svg"),
        (logo, pub / "pwa" / "icon-512.svg"),
        (mask, pub / "pwa" / "icon-maskable-512.svg"),
    ]
    for a, b in copies:
        shutil.copyfile(a, b)
    return len(copies)


HEAD_RE = re.compile(r"<title>.*?<meta name=\"application-name\"[^>]*/>", re.S)
SPLASH_SVG_RE = re.compile(r'<svg class="logo"[^>]*>.*?</svg>', re.S)


def html_pass(name: str) -> int:
    n = 0
    idx = FRONT / "index.html"
    s = idx.read_text(encoding="utf-8")
    head = (
        f"<title>{name}</title>\n"
        '    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />\n'
        f'    <meta name="description" content="{name} - construction project management platform." />\n'
        '    <meta name="robots" content="noindex, nofollow" />\n'
        f'    <meta name="application-name" content="{name}" />'
    )
    new = HEAD_RE.sub(lambda _m: head, s, count=1)
    if new != s:
        idx.write_text(new, encoding="utf-8")
        n += 1
    splash = FRONT / "public" / "splash.html"
    if splash.exists():
        s = splash.read_text(encoding="utf-8")
        new = SPLASH_SVG_RE.sub(
            f'<img class="logo" src="/brand/pmpm-logo.svg" alt="{name}" />', s, count=1
        )
        if new != s:
            splash.write_text(new, encoding="utf-8")
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="PM Project Management")
    args = ap.parse_args()
    if not (SRC / "shared" / "brand.ts").exists():
        print("frontend/src/shared/brand.ts is missing - run this on the pmpm-branding branch.")
        return 1
    files, lines = text_pass(args.name)
    print(f"1. product name: {lines} lines in {files} files")
    print(f"2. wordmarks/attribution lines: {jsx_pass()} files")
    print(f"   tests that assert the product name: {brand_tests_pass(args.name)} files")
    print(f"3. upstream prompts + update check switched off: {gate_pass()} changes")
    print(f"4. upstream-link CSS rule: {'added' if css_pass() else 'already present'}")
    print(f"5. assets installed: {assets_pass()}, html heads updated: {html_pass(args.name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
