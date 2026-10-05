"""Pages for a logged-in user.

`use_auth = "admin"` makes every test here start with admin's session cookie:
the login itself runs once (auth_admin in conftest.py), not before each test.
"""
from playwright.sync_api import Page

use_auth = "admin"


def test_dashboard_opens_without_login(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/dashboard")
    assert page.url.endswith("/dashboard")
    assert "Личный кабинет" in page.inner_text("h1")


def test_dashboard_shows_username(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/dashboard")
    assert page.inner_text("strong") == "admin"


def test_nav_shows_logout_for_user(page: Page, base_url: str) -> None:
    page.goto(base_url)
    assert page.is_visible("text=Выйти (admin)")
    assert not page.is_visible("nav >> text=Войти")
