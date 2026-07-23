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
    from sqlalchemy import text

    from .db import Base, engine

    # Migrations ship as "migrations/" in the zip — the "alembic/" name would
    # collide with the alembic library package at /var/task/alembic
    cfg = Config()
    cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    command.upgrade(cfg, "head")

    # Reconciliation backstop. create_all is idempotent (checkfirst=True): it
    # creates only tables that are absent and never drops or alters an existing
    # one. This self-heals a "stamped-but-not-fully-created" revision — e.g. a
    # table that never landed while alembic_version still reads head, which
    # leaves `upgrade head` a permanent no-op. Base.metadata is fully populated
    # because `from .main import app` (module top) imports every model.
    Base.metadata.create_all(bind=engine, checkfirst=True)

    with engine.connect() as conn:
        present = {
            t: conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar() is not None
            for t in ("notification_preferences", "push_subscriptions", "notifications")
        }
    return {"status": "migrated", "tables": present}


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


def _purge(admin_email: str, confirm: str) -> dict:
    """DESTRUCTIVE one-off: wipe ALL application data in this database, keeping
    only the given admin user. Guarded by a confirm token and only reachable via
    a direct Lambda invoke (AWS creds required) — never an HTTP route. Truncates
    every model table (CASCADE resolves the FK cycles) but preserves
    alembic_version so the schema stays at head, then re-inserts the admin row
    (role forced to admin, avatar nulled since media_objects is gone). If the
    admin email isn't present in this DB, everything is still wiped and the DB is
    left with zero users (reported)."""
    from sqlalchemy import text

    from .db import Base, SessionLocal
    from .models import User, UserRole

    if confirm != "yes-wipe-everything":
        return {"error": "refused: pass confirm='yes-wipe-everything'"}
    if not admin_email:
        return {"error": "admin_email required"}
    email = admin_email.lower()

    with SessionLocal() as db:
        admin = db.query(User).filter(User.email == email).first()
        admin_data = None
        if admin is not None:
            admin_data = {c.name: getattr(admin, c.name) for c in User.__table__.columns}
            admin_data["role"] = UserRole.admin  # ensure it stays an admin
            admin_data["avatar_media_id"] = None  # media_objects is truncated below

        # TRUNCATE every model table (NOT alembic_version) in one statement;
        # CASCADE + RESTART IDENTITY handles the mutually-dependent FKs. This is
        # transactional in Postgres, so a failure rolls back cleanly.
        table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        db.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))

        preserved = False
        if admin_data is not None:
            db.add(User(**admin_data))
            preserved = True
        db.commit()
        users_remaining = db.query(User).count()

    return {
        "status": "purged",
        "admin_email": email,
        "admin_preserved": preserved,
        "users_remaining": users_remaining,
        "tables_truncated": len(Base.metadata.sorted_tables),
    }


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
        if cmd == "purge":
            return _purge(event.get("admin_email", ""), event.get("confirm", ""))
    return _mangum(event, context)
