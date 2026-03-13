# parse_fit_bot

Telegram-бот для конвертации файлов Garmin FIT в текстовый формат (JSON).

Репозиторий: https://github.com/hexbat/parse_fit_bot

## Требования

- Python 3.10+
- Telegram Bot Token (от [@BotFather](https://t.me/BotFather))

## Установка

### 1. Клонирование и переход в каталог

```bash
git clone https://github.com/hexbat/parse_fit_bot.git
cd parse_fit_bot
```

### 2. Виртуальное окружение (рекомендуется)

```bash
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Windows (cmd) / Linux / macOS
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # Linux/macOS
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Конфигурация

```bash
# Windows
copy .env.example .env
copy config.json.example config.json

# Linux / macOS
cp .env.example .env
cp config.json.example config.json
```

Отредактируйте `.env` — укажите токен бота:

```
BOT_TOKEN=ваш_токен_от_BotFather
```

При использовании авторизации отредактируйте `config.json` — добавьте свой Telegram `user_id` в `allowed_users`:

```json
{
  "allowed_users": [123456789]
}
```

**Как узнать свой user_id:** запустите бота в режиме `--no-auth`, отправьте команду `/start` и посмотрите в логе строку вида `/start от пользователя id=123456789`.

## Запуск

```bash
# С авторизацией (доступ только пользователям из config.json)
python bot.py

# Без авторизации (доступ всем)
python bot.py --no-auth
```

На Windows без активации venv:

```powershell
.\.venv\Scripts\python.exe bot.py --no-auth
```

## Использование

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и краткая справка по командам |
| `/parse` | Конвертация FIT → TXT и общий JSON (`*_common.json`) |
| `/run` | Анализ беговой тренировки: TXT + JSON со сплитами и зонами (`*_run.json`) |
| `/zones` | Настройка индивидуальных пульсовых зон для анализа бега |
| `/authuser <user_id>` | Добавить `user_id` в `allowed_users` (доступно только администраторам) |

### Порядок действий

1. Отправьте боту `/parse`
2. Отправьте файл с расширением `.fit`
3. Получите файл `.txt` (JSON с данными FIT)

## Ограничения

- Максимальный размер файла в Telegram — около 20 MB
- Для больших файлов таймауты отправки увеличены (до 2 минут)

## Конфигурация

| Файл | Описание |
|------|----------|
| `.env` | `BOT_TOKEN` — токен бота (обязательно) |
| `config.json` | `allowed_users` — список `user_id` при запуске без `--no-auth`; `admin_users` — список администраторов, которым доступна команда `/authuser` |
