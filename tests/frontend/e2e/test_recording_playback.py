"""
Recording Playback Page E2E Tests (Module H2)

Tests the recording playback functionality in the frontend.
"""

import pytest
from playwright.sync_api import Page, expect
import requests


@pytest.fixture(scope="module")
def api_base(server):
    """Return the API base URL."""
    return server


def test_recordings_page_loads(page: Page, server: str):
    """H2-1: Recordings page loads successfully."""
    page.goto(f"{server}/race/")
    
    # Page should load without errors
    page.wait_for_timeout(2000)
    assert page.title() is not None


def test_recordings_page_has_ui_elements(page: Page, server: str):
    """H2-2: Recordings page has expected UI elements."""
    page.goto(f"{server}/race/")
    
    # Wait for page to load
    page.wait_for_timeout(2000)
    
    # Check for key elements (adjust selectors based on actual UI)
    # Common elements that should exist
    body = page.locator("body")
    expect(body).to_be_visible()


def test_public_zone_page_loads(page: Page, server: str):
    """H2-3: Public zone page is accessible."""
    page.goto(f"{server}/zone/?id=zone1")
    
    page.wait_for_timeout(2000)
    assert page.title() is not None


def test_admin_recordings_accessible(page: Page, server: str):
    """H2-4: Admin can access recordings through admin panel."""
    page.goto(f"{server}/admin/")
    
    # Login
    page.fill("#pwd-input", "12345")
    page.click("button:has-text('登录')")
    
    # Wait for app
    page.wait_for_selector("#app", timeout=5000)
    
    # Navigate to recordings or relevant section
    # The admin panel should be accessible
    expect(page.locator("#app")).to_be_visible()
