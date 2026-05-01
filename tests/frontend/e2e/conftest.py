import os
import signal
import subprocess
import sys
import tempfile
import time

import pytest
import requests


@pytest.fixture(scope="module")
def server():
    env = os.environ.copy()
    env["DB_PATH"] = tempfile.mktemp(suffix=".db")
    env["SUBMISSIONS_DIR"] = tempfile.mkdtemp()
    env["RECORDINGS_DIR"] = tempfile.mkdtemp()
    env["ADMIN_PASSWORD"] = "12345"
    env["PYTHONPATH"] = os.getcwd()

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8002",
        ],
        env=env,
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    base_url = "http://127.0.0.1:8002"
    deadline = time.time() + 10
    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"Test server exited early:\n{stdout}\n{stderr}")
        try:
            requests.get(f"{base_url}/api/recordings", timeout=0.5)
            break
        except requests.RequestException:
            time.sleep(0.2)
    else:
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(f"Test server did not start:\n{stdout}\n{stderr}")

    requests.post(
        f"{base_url}/api/admin/zones",
        json={"id": "zone1", "name": "Zone 1", "description": "", "total_laps": 3},
        auth=("admin", "12345"),
        timeout=2,
    )

    yield base_url

    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    if os.path.exists(env["DB_PATH"]):
        os.remove(env["DB_PATH"])
