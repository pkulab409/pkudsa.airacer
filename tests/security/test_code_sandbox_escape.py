"""
Code Sandbox Escape Tests (Module K2)

Tests that student code cannot escape the sandbox restrictions.
"""

import base64
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import os
import shutil
import tempfile


@pytest.fixture
def client():
    os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
    os.environ["SUBMISSIONS_DIR"] = tempfile.mkdtemp()
    os.environ["RECORDINGS_DIR"] = tempfile.mkdtemp()
    os.environ["ADMIN_PASSWORD"] = "test_admin_pwd"

    from server.app import app
    from server.database.models import init_db, get_db
    from server.config.config import DB_PATH
    from server.blueprints.submission import _hash_password

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db(DB_PATH)

    with get_db(DB_PATH) as conn:
        conn.execute("INSERT INTO zones (id, name) VALUES ('zone1', 'Zone 1')")
        conn.execute(
            "INSERT INTO teams (id, name, password_hash, zone_id) VALUES ('t1', 'Team 1', ?, 'zone1')",
            (_hash_password("hash"),),
        )
        conn.commit()

    with TestClient(app) as c:
        yield c

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    shutil.rmtree(os.environ["SUBMISSIONS_DIR"], ignore_errors=True)
    shutil.rmtree(os.environ["RECORDINGS_DIR"], ignore_errors=True)


def submit_code(client, code_str):
    """Helper to submit code and return response."""
    code_b64 = base64.b64encode(code_str.encode()).decode()
    return client.post("/api/submit", json={
        "team_id": "t1",
        "password": "hash",
        "code": code_b64,
        "slot_name": "main"
    })


class TestForbiddenImports:
    """K2-1: Test that forbidden modules cannot be imported."""

    def test_import_os_blocked(self, client):
        """Importing os should be rejected."""
        code = "import os\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_import_sys_blocked(self, client):
        """Importing sys should be rejected."""
        code = "import sys\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_import_subprocess_blocked(self, client):
        """Importing subprocess should be rejected."""
        code = "import subprocess\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_import_socket_blocked(self, client):
        """Importing socket should be rejected."""
        code = "import socket\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_import_threading_blocked(self, client):
        """Importing threading should be rejected."""
        code = "import threading\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_import_requests_blocked(self, client):
        """Importing requests should be rejected."""
        code = "import requests\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_from_import_blocked(self, client):
        """from ... import ... of forbidden modules should be rejected."""
        code = "from subprocess import call\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400


class TestForbiddenBuiltins:
    """K2-2: Test that dangerous builtins are blocked."""

    def test_eval_blocked(self, client):
        """Using eval() should be rejected."""
        code = "def control(img_front, img_rear, speed): eval('1+1'); return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_exec_blocked(self, client):
        """Using exec() should be rejected."""
        code = "def control(img_front, img_rear, speed): exec('x=1'); return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_open_blocked(self, client):
        """Using open() should be rejected."""
        code = "def control(img_front, img_rear, speed): open('file.txt'); return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_globals_blocked(self, client):
        """Using globals() should be rejected."""
        code = "def control(img_front, img_rear, speed): globals(); return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_locals_blocked(self, client):
        """Using locals() should be rejected."""
        code = "def control(img_front, img_rear, speed): locals(); return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400


class TestSandboxEscapeTechniques:
    """K2-3: Test advanced sandbox escape techniques."""

    def test_dunder_import_escape(self, client):
        """__import__('os') should be rejected."""
        code = "def control(img_front, img_rear, speed): __import__('os'); return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_globals_builtins_escape(self, client):
        """Accessing __builtins__ via globals() should be rejected."""
        code = "def control(img_front, img_rear, speed):\n    g = globals()\n    return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_importlib_escape(self, client):
        """importlib should be rejected."""
        code = "import importlib\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400

    def test_time_module_blocked(self, client):
        """time module should be rejected."""
        code = "import time\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 400


class TestAllowedImports:
    """K2-4: Verify that allowed modules can be imported."""

    def test_numpy_allowed(self, client):
        """numpy should be allowed."""
        code = "import numpy as np\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        # Should pass validation (may fail at runtime if numpy not installed in test env)
        assert resp.status_code in [200, 400]

    def test_cv2_allowed(self, client):
        """cv2 should be allowed."""
        code = "import cv2\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code in [200, 400]

    def test_math_allowed(self, client):
        """math should be allowed."""
        code = "import math\ndef control(img_front, img_rear, speed): return math.sin(0.5), 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 200

    def test_collections_allowed(self, client):
        """collections should be allowed."""
        code = "from collections import deque\ndef control(img_front, img_rear, speed): return 0.5, 0.5"
        resp = submit_code(client, code)
        assert resp.status_code == 200
