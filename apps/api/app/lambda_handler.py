"""AWS Lambda entrypoint.

Normal invocations are API Gateway proxy events handled by Mangum.
Management events run from inside the VPC (the database has no public
endpoint, so this is how admin actions reach it):
  {"futureroots_command": "migrate"}             -> alembic upgrade head
  {"futureroots_command": "create_database",
   "name": "futureroots_testnet"}                -> CREATE DATABASE if absent
  {"futureroots_command": "maintenance"}         -> daily data-lifecycle sweep
                                                    (services/maintenance.py;
                                                    EventBridge invokes daily)
"""

from pathlib import Path

from mangum import Mangum

from .main import app

_mangum = Mangum(app, lifespan="off")


def _create_database(name: str) -> dict:
    import re

    import psycopg

    from .config import settings

    # server-generated call site only, but be strict about the identifier
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name):
        return {"error": "invalid database name"}
    # Connect to the maintenance DB on the same server; CREATE DATABASE cannot
    # run in a transaction, so use autocommit.
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if exists:
            return {"status": "exists", "name": name}
        conn.execute(f'CREATE DATABASE "{name}"')
    return {"status": "created", "name": name}


def _run_migrations() -> dict:
    from alembic import command
    from alembic.config import Config

    # Migrations ship as "migrations/" in the zip — the "alembic/" name would
    # collide with the alembic library package at /var/task/alembic
    cfg = Config()
    cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    command.upgrade(cfg, "head")
    return {"status": "migrated"}


def _set_role(email: str, role: str) -> dict:
    """Grant or revoke a user's role. The secure bootstrap for the first admin:
    only someone who can invoke this Lambda (i.e. holds AWS credentials) can
    mint an admin, after which admins manage each other in the console."""
    from .db import SessionLocal
    from .models import User, UserRole

    if role not in (UserRole.user.value, UserRole.admin.value):
        return {"error": "role must be 'user' or 'admin'"}
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email.lower()).first()
        if user is None:
            return {"error": f"no user with email {email}"}
        user.role = UserRole(role)
        db.commit()
        return {"status": "ok", "email": user.email, "role": user.role.value}


def _run_maintenance() -> dict:
    """Idempotent daily sweep (retention prunes + abandoned-call cap). Safe to
    run at any time, any number of times."""
    from .db import SessionLocal
    from .services.maintenance import run_maintenance

    with SessionLocal() as db:
        return {"status": "ok", "counts": run_maintenance(db)}


def handler(event, context):
    if isinstance(event, dict):
        cmd = event.get("futureroots_command")
        if cmd == "migrate":
            return _run_migrations()
        if cmd == "maintenance":
            return _run_maintenance()
        if cmd == "create_database":
            return _create_database(event.get("name", ""))
        if cmd == "set_role":
            return _set_role(event.get("email", ""), event.get("role", ""))
    return _mangum(event, context)
