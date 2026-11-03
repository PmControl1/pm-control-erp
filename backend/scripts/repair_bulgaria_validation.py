"""Preview or explicitly repair legacy Bulgarian project validation settings.

Nothing is written unless ``--apply`` and one or more ``--project-id`` values
are supplied. An explicitly selected DIN 276 standard is protected unless the
operator also supplies ``--clear-din-standard``. Original settings are retained
for ``--restore``; restore refuses to overwrite settings edited since repair.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SNAPSHOT_KEY = "bulgaria_validation_repair_v1"


def repair_plan(project: Any, *, clear_din_standard: bool = False, restore: bool = False) -> dict[str, Any]:
    """Return a side-effect-free plan, including any reason the operation is blocked."""
    from app.modules.projects.country_configuration import validated_country

    before = {
        "validation_rule_sets": list(project.validation_rule_sets or []),
        "classification_standard": project.classification_standard or "",
    }
    plan: dict[str, Any] = {
        "project_id": str(project.id),
        "name": project.name,
        "owner_id": str(project.owner_id),
        "country": validated_country(project.region, project.country_code),
        "before": before,
        "after": dict(before),
        "status": "unchanged",
    }
    if plan["country"] != "BG":
        return {**plan, "status": "blocked", "reason": "Project does not validate as Bulgarian."}
    if restore:
        snapshot = (project.metadata_ or {}).get(SNAPSHOT_KEY)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("before"), dict):
            return {**plan, "status": "blocked", "reason": "No saved repair settings to restore."}
        if before != snapshot.get("after"):
            return {**plan, "status": "blocked", "reason": "Settings changed since repair; restore them manually."}
        plan["after"] = snapshot["before"]
    else:
        standard = before["classification_standard"]
        if standard.strip().lower() == "din276" and not clear_din_standard:
            return {
                **plan,
                "status": "blocked",
                "reason": "Project explicitly names DIN 276. Keep it, or review --clear-din-standard.",
            }
        rules = [name for name in before["validation_rule_sets"] if name != "din276"]
        for required in ("boq_quality", "bulgaria"):
            if required not in rules:
                rules.append(required)
        plan["after"] = {
            "validation_rule_sets": rules,
            "classification_standard": "" if standard.strip().lower() == "din276" else standard,
        }
        if plan["after"] != before and SNAPSHOT_KEY in (project.metadata_ or {}):
            return {**plan, "status": "blocked", "reason": "A repair snapshot already exists; review it first."}
    if plan["after"] != before:
        plan["status"] = "change"
    return plan


def apply_plan(project: Any, plan: dict[str, Any], *, restore: bool = False) -> None:
    """Apply a previously checked plan to one locked ORM row; caller owns the transaction."""
    if plan["status"] != "change":
        return
    metadata = dict(project.metadata_ or {})
    if restore:
        metadata.pop(SNAPSHOT_KEY, None)
    else:
        metadata[SNAPSHOT_KEY] = {
            "before": plan["before"],
            "after": plan["after"],
            "repaired_at": datetime.now(UTC).isoformat(),
        }
    project.validation_rule_sets = list(plan["after"]["validation_rule_sets"])
    project.classification_standard = plan["after"]["classification_standard"]
    project.metadata_ = metadata


async def _run(project_ids: list[uuid.UUID], *, apply: bool, clear_din_standard: bool, restore: bool) -> int:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as session:
        query = select(Project).order_by(Project.name, Project.id)
        if project_ids:
            query = query.where(Project.id.in_(project_ids))
        if apply:
            query = query.with_for_update()
        rows = list((await session.execute(query)).scalars().all())
        missing = set(project_ids) - {row.id for row in rows}
        if missing:
            print(json.dumps({"error": "Project IDs not found", "project_ids": sorted(map(str, missing))}))
            return 2
        plans = [repair_plan(row, clear_din_standard=clear_din_standard, restore=restore) for row in rows]
        if not project_ids:
            plans = [plan for plan in plans if plan["country"] == "BG"]
        print(json.dumps({"mode": "apply" if apply else "dry-run", "projects": plans}, ensure_ascii=False, indent=2))
        if any(plan["status"] == "blocked" for plan in plans):
            print("No changes written. Resolve the blocked project(s), then select the intended IDs.")
            return 2 if project_ids or apply else 0
        if apply:
            by_id = {str(row.id): row for row in rows}
            for plan in plans:
                apply_plan(by_id[plan["project_id"]], plan, restore=restore)
            await session.commit()
            print("Changes committed. Revalidate the affected bills in the application.")
        else:
            print("Dry run: nothing written. Use --project-id UUID --apply after reviewing the plan.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id", type=uuid.UUID, action="append", default=[], help="project UUID; repeat to select more"
    )
    parser.add_argument("--apply", action="store_true", help="commit the selected repairs (default: dry run)")
    parser.add_argument(
        "--clear-din-standard", action="store_true", help="explicitly remove a selected project's DIN 276 standard"
    )
    parser.add_argument(
        "--restore", action="store_true", help="restore saved settings if they have not subsequently changed"
    )
    args = parser.parse_args(argv)
    if (args.apply or args.clear_din_standard or args.restore) and not args.project_id:
        parser.error("--apply, --clear-din-standard and --restore require at least one --project-id")
    if args.restore and args.clear_din_standard:
        parser.error("--restore cannot be combined with --clear-din-standard")
    return asyncio.run(
        _run(args.project_id, apply=args.apply, clear_din_standard=args.clear_din_standard, restore=args.restore)
    )


if __name__ == "__main__":
    raise SystemExit(main())
