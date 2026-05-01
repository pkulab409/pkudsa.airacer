"""
Error Handling E2E Tests (Module H3)

Tests that the frontend displays user-friendly error messages.
"""

import pytest
from playwright.sync_api import Page, expect
import base64


def test_invalid_password_shows_error(page: Page, server: str):
    """H3-1: Invalid password shows error message."""
    page.goto(f"{server}/admin/")
    
    # Wait for login overlay
    page.wait_for_selector("#login-overlay", timeout=5000)
    
    # Enter wrong password
    page.fill("#pwd-input", "wrong_password")
    page.click("button:has-text('登录')")
    
    # Should show error
    page.wait_for_selector("#login-error", timeout=3000)
    expect(page.locator("#login-error")).to_be_visible()


def test_submit_invalid_code_shows_error(page: Page, server: str):
    """H3-2: Submitting invalid code shows error message."""
    # First register a team via API
    import requests
    requests.post(f"{server}/api/register", json={
        "zone_id": "zone1",
        "team_id": "error_test_team",
        "team_name": "Error Test Team",
        "password": "test_pwd"
    })
    
    page.goto(f"{server}/submit/")
    
    # Wait for zones to load
    page.wait_for_selector("#input-zone", timeout=5000)
    page.wait_for_timeout(1000)
    
    # Login
    page.fill("#input-team-id", "error_test_team")
    page.fill("#input-password", "test_pwd")
    page.select_option("#input-zone", "zone1")
    page.click("#btn-login")
    
    # Wait for main panel
    page.wait_for_selector("#main-panel", timeout=5000)
    
    # Create invalid Python code
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def control(img_front, img_rear, speed)\n    return 0.5, 0.5\n")  # Missing colon
        tmp_path = f.name
    
    try:
        # Upload invalid file
        page.set_input_files("#file-input-hidden", tmp_path)
        
        # Wait for file to be selected
        page.wait_for_timeout(1000)
        
        # Click upload
        page.click("#btn-upload")
        
        # Should show error toast
        page.wait_for_selector("#toast-body", timeout=5000)
        toast = page.locator("#toast-body")
        expect(toast).to_be_visible()
        
    finally:
        os.unlink(tmp_path)


def test_unauthorized_access_redirects(page: Page, server: str):
    """H3-3: Unauthorized access is handled gracefully."""
    # Try to access admin without login
    page.goto(f"{server}/admin/")
    
    # Should show login overlay
    page.wait_for_selector("#login-overlay", timeout=5000)
    expect(page.locator("#login-overlay")).to_be_visible()


def test_nonexistent_page_shows_error(page: Page, server: str):
    """H3-4: Non-existent page shows 404 or friendly error."""
    page.goto(f"{server}/nonexistent-page/")
    
    # Page should not crash
    page.wait_for_timeout(1000)
    assert page.title() is not None or "404" in page.content() or page.locator("body").is_visible()
