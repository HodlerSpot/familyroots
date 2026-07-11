"""AWS Lambda entrypoint.

Normal invocations are API Gateway proxy events handled by Mangum.
A management event {"futureroots_command": "migrate"} runs Alembic
migrations from inside the VPC (the database has no public endpoint,
so this is how schema changes reach it).
"""

from pathlib import Path

from mangum import Mangum

from .main import app

_mangum = Mangum(app, lifespan="off")


def _run_migrations() -> dict:
    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "alembic"))
    command.upgrade(cfg, "head")
    return {"status": "migrated"}


def handler(event, context):
    if isinstance(event, dict) and event.get("futureroots_command") == "migrate":
        return _run_migrations()
    return _mangum(event, context)
