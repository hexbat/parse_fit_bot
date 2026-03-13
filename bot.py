"""Точка входа Telegram-бота parse_fit_bot."""
import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import load_config
from handlers.parse_handler import register_parse_handlers
from handlers.zones_handler import register_zones_handlers
from handlers.auth_handler import register_auth_handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# httpx логирует URL запросов (включая токен) — отключаем в целях безопасности
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    user = update.effective_user
    if user:
        logger.info("/start от пользователя id=%s", user.id)
    text = (
        "Привет! Я бот для конвертации Garmin FIT и анализа тренировок.\n\n"
        "Доступные команды:\n"
        "/parse — конвертировать FIT в TXT (+ общий JSON *_common.json)\n"
        "/run — анализ беговой тренировки (splits, зоны, JSON *_run.json)\n"
        "/zones — настроить индивидуальные пульсовые зоны для анализа бега\n"
        "/authuser <user_id> — добавить пользователя с указанным id в белый список (только для админов)\n"
        # В будущем здесь появятся /interval и /strenght
    )
    await update.message.reply_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="parse_fit_bot — конвертация FIT в TXT")
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Разрешить доступ всем пользователям (без проверки config.json)",
    )
    args = parser.parse_args()

    load_dotenv(Path(__file__).parent / ".env")
    token = os.environ.get("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN не задан. Добавьте его в .env")
        raise SystemExit(1)

    if not args.no_auth:
        config = load_config()
        allowed_users = config.get("allowed_users", [])
        admin_users = config.get("admin_users", [])
    else:
        allowed_users = []
        admin_users = []

    application = (
        Application.builder()
        .token(token)
        .read_timeout(60)
        .media_write_timeout(120)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    register_parse_handlers(application, no_auth=args.no_auth, allowed_users=allowed_users)
    register_zones_handlers(application)
    register_auth_handlers(application)

    # Данные авторизации для хэндлеров
    application.bot_data["no_auth"] = args.no_auth
    application.bot_data["allowed_users"] = allowed_users
    application.bot_data["admin_users"] = admin_users

    logger.info("Бот запущен (polling). --no-auth: %s", args.no_auth)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
