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
    await update.message.reply_text("Привет! Используйте /parse для конвертации FIT в TXT.")


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
    else:
        allowed_users = []

    application = (
        Application.builder()
        .token(token)
        .read_timeout(60)
        .media_write_timeout(120)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    register_parse_handlers(application, no_auth=args.no_auth, allowed_users=allowed_users)

    logger.info("Бот запущен (polling). --no-auth: %s", args.no_auth)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
