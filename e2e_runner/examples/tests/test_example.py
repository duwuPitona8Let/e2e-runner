"""
Example E2E tests for https://example.com.

Each test function receives a Playwright `page` object.
Use standard assert statements — failures are caught and reported automatically.
"""

from playwright.sync_api import Page


def test_page_loads(page: Page) -> None:
    page.goto("https://example.com")
    assert page.title() != "", "Page should have a title"


def test_heading_visible(page: Page) -> None:
    page.goto("https://example.com")
    heading = page.locator("h1")
    assert heading.is_visible(), "H1 heading should be visible"


def test_more_information_link(page: Page) -> None:
    page.goto("https://example.com")
    link = page.get_by_role("link", name="More information")
    assert link.is_visible(), "More information link should be present"
    link.click()
    assert "iana.org" in page.url, f"Expected iana.org, got: {page.url}"
