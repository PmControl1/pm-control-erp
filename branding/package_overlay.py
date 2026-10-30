#!/usr/bin/env python3
"""Build the Docker overlay folder from a fresh frontend build.

usage: package_overlay.py <frontend/dist> <upstream _frontend_dist> <backend/app> <upstream tag> <out dir>

- frontend files identical to the upstream build go to keep_from_upstream.txt
  (the Dockerfile copies them out of the official image); the rest are copied
  to <out>/frontend_dist.
- backend files changed since <upstream tag> are copied to <out>/backend_app.
- backend files and packs deleted since <upstream tag> are listed in
  <out>/remove_from_upstream.txt (paths under /app in the image; a whole folder
  where the folder is gone), and the Dockerfile deletes them from the image.
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    dist, upstream, backend_app, tag, out = (Path(a) for a in sys.argv[1:6])
    tag = str(tag)
    fe_out = out / "frontend_dist"
    be_out = out / "backend_app"
    for d in (fe_out, be_out):
        if d.exists():
            shutil.rmtree(d)
    keep, shipped, shipped_bytes = [], 0, 0
    for f in sorted(p for p in dist.rglob("*") if p.is_file()):
        rel = f.relative_to(dist).as_posix()
        u = upstream / rel
        if u.is_file() and u.stat().st_size == f.stat().st_size and sha(u) == sha(f):
            keep.append(rel)
            continue
        dst = fe_out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        shipped += 1
        shipped_bytes += f.stat().st_size
    (out / "keep_from_upstream.txt").write_text("\n".join(keep) + "\n", encoding="utf-8")

    repo = backend_app.resolve().parent.parent
    changed = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--name-only", tag, "HEAD", "--", "backend/app"], text=True
    ).split()
    copied = 0
    for rel in changed:
        src = repo / rel
        if not src.is_file():
            continue
        copied += 1
        dst = be_out / Path(rel).relative_to("backend/app")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    deleted = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=D", tag, "HEAD", "--", "backend/app", "packs"],
        text=True,
    ).split()
    removals: set[str] = set()
    for rel in deleted:
        path = Path(rel)
        # Remove the highest folder that no longer exists at all, else the file.
        top = path
        for parent in path.parents:
            if str(parent) in (".", "backend", "backend/app", "packs") or (repo / parent).exists():
                break
            top = parent
        removals.add(top.as_posix())
    (out / "remove_from_upstream.txt").write_text("\n".join(sorted(removals)) + "\n", encoding="utf-8")
    print(f"frontend: {shipped} files ({shipped_bytes / 1e6:.1f} MB) shipped, {len(keep)} kept from upstream")
    print(f"backend: {copied} files changed, {len(removals)} paths removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
