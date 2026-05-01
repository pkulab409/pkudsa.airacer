import base64
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def perf_app():
    os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
    os.environ["SUBMISSIONS_DIR"] = tempfile.mkdtemp()
    os.environ["RECORDINGS_DIR"] = tempfile.mkdtemp()
    os.environ["ADMIN_PASSWORD"] = "test_admin_pwd"

    from server.app import app
    from server.config.config import DB_PATH
    from server.database.models import init_db

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db(DB_PATH)
    yield app
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


@pytest.fixture
def client(perf_app):
    with TestClient(perf_app) as test_client:
        yield test_client


@pytest.fixture
def db_conn(perf_app):
    from server.config.config import DB_PATH
    from server.database.models import get_db

    with get_db(DB_PATH) as conn:
        yield conn


def test_concurrent_submission_load(client, db_conn):
    from server.blueprints.submission import _hash_password

    team_count = 8
    password = "load_test_pwd"
    password_hash = _hash_password(password)
    db_conn.execute("INSERT INTO zones (id, name) VALUES ('load_zone', 'Load Zone')")
    for idx in range(team_count):
        db_conn.execute(
            "INSERT INTO teams (id, name, password_hash, zone_id) VALUES (?, ?, ?, 'load_zone')",
            (f"load_team_{idx}", f"Load Team {idx}", password_hash),
        )
    db_conn.commit()

    code = base64.b64encode(
        b"def control(img_front, img_rear, speed):\n    return 0.5, 0.5\n"
    ).decode()

    def submit(idx):
        return client.post(
            "/api/submit",
            json={
                "team_id": f"load_team_{idx}",
                "password": password,
                "code": code,
                "slot_name": "main",
            },
        )

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=team_count) as pool:
        responses = list(pool.map(submit, range(team_count)))
    elapsed = time.perf_counter() - started

    assert [response.status_code for response in responses] == [200] * team_count
    assert elapsed < 10

    submissions = db_conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    queued_runs = db_conn.execute(
        "SELECT COUNT(*) FROM test_runs WHERE status='queued'"
    ).fetchone()[0]
    assert submissions == team_count
    assert queued_runs == team_count
