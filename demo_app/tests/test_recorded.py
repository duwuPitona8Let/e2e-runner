"""Recorded with `e2e record` from http://localhost:8080 on 2026-10-05.

Run: e2e run demo_app/tests/test_recorded.py -u http://localhost:8080
"""
from playwright.sync_api import Page, expect


def test_recorded(page: Page) -> None:
    page.goto("/")
    page.get_by_role("link", name="Посмотреть товары").click()
    page.get_by_role("link", name="Подробнее").first.click()
    page.get_by_role("button", name="В корзину").click()
    # Added by hand: the recording only clicked; this checks the item really got into the cart.
    expect(page.locator(".cart-badge")).to_have_text("1")
