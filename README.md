# e2e_runner

[![CI](https://github.com/duwuPitona8Let/e2e-runner/actions/workflows/ci.yml/badge.svg)](https://github.com/duwuPitona8Let/e2e-runner/actions/workflows/ci.yml)

Инструмент командной строки для автоматизированного E2E-тестирования веб-приложений. Написан на Python, использует Playwright для управления браузером.

---

## Содержание

- [Возможности](#возможности)
- [Установка](#установка)
- [Быстрый старт](#быстрый старт)
- [Как писать тесты](#как-писать-тесты)
- [Команды](#команды)
- [Конфигурационный файл](#конфигурационный-файл)
- [TUI-интерфейс](#tui-интерфейс)
- [Демо-приложение](#демо-приложение)

---

## Возможности

- Автоматическое обнаружение тестов по шаблону `test_*.py`
- Параллельный запуск тестов (`--workers N`)
- Повтор упавших тестов (`--retry N`)
- Запись тестов в браузере без написания кода (`e2e record`)
- Скриншоты и Playwright trace при падении теста
- История прогонов в SQLite
- Отчёты в форматах HTML и JSON
- Конфигурация через файл `e2e.yaml`
- Интерактивный TUI-интерфейс

---

## Установка

```bash
# 1. Клонировать репозиторий
git clone <url>
cd e2e_runner

# 2. Установить пакет
pip install -e .

# 3. Установить браузер Chromium (один раз)
playwright install chromium
```

---

## Быстрый старт

```bash
# Создать файл конфигурации в папке проекта
e2e init

# Отредактировать e2e.yaml — указать base_url и путь к тестам
# Запустить тесты
e2e run

# Или без конфига — явно указать параметры
e2e run tests/ -u http://localhost:8080
```

---

## Как писать тесты

Создайте файл с именем `test_*.py` и напишите функции с префиксом `test_`:

```python
# test_example.py

def test_title(page, base_url):
    page.goto(base_url)
    assert "Мой сайт" in page.title()

def test_login(page, base_url):
    page.goto(f"{base_url}/login")
    page.fill("#username", "admin")
    page.fill("#password", "secret")
    page.click("button[type=submit]")
    assert page.url.endswith("/dashboard")

def test_without_browser():
    # тест без браузера — page и base_url не обязательны
    assert 2 + 2 == 4
```

**Правила:**
- Файл называется `test_*.py`
- Функция называется `test_*`
- Параметры `page` и `base_url` **опциональны** — инструмент сам их передаёт если они указаны в сигнатуре
- Никаких импортов из `e2e_runner` не требуется
- `AssertionError` → статус **FAILED**, любое другое исключение → **ERROR**

---

## Команды

### `e2e run` — запуск тестов

```bash
e2e run [PATH] [OPTIONS]
```

| Флаг | По умолчанию | Описание |
|---|---|---|
| `PATH` | `.` | Путь к папке или файлу с тестами |
| `-u`, `--base-url URL` | — | Адрес тестируемого приложения |
| `-p`, `--project NAME` | `default` | Название проекта для истории |
| `-k`, `--filter TEXT` | — | Фильтр по имени теста |
| `-n`, `--workers N` | `1` | Количество параллельных потоков |
| `--timeout MS` | `30000` | Таймаут действий браузера (мс) |
| `--retry N` | `0` | Повторить упавший тест N раз |
| `--fail-fast` | выкл | Остановить при первом падении |
| `--headed` | выкл | Показывать окно браузера |
| `--html PATH` | — | Сохранить HTML-отчёт |
| `--json PATH` | — | Сохранить JSON-отчёт |

```bash
# Примеры
e2e run tests/ -u http://localhost:8080
e2e run tests/ -u http://localhost:8080 -n 4 --retry 2
e2e run tests/ -k login --headed
e2e run tests/ --fail-fast --html report.html
```

---

### `e2e init` — создать конфиг

```bash
e2e init          # создать e2e.yaml в текущей папке
e2e init --force  # перезаписать существующий
```

---

### `e2e record` — записать тест в браузере

Открывает браузер с инспектором Playwright (`playwright codegen`). Пройдите сценарий мышкой и закройте окно браузера — шаги сохранятся как функция `test_*`. Адреса делаются относительными, поэтому тест работает с любым `-u`.

```bash
e2e record http://localhost:8080 -o tests/test_login.py   # создать файл
e2e record http://localhost:8080 -o tests/test_login.py   # дописать ещё один тест (test_login_2)
e2e record -o tests/test_cart.py -n test_add_to_cart      # URL из e2e.yaml, своё имя теста
e2e record -p shop                                         # URL из зарегистрированного проекта
```

Получившийся файл:

```python
from playwright.sync_api import Page, expect


def test_login(page: Page) -> None:
    page.goto("/login")
    page.locator("#username").fill("admin")
    page.locator("#password").fill("password123")
    page.get_by_role("button", name="Войти").click()
    expect(page.locator("h1")).to_contain_text("Личный кабинет")
```

---

### `e2e discover` — найти тесты без запуска

```bash
e2e discover tests/
e2e discover tests/ -k login
```

---

### `e2e history` — история прогонов

```bash
e2e history               # последние 20 прогонов
e2e history -p myapp      # только для проекта myapp
e2e history -n 50         # последние 50 прогонов
```

---

### `e2e report` — детали прогона

```bash
e2e report 42             # показать в терминале
e2e report 42 --html out.html
e2e report 42 --json out.json
```

---

### `e2e export` — экспорт прогона в файл

```bash
e2e export 42                        # report_42.html + report_42.json
e2e export 42 --format html          # только HTML
e2e export 42 --format json          # только JSON
e2e export 42 --html my_report.html  # задать имя файла
e2e export 42 --open                 # открыть в браузере после экспорта
```

---

### `e2e clean` — очистить историю

```bash
e2e clean                  # удалить всю историю (с подтверждением)
e2e clean --keep 10        # оставить последние 10 прогонов
e2e clean -p myapp         # только для проекта myapp
e2e clean -y               # без запроса подтверждения
```

---

### `e2e projects` — управление проектами

```bash
e2e projects add myapp http://localhost:8080 -d "Описание"
e2e projects list
e2e projects edit myapp -u http://localhost:9000
e2e projects remove myapp
e2e projects stats myapp
```

---

### `e2e ui` — TUI-интерфейс

```bash
e2e ui
```

---

## Конфигурационный файл

Команда `e2e init` создаёт файл `e2e.yaml` в текущей папке:

```yaml
project: default        # название проекта
base_url: ""            # адрес приложения, например http://localhost:8080
tests: .                # путь к тестам

workers: 1              # параллельные потоки
timeout: 30000          # таймаут в мс
retry: 0                # повторы при падении
fail_fast: false        # стоп при первом падении
headed: false           # видимый браузер

html_report: ""         # путь к HTML-отчёту (пусто = не сохранять)
json_report: ""         # путь к JSON-отчёту (пусто = не сохранять)
```

`e2e run` автоматически ищет `e2e.yaml` в текущей папке и выше по дереву директорий. **Флаги командной строки всегда имеют приоритет** над значениями из файла.

---

## TUI-интерфейс

Запустите `e2e ui` для работы через интерактивный терминальный интерфейс.

```
┌─ Конфигурация ──────┐  ┌─ Действия ──────────┐
│ Тесты   tests/      │  │  ▶  Запустить тесты  │
│ URL     localhost   │  │  ⚙  Настройки        │
│ Потоки  2  Retry 1  │  │     История          │
│ Таймаут 30000 мс    │  │  ✕  Выйти            │
└─────────────────────┘  └─────────────────────┘
```

**Экраны:**
- **Главный** — конфигурация и кнопки запуска
- **Настройки** — форма со всеми параметрами запуска
- **Результаты** — прогресс-бар, счётчики и таблица тестов в реальном времени
- **История** — список прогонов; Enter — открыть детали; кнопка 🗑 — очистить
- **Детали прогона** — результаты теста; Enter на упавшем тесте — открыть скриншот; кнопка ↓ — экспортировать

---

## Демо-приложение

В репозитории есть Flask-приложение для демонстрации инструмента:

```bash
# Запустить демо-приложение
cd demo_app
python3 app.py          # http://localhost:8080

# В другом терминале — запустить тесты
e2e run demo_app/tests -u http://localhost:8080
```

Демо-приложение содержит 22 теста: 19 проходят, 3 намеренно падают — для демонстрации `--retry` и `--fail-fast`.

Учётные данные: `admin / password123`, `user / qwerty`.

---

## Структура проекта

```
e2e_runner/
├── e2e_runner/
│   ├── cli.py          # точка входа, Click-команды
│   ├── discovery.py    # поиск и загрузка тестов
│   ├── runner.py       # выполнение тестов через Playwright
│   ├── recorder.py     # e2e record: запись тестов через playwright codegen
│   ├── reporter.py     # вывод в терминал, HTML/JSON отчёты
│   ├── storage.py      # SQLite хранилище истории
│   ├── tui.py          # TUI-интерфейс на Textual
│   ├── config.py       # чтение e2e.yaml
│   └── models.py       # модели данных
├── tests/              # unit- и интеграционные тесты самого инструмента
└── pyproject.toml

demo_app/
├── app.py              # Flask-приложение
├── templates/          # HTML-шаблоны
└── tests/
    └── test_demo_app.py
```
