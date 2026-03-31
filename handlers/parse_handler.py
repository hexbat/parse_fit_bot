"""Handlers для /parse, /run и /interval — работа с FIT-файлами."""
from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Literal, Optional

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from parse_fit import convert_fit_to_txt
from fit_common import decode_fit_to_messages, extract_common_metrics
from analysis_run import build_run_metrics
from analysis_interval import build_interval_json

logger = logging.getLogger(__name__)

FitMode = Literal["parse", "run", "interval"]


_MODE_COMMAND_MESSAGES: dict[FitMode, str] = {
    "parse": "Отправьте файл в формате .fit",
    "run": "Отправьте беговую тренировку в формате .fit",
    "interval": "Отправьте интервальную беговую тренировку в формате .fit",
}

_MODE_OUTPUT_SUFFIX: dict[FitMode, str] = {
    "parse": "_common.json",
    "run": "_run.json",
    "interval": "_interval.json",
}


def _is_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, имеет ли пользователь доступ к боту."""
    no_auth = context.bot_data.get("no_auth", False)
    if no_auth:
        return True
    allowed_users = context.bot_data.get("allowed_users", [])
    user_id = update.effective_user.id if update.effective_user else None
    return user_id is not None and user_id in allowed_users


def _prepare_fit_mode(context: ContextTypes.DEFAULT_TYPE, mode: FitMode) -> None:
    context.user_data["waiting_fit"] = True
    context.user_data["fit_mode"] = mode


async def _start_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: FitMode) -> None:
    if not _is_allowed(update, context):
        await update.message.reply_text("Access denied.")
        return
    _prepare_fit_mode(context, mode)
    logger.info(
        "Пользователь %s вызвал /%s",
        update.effective_user.id if update.effective_user else "unknown",
        mode,
    )
    await update.message.reply_text(_MODE_COMMAND_MESSAGES[mode])


async def parse_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /parse."""
    await _start_mode(update, context, "parse")


async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /run (анализ беговой тренировки)."""
    await _start_mode(update, context, "run")


async def interval_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /interval (анализ интервальной тренировки)."""
    await _start_mode(update, context, "interval")


def _build_analysis_payload(messages, mode: FitMode, user_id: Optional[int]) -> str:
    if mode == "parse":
        common_metrics = extract_common_metrics(messages)
        return json.dumps(
            common_metrics.model_dump(mode="json"), indent=2, ensure_ascii=False
        )
    if mode == "run":
        run_metrics = build_run_metrics(messages, user_id=user_id)
        return json.dumps(run_metrics.model_dump(mode="json"), indent=2, ensure_ascii=False)

    interval_data = build_interval_json(messages)
    return json.dumps(interval_data, indent=2, ensure_ascii=False)


def _analysis_output_name(file_name: str, mode: FitMode) -> str:
    return Path(file_name).stem + _MODE_OUTPUT_SUFFIX[mode]


async def _send_document(update: Update, path: Path, output_name: str) -> None:
    with open(path, "rb") as f:
        await update.message.reply_document(document=f, filename=output_name)


async def _send_outputs(
    update: Update,
    *,
    txt_path: Path,
    source_file_name: str,
    analysis_json_path: Optional[Path],
    mode: FitMode,
) -> None:
    output_name = Path(source_file_name).stem + ".txt"
    await _send_document(update, txt_path, output_name)

    if analysis_json_path is not None and analysis_json_path.exists():
        await _send_document(
            update, analysis_json_path, _analysis_output_name(source_file_name, mode)
        )


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик входящего документа."""
    if not context.user_data.pop("waiting_fit", False):
        return
    mode_raw = context.user_data.pop("fit_mode", "parse")
    mode: FitMode = mode_raw if mode_raw in ("parse", "run", "interval") else "parse"

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
        analysis_json_path = Path(tmpdir) / "analysis.json"
        analysis_ready = False

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
                user_id = update.effective_user.id if update.effective_user else None
                payload = _build_analysis_payload(messages, mode, user_id=user_id)
                analysis_json_path.write_text(payload, encoding="utf-8")
                analysis_ready = True

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
                analysis_ready = False

            if txt_path.exists() and txt_path.stat().st_size > 0:
                await _send_outputs(
                    update,
                    txt_path=txt_path,
                    source_file_name=file_name,
                    analysis_json_path=analysis_json_path if analysis_ready else None,
                    mode=mode,
                )

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
    """Регистрирует handlers для /parse, /run, /interval и обработки документов."""
    application.bot_data.setdefault("no_auth", no_auth)
    application.bot_data.setdefault("allowed_users", allowed_users)
    application.add_handler(CommandHandler("parse", parse_command))
    application.add_handler(CommandHandler("run", run_command))
    application.add_handler(CommandHandler("interval", interval_command))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
