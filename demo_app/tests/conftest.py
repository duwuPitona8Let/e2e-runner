"""Shared fixtures for demo_app tests. e2e_runner picks this file up automatically."""
from playwright.sync_api import Page


def auth_admin(page: Page, base_url: str) -> None:
    """Log in as admin once per run; test files with `use_auth = "admin"` start already logged in."""
    page.goto(f"{base_url}/login")
    page.fill("#username", "admin")
    page.fill("#password", "password123")
    page.click("button[type=submit]")
    page.wait_for_url("**/dashboard")
