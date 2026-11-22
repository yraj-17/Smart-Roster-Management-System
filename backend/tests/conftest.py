"""DB and API tests run against a dedicated test database (never the main one).

Set TEST_DATABASE_URL, e.g. postgresql+psycopg://postgres:pw@localhost:5432/smart_roster_test
The schema is rebuilt from Alembic migrations, seeded, and December 2026 is generated
and persisted once per session. Each test runs inside a rolled-back transaction.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

TEST_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def engine():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    if not TEST_URL.rsplit("/", 1)[-1].endswith("_test"):
        pytest.exit("TEST_DATABASE_URL must point at a database whose name ends with _test")
    os.environ["DATABASE_URL"] = TEST_URL
    from app.config import get_settings
    get_settings.cache_clear()

    eng = create_engine(TEST_URL)
    try:
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"test database unreachable: {exc}")

    from alembic import command
    from alembic.config import Config
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.upgrade(cfg, "head")

    from app.scheduling import generate
    from app.seed.seed import seed
    from app.services.engine_adapter import load_problem, persist_outcome
    with Session(eng) as s:
        seed(s)
        problem = load_problem(s, 2026, 12)
        persist_outcome(s, problem, generate(problem), created_by="test")
        s.commit()
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield s
    s.close()
    trans.rollback()
    conn.close()
