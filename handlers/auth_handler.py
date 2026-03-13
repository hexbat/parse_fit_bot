"""Команда /authuser — управление списком allowed_users для администраторов."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config import load_config, save_config

logger = logging.getLogger(__name__)


async def authuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавляет нового пользователя в allowed_users (только для админов)."""
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    bot_data = context.bot_data

    no_auth = bot_data.get("no_auth", False)
    if no_auth:
        await update.message.reply_text(
            "Авторизация отключена (--no-auth). Список пользователей сейчас не используется."
        )
        return

    admin_users = bot_data.get("admin_users", [])
    if user_id not in admin_users:
        await update.message.reply_text("Access denied.")
        logger.warning("Пользователь %s попытался вызвать /authuser без прав", user_id)
        return

    if not context.args:
        await update.message.reply_text("Использование: /authuser <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("user_id должен быть числом.")
        return

    config = load_config()
    allowed_users = config.get("allowed_users", [])
    if target_id in allowed_users:
        await update.message.reply_text(f"user_id {target_id} уже есть в списке allowed_users.")
        return

    allowed_users.append(target_id)
    config["allowed_users"] = allowed_users
    save_config(config)

    # Обновим кэш в bot_data, чтобы новые настройки применялись сразу.
    bot_data["allowed_users"] = allowed_users

    await update.message.reply_text(f"user_id {target_id} добавлен в allowed_users.")
    logger.info("Админ %s добавил user_id %s в allowed_users", user_id, target_id)


def register_auth_handlers(application) -> None:
    """Регистрирует handler /authuser."""
    application.add_handler(CommandHandler("authuser", authuser_command))

