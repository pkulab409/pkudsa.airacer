import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# Set environment variables before importing app
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ["SUBMISSIONS_DIR"] = tempfile.mkdtemp()
os.environ["RECORDINGS_DIR"] = tempfile.mkdtemp()
os.environ["ADMIN_PASSWORD"] = "test_admin_pwd"

from server.app import app
from server.database.models import init_db, get_db
from server.config.config import DB_PATH, RECORDINGS_DIR, SUBMISSIONS_DIR

@pytest.fixture(scope="function", autouse=True)
def setup_test_db():
    os.environ["SUBMISSIONS_DIR"] = SUBMISSIONS_DIR
    os.environ["RECORDINGS_DIR"] = RECORDINGS_DIR
    # Re-create DB for each test to avoid UNIQUE constraint failures
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db(DB_PATH)
    for root in (SUBMISSIONS_DIR, RECORDINGS_DIR):
        if os.path.exists(root):
            shutil.rmtree(root)
        os.makedirs(root, exist_ok=True)
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def db_conn():
    with get_db(DB_PATH) as conn:
        yield conn

@pytest.fixture
def admin_auth():
    import base64
    auth_str = base64.b64encode(b"admin:test_admin_pwd").decode()
    return {"Authorization": f"Basic {auth_str}"}
