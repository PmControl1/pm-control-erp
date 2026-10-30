"""PM Project Management: remove the demo data from this installation.

Sign up in the app with your own e-mail and password first, then run, from the
folder with docker-compose.yml:

    docker compose exec app python -m app.scripts.pmpm_remove_demo_data you@example.com

What it does, in order (each step commits on its own):

1. Makes the account at <email> an active admin, the same as the
   ``promote-admin`` command. Self-registration waits for an admin's approval,
   and this is that approval.
2. Deletes every demo project, archived ones included (the Settings -> Danger
   Zone "Remove demo data" purge), and records the opt-out so the startup
   seeder does not install them again.
3. Removes the demo records older seeders wrote into shared tables (the
   ``demo-cleanup --apply`` pass). Rows somebody has changed since are kept.
4. Erases the demo logins (demo@, estimator@, manager@ and the two seed-script
   admins). An erased account is anonymised in place and can no longer log in.

``--dry-run`` reports what it would remove and changes nothing.

Demo data stays off afterwards because docker-compose.override.yml sets
``SEED_DEMO=false``; with that set, no demo project can be installed from the
interface either.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


async def _run(email: str, dry_run: bool) -> int:
    from sqlalchemy import func, select

    from app.cli import _promote_user_to_admin, _register_all_module_models
    from app.config import get_settings
    from app.core.demo_accounts import NON_MAILBOX_LOGINS
    from app.core.demo_cleanup import clean_leaked_demo_rows
    from app.core.demo_seed import write_demo_seed_choice
    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.projects.service import ProjectService
    from app.modules.users.models import User
    from app.modules.users.service import UserService

    _register_all_module_models()
    settings = get_settings()
    email = email.strip().lower()

    if email in NON_MAILBOX_LOGINS:
        print(f"{email} is one of the demo logins this script removes. Give your own account's e-mail.")
        return 2

    # 1. Your account becomes the administrator.
    async with async_session_factory() as session:
        me = (await session.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
        if me is None or me.deleted_at is not None:
            print(
                f"No account with e-mail {email}.\n"
                "Sign up in the app first (http://localhost:8091, 'Create account'), then run this again."
            )
            return 1
        if dry_run:
            print(f"[dry run] Would make {me.email} an active admin.")
        else:
            print(await _promote_user_to_admin(session, email))
            await session.commit()
        my_id = me.id

    # 2. Demo projects.
    async with async_session_factory() as session:
        projects = (await session.execute(select(Project))).scalars().all()
        demo = [p for p in projects if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id")]
        if dry_run:
            print(f"[dry run] Would delete {len(demo)} demo project(s):")
            for p in demo:
                print(f"    {p.name}")
        else:
            deleted = await ProjectService(session, settings).purge_demo_projects()
            await session.commit()
            write_demo_seed_choice(False)
            print(f"Deleted {deleted} demo project(s).")

    # 3. Demo records left in shared tables.
    async with async_session_factory() as session:
        report = await clean_leaked_demo_rows(session, apply=not dry_run)
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
        verb = "[dry run] Would remove" if dry_run else "Removed"
        print(f"{verb} {report.total} leftover demo record(s) from shared tables.")
        if report.kept:
            print(f"Kept {len(report.kept)} record(s) that look like demo data but were changed since.")

    # 4. Demo logins.
    async with async_session_factory() as session:
        demo_users = (
            (
                await session.execute(
                    select(User).where(
                        func.lower(User.email).in_(sorted(NON_MAILBOX_LOGINS)),
                        User.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        service = UserService(session, settings)
        for user in demo_users:
            if dry_run:
                print(f"[dry run] Would erase the demo login {user.email}.")
                continue
            address = user.email
            await service.admin_erase_account(my_id, user.id)
            print(f"Erased the demo login {address}.")
        if not dry_run:
            await session.commit()
        if not demo_users:
            print("No demo logins left.")

    print("Done." if not dry_run else "Dry run finished; nothing was changed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove the demo data from this installation.")
    parser.add_argument("email", help="Your own account's e-mail; it becomes the administrator")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be removed; change nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(_run(args.email, args.dry_run)))


if __name__ == "__main__":
    main()
