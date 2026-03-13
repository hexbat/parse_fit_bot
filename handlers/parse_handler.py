"""Handlers для команд /parse и /run — работа с FIT-файлами."""
import logging
import tempfile
import time
from pathlib import Path

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from parse_fit import convert_fit_to_txt
from fit_common import decode_fit_to_messages, extract_common_metrics
from analysis_run import build_run_metrics

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
    logger.info("Пользователь %s вызвал /parse", update.effective_user.id if update.effective_user else "unknown")
    context.user_data["waiting_fit"] = True
    context.user_data["fit_mode"] = "parse"
    await update.message.reply_text("Отправьте файл в формате .fit")


async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /run (анализ беговой тренировки)."""
    if not _is_allowed(update, context):
        await update.message.reply_text("Access denied.")
        return
    logger.info("Пользователь %s вызвал /run", update.effective_user.id if update.effective_user else "unknown")
    context.user_data["waiting_fit"] = True
    context.user_data["fit_mode"] = "run"
    await update.message.reply_text("Отправьте беговую тренировку в формате .fit")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик входящего документа."""
    if not context.user_data.pop("waiting_fit", False):
        return
    mode = context.user_data.pop("fit_mode", "parse")

    if not _is_allowed(update, context):
        await update.message.reply_text("Access denied.")
        return

    document = update.message.document
    if not document:
        return

    logger.info(
        "Получен файл %s от user_id=%s (mode=%s)",
        document.file_name,
        update.effective_user.id if update.effective_user else "unknown",
        mode,
    )
    file_name = document.file_name or ""
    if not file_name.lower().endswith(".fit"):
        await update.message.reply_text("Please send a .fit file")
        return

    await update.message.reply_text("Файл получен, начинаю обработку…")
    logger.info("Начата обработка файла %s (mode=%s)", file_name, mode)

    with tempfile.TemporaryDirectory() as tmpdir:
        fit_path = Path(tmpdir) / "input.fit"
        txt_path = Path(tmpdir) / "output.txt"
        common_json_path = Path(tmpdir) / "common.json"
        run_json_path = Path(tmpdir) / "run.json"

        try:
            file = await context.bot.get_file(document.file_id)
            await file.download_to_drive(str(fit_path))

            await update.message.reply_text("Файл сохранён, запускаю конвертацию…")
            logger.info("Файл %s сохранён во временную директорию", file_name)

            convert_fit_to_txt(str(fit_path), str(txt_path))

            # Анализ через pydantic-модели
            try:
                analysis_start = time.perf_counter()
                await update.message.reply_text("Конвертация завершена, выполняю анализ…")
                logger.info("Запуск анализа файла %s (mode=%s)", file_name, mode)

                messages = decode_fit_to_messages(str(fit_path))
                if mode == "parse":
                    common_metrics = extract_common_metrics(messages)
                    common_json = common_metrics.model_dump_json(indent=2, ensure_ascii=False)
                    common_json_path.write_text(common_json, encoding="utf-8")
                elif mode == "run":
                    user_id = update.effective_user.id if update.effective_user else None
                    run_metrics = build_run_metrics(messages, user_id=user_id)
                    run_json = run_metrics.model_dump_json(indent=2, ensure_ascii=False)
                    run_json_path.write_text(run_json, encoding="utf-8")

                analysis_time = time.perf_counter() - analysis_start
                await update.message.reply_text(
                    f"Анализ завершён за {analysis_time:.1f} сек."
                )
                logger.info(
                    "Анализ файла %s завершён за %.1f сек (mode=%s)",
                    file_name,
                    analysis_time,
                    mode,
                )
            except Exception as analysis_err:  # noqa: BLE001
                logger.exception("Ошибка анализа метрик для файла %s: %s", file_name, analysis_err)
                common_json_path = None
                run_json_path = None

            if txt_path.exists() and txt_path.stat().st_size > 0:
                output_name = Path(file_name).stem + ".txt"
                with open(txt_path, "rb") as f:
                    await update.message.reply_document(document=f, filename=output_name)

                if mode == "parse":
                    # Если удалось сформировать common.json — отправляем его вторым файлом
                    if common_json_path is not None and common_json_path.exists():
                        json_name = Path(file_name).stem + "_common.json"
                        with open(common_json_path, "rb") as jf:
                            await update.message.reply_document(document=jf, filename=json_name)
                elif mode == "run":
                    # Для режима /run отправляем специализированный JSON анализа
                    if run_json_path is not None and run_json_path.exists():
                        json_name = Path(file_name).stem + "_run.json"
                        with open(run_json_path, "rb") as jf:
                            await update.message.reply_document(document=jf, filename=json_name)

                logger.info(
                    "Файлы для %s успешно отправлены пользователю %s (mode=%s)",
                    file_name,
                    update.effective_user.id if update.effective_user else "unknown",
                    mode,
                )
            else:
                await update.message.reply_text("Ошибка конвертации: не удалось преобразовать файл.")
                logger.warning("Конвертация не создала файл: %s", file_name)

        except Exception as e:
            logger.exception("Ошибка при обработке файла %s: %s", file_name, e)
            await update.message.reply_text(f"Ошибка конвертации: {e}")


def register_parse_handlers(application, no_auth: bool, allowed_users: list) -> None:
    """Регистрирует handlers для /parse, /run и обработки документов."""
    application.bot_data.setdefault("no_auth", no_auth)
    application.bot_data.setdefault("allowed_users", allowed_users)
    application.add_handler(CommandHandler("parse", parse_command))
    application.add_handler(CommandHandler("run", run_command))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
