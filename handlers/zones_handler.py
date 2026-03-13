"""Команда /zones — настройка индивидуальных пульсовых зон."""
from __future__ import annotations

import logging
import re
from typing import List, Tuple

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from zones_store import set_user_zones

logger = logging.getLogger(__name__)

_WAITING_ZONES_FLAG = "waiting_zones_input"
_ZONE_LINE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


def _parse_zones_text(text: str) -> List[Tuple[int, int]]:
    """
    Парсит текст вида:
    Z1: 0-120
    Z2: 130-145
    ...
    Возвращает список [(min, max), ...].
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 5:
        raise ValueError("Нужно указать ровно 5 строк (для зон 1–5).")

    zones: List[Tuple[int, int]] = []

    for idx, line in enumerate(lines, start=1):
        m = _ZONE_LINE_RE.search(line)
        if not m:
            raise ValueError(f"Не удалось разобрать строку {idx}: '{line}' (ожидается формат вроде 'Z{idx}: 130-145').")
        zmin = int(m.group(1))
        zmax = int(m.group(2))
        if zmin < 0 or zmax <= zmin:
            raise ValueError(f"Неверный диапазон в строке {idx}: {zmin}-{zmax}.")
        zones.append((zmin, zmax))

    # Проверим, что зоны упорядочены и не пересекаются
    last_max = -1
    for idx, (zmin, zmax) in enumerate(zones, start=1):
        if zmin <= last_max:
            raise ValueError(f"Зоны пересекаются или не упорядочены (проблема в зоне {idx}).")
        last_max = zmax

    return zones


async def zones_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Старт настройки зон."""
    user = update.effective_user
    if not user or not update.message:
        return

    context.user_data[_WAITING_ZONES_FLAG] = True

    text = (
        "Давайте настроим ваши пульсовые зоны.\n\n"
        "Пришлите 5 строк в формате:\n"
        "Z1: 0-120\n"
        "Z2: 130-145\n"
        "Z3: 145-155\n"
        "Z4: 155-165\n"
        "Z5: 165-200\n\n"
        "Диапазоны должны быть возрастающими и не пересекаться."
    )
    await update.message.reply_text(text)


async def zones_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает текст с описанием зон, если мы в режиме ожидания."""
    if not context.user_data.get(_WAITING_ZONES_FLAG):
        return

    if not update.message or not update.effective_user:
        return

    text = update.message.text or ""

    try:
        zones = _parse_zones_text(text)
    except ValueError as e:
        await update.message.reply_text(f"Ошибка: {e}")
        return

    set_user_zones(update.effective_user.id, zones)
    context.user_data[_WAITING_ZONES_FLAG] = False

    zones_str = "\n".join(
        f"Z{i + 1}: {zmin}-{zmax} уд/мин" for i, (zmin, zmax) in enumerate(zones)
    )
    await update.message.reply_text(
        "Индивидуальные пульсовые зоны сохранены:\n" f"{zones_str}"
    )


def register_zones_handlers(application) -> None:
    """Регистрирует handlers для настройки зон."""
    application.add_handler(CommandHandler("zones", zones_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, zones_text_handler)
    )

