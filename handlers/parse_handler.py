"""Handler команды /parse — конвертация FIT в TXT."""
import logging
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from parse_fit import convert_fit_to_txt

logger = logging.getLogger(__name__)


def _is_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, имеет ли пользователь доступ к боту."""
    no_auth = context.bot_data.get("no_auth", False)
    if no_auth:
        return True
    allowed_users = context.bot_data.get("allowed_users", [])
    user_id = update.effective_user.id if update.effective_user else None
    return user_id is not None and user_id in allowed_users


async def parse_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /parse."""
    if not _is_allowed(update, context):
        await update.message.reply_text("Access denied.")
        return
    context.user_data["waiting_fit"] = True
    await update.message.reply_text("Отправьте файл в формате .fit")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик входящего документа."""
    if not context.user_data.pop("waiting_fit", False):
        return

    if not _is_allowed(update, context):
        await update.message.reply_text("Access denied.")
        return

    document = update.message.document
    if not document:
        return

    file_name = document.file_name or ""
    if not file_name.lower().endswith(".fit"):
        await update.message.reply_text("Please send a .fit file")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        fit_path = Path(tmpdir) / "input.fit"
        txt_path = Path(tmpdir) / "output.txt"

        try:
            file = await context.bot.get_file(document.file_id)
            await file.download_to_drive(str(fit_path))

            convert_fit_to_txt(str(fit_path), str(txt_path))

            if txt_path.exists() and txt_path.stat().st_size > 0:
                output_name = Path(file_name).stem + ".txt"
                with open(txt_path, "rb") as f:
                    await update.message.reply_document(document=f, filename=output_name)
                logger.info("Файл %s успешно сконвертирован для user_id=%s", file_name, update.effective_user.id)
            else:
                await update.message.reply_text("Ошибка конвертации: не удалось преобразовать файл.")
                logger.warning("Конвертация не создала файл: %s", file_name)

        except Exception as e:
            logger.exception("Ошибка при обработке файла %s: %s", file_name, e)
            await update.message.reply_text(f"Ошибка конвертации: {e}")


def register_parse_handlers(application, no_auth: bool, allowed_users: list) -> None:
    """Регистрирует handlers для /parse."""
    application.bot_data["no_auth"] = no_auth
    application.bot_data["allowed_users"] = allowed_users
    application.add_handler(CommandHandler("parse", parse_command))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
