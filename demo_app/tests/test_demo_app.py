from playwright.sync_api import Page


def test_home_page_loads(page: Page, base_url: str) -> None:
    page.goto(base_url)
    assert "Demo Shop" in page.title()


def test_home_page_has_nav(page: Page, base_url: str) -> None:
    page.goto(base_url)
    assert page.locator("nav").is_visible()
    assert page.locator("nav").get_by_role("link", name="Товары").is_visible()
    assert page.locator("nav").get_by_role("link", name="Войти").is_visible()


def test_items_page_loads(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items")
    assert "Товары" in page.title()


def test_items_page_shows_products(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items")
    assert page.get_by_text("Ноутбук").is_visible()
    assert page.get_by_text("Мышь").is_visible()
    assert page.get_by_text("Клавиатура").is_visible()


def test_item_detail_opens(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items")
    page.get_by_role("link", name="Подробнее").first.click()
    assert page.get_by_text("Артикул:").is_visible()
    assert page.get_by_text("Цена:").is_visible()


def test_item_detail_back_button(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items/1")
    page.get_by_role("link", name="← Назад к товарам").click()
    assert "/items" in page.url


def test_login_page_loads(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/login")
    assert page.locator("#username").is_visible()
    assert page.locator("#password").is_visible()


def test_login_success(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill("#username", "admin")
    page.fill("#password", "password123")
    page.get_by_role("button", name="Войти").click()
    assert "/dashboard" in page.url
    assert page.get_by_text("Личный кабинет").is_visible()


def test_login_wrong_password(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill("#username", "admin")
    page.fill("#password", "wrongpass")
    page.get_by_role("button", name="Войти").click()
    assert page.get_by_text("Неверный логин или пароль").is_visible()


def test_dashboard_requires_auth(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/dashboard")
    assert "/login" in page.url


def test_logout(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill("#username", "admin")
    page.fill("#password", "password123")
    page.get_by_role("button", name="Войти").click()
    page.get_by_role("link", name="Выйти (admin)").click()
    assert page.locator("nav").get_by_role("link", name="Войти").is_visible()


def test_404_page(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/nonexistent-page")
    assert page.get_by_text("404").is_visible()


def test_cart_empty_by_default(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/cart")
    assert page.locator("#empty-cart-message").is_visible()


def test_cart_add_item(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items")
    page.get_by_role("button", name="В корзину").first.click()
    assert "/cart" not in page.url
    page.goto(f"{base_url}/cart")
    assert not page.locator("#empty-cart-message").is_visible()


def test_cart_badge_updates(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items")
    page.get_by_role("button", name="В корзину").first.click()
    assert page.locator("nav .cart-badge").is_visible()


def test_cart_add_from_detail(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items/2")
    page.get_by_role("button", name="В корзину").click()
    page.goto(f"{base_url}/cart")
    assert page.get_by_text("Мышь").is_visible()


def test_cart_remove_item(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items/1")
    page.get_by_role("button", name="В корзину").click()
    page.goto(f"{base_url}/cart")
    page.get_by_role("button", name="Удалить").click()
    assert page.locator("#empty-cart-message").is_visible()


def test_cart_clear(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items")
    page.get_by_role("button", name="В корзину").first.click()
    page.goto(f"{base_url}/cart")
    page.get_by_role("button", name="Очистить корзину").click()
    assert page.locator("#empty-cart-message").is_visible()


def test_cart_shows_total(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items/2")
    page.get_by_role("button", name="В корзину").click()
    page.goto(f"{base_url}/cart")
    assert page.get_by_text("Итого: 1500 ₽").is_visible()


def test_nonexistent_item(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/items/999")
    assert page.get_by_text("Товар найден").is_visible()


def test_wrong_title(page: Page, base_url: str) -> None:
    page.goto(base_url)
    assert "Amazon" in page.title(), "Ожидался заголовок Amazon"


def test_login_as_unknown_user(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill("#username", "hacker")
    page.fill("#password", "12345")
    page.get_by_role("button", name="Войти").click()
    assert "/dashboard" in page.url, "Ожидался редирект в кабинет"
