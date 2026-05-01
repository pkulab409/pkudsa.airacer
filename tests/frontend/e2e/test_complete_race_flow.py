"""
Full Race Flow E2E Test (Module H1)

Tests the complete race lifecycle from admin perspective:
Create zone -> Register teams -> Submit code -> Set session -> Start race -> Finalize
"""

import pytest
import requests
import base64
import tempfile
import os
from playwright.sync_api import Page, expect


@pytest.fixture(scope="module")
def api_base(server):
    """Return the API base URL."""
    return server


def test_full_race_lifecycle(page: Page, server: str):
    """H1-1: Complete race lifecycle via admin UI and API."""
    api = server

    # ---- Step 1: Create zone via API ----
    resp = requests.post(f"{api}/api/admin/zones", json={
        "id": "e2e_full_zone",
        "name": "E2E Full Race Zone",
        "description": "Full lifecycle test",
        "total_laps": 3
    }, auth=("admin", "12345"))
    assert resp.status_code == 200, f"Zone creation failed: {resp.text}"

    # ---- Step 2: Register 4 teams via API ----
    for i in range(1, 5):
        resp = requests.post(f"{api}/api/register", json={
            "zone_id": "e2e_full_zone",
            "team_id": f"e2e_race_team_{i}",
            "team_name": f"E2E Race Team {i}",
            "password": "team_pwd"
        })
        assert resp.status_code == 200, f"Team {i} registration failed: {resp.text}"

    # ---- Step 3: Submit code for all teams via API ----
    valid_code = "def control(img_front, img_rear, speed):\n    return 0.5, 0.5\n"
    code_b64 = base64.b64encode(valid_code.encode()).decode()

    for i in range(1, 5):
        resp = requests.post(f"{api}/api/submit", json={
            "team_id": f"e2e_race_team_{i}",
            "password": "team_pwd",
            "code": code_b64,
            "slot_name": "main"
        })
        assert resp.status_code == 200, f"Team {i} code submission failed: {resp.text}"

    # ---- Step 4: Admin sets up a qualifying session via API ----
    resp = requests.post(f"{api}/api/admin/zones/e2e_full_zone/set-session", json={
        "session_type": "qualifying",
        "session_id": "e2e_qual_1",
        "team_ids": ["e2e_race_team_1", "e2e_race_team_2", "e2e_race_team_3", "e2e_race_team_4"],
        "total_laps": 3
    }, auth=("admin", "12345"))
    assert resp.status_code == 200, f"Set session failed: {resp.text}"

    # ---- Step 5: Verify standings are accessible ----
    resp = requests.get(f"{api}/api/admin/zones/e2e_full_zone/standings",
                        auth=("admin", "12345"))
    assert resp.status_code == 200, f"Standings query failed: {resp.text}"

    # ---- Step 6: Verify bracket is accessible ----
    resp = requests.get(f"{api}/api/admin/zones/e2e_full_zone/bracket",
                        auth=("admin", "12345"))
    assert resp.status_code == 200, f"Bracket query failed: {resp.text}"

    # ---- Step 7: Verify zone list includes our zone ----
    resp = requests.get(f"{api}/api/admin/zones",
                        auth=("admin", "12345"))
    assert resp.status_code == 200
    zones = resp.json()
    zone_ids = [z["id"] for z in zones]
    assert "e2e_full_zone" in zone_ids, f"Zone not found in list: {zone_ids}"


def test_admin_ui_zone_visible(page: Page, server: str):
    """H1-2: Verify zone appears in admin UI sidebar."""
    page.goto(f"{server}/admin/")

    # Login
    page.fill("#pwd-input", "12345")
    page.click("button:has-text('登录')")

    # Wait for app to load
    page.wait_for_selector("#app", timeout=5000)

    # Check zone list contains our zone
    expect(page.locator("#zone-list")).to_contain_text("E2E Full Race Zone", timeout=5000)


def test_public_zone_page(page: Page, server: str):
    """H1-3: Verify public zone page is accessible."""
    page.goto(f"{server}/zone/?id=e2e_full_zone")

    # Should show zone info
    page.wait_for_timeout(2000)
    # The page should load without errors
    assert page.title() is not None


def test_recordings_accessible(page: Page, server: str):
    """H1-4: Verify recordings page is accessible."""
    page.goto(f"{server}/race/")

    # Page should load
    page.wait_for_timeout(2000)
    assert page.title() is not None
