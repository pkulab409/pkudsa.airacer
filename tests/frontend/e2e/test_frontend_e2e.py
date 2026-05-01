import pytest
import os
import tempfile
from playwright.sync_api import Page, expect

def test_admin_login(page: Page, server: str):
    page.goto(f"{server}/admin/")
    
    # Should see login overlay
    expect(page.locator("#login-overlay")).to_be_visible()
    
    # Login with wrong password
    page.fill("#pwd-input", "wrong")
    page.click("button:has-text('登录')")
    expect(page.locator("#login-error")).to_be_visible()
    
    # Login with correct password
    page.fill("#pwd-input", "12345")
    page.click("button:has-text('登录')")
    
    # Should see main app
    expect(page.locator("#app")).to_be_visible()
    expect(page.locator("#login-overlay")).to_be_hidden()

def test_create_zone(page: Page, server: str):
    page.goto(f"{server}/admin/")
    
    # Login
    page.fill("#pwd-input", "12345")
    page.click("button:has-text('登录')")
    
    # Navigate to teams/zones
    page.click("a:has-text('队伍管理')")
    
    # Create zone
    page.fill("#nz-id", "e2e_zone")
    page.fill("#nz-name", "E2E Test Zone")
    page.fill("#nz-desc", "Created by Playwright")
    page.fill("#nz-laps", "3")
    page.click("button:has-text('创建赛区')")
    
    # Verify toast
    expect(page.locator(".toast-body")).to_contain_text("赛区已创建")
    
    # Verify zone appears in sidebar
    expect(page.locator("#zone-list")).to_contain_text("E2E Test Zone")

def test_team_registration(page: Page, server: str):
    # Register via API directly since the submit page doesn't have a register form
    import requests
    resp = requests.post(f"{server}/api/register", json={
        "zone_id": "e2e_zone",
        "team_id": "e2e_team",
        "team_name": "E2E Team",
        "password": "team_pwd"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "registered"

def test_team_login_and_submit(page: Page, server: str):
    page.goto(f"{server}/submit/")
    
    # Wait for zones to load (the select element itself)
    page.wait_for_selector("#input-zone", timeout=5000)
    page.wait_for_timeout(1000)  # Give time for options to populate
    
    # Login
    page.fill("#input-team-id", "e2e_team")
    page.fill("#input-password", "team_pwd")
    page.select_option("#input-zone", "e2e_zone")
    page.click("#btn-login")
    
    # Should see main panel
    expect(page.locator("#main-panel")).to_be_visible(timeout=5000)
    expect(page.locator("#header-team-name")).to_contain_text("e2e_team")
    
    # Create a temp .py file and upload it
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def control(img_front, img_rear, speed):\n    return 0.5, 0.5\n")
        tmp_path = f.name
    
    try:
        # Upload the file
        page.set_input_files("#file-input-hidden", tmp_path)
        
        # Wait for file to be selected
        expect(page.locator("#dz-filename")).to_be_visible(timeout=3000)
        
        # Click upload
        page.click("#btn-upload")
        
        # Verify success toast
        expect(page.locator("#toast-body")).to_contain_text("上传成功", timeout=5000)
    finally:
        os.unlink(tmp_path)
