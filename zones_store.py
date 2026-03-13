from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ZONES_PATH = Path(__file__).parent / "zones.json"
ZONES_EXAMPLE_PATH = Path(__file__).parent / "zones.json.example"


def _load_all() -> Dict[str, dict]:
    if not ZONES_PATH.exists():
        # Если файла ещё нет, просто возвращаем пустой словарь.
        return {}
    try:
        with ZONES_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        # При ошибке чтения не ломаем работу бота.
        return {}
    return {}


def _save_all(data: Dict[str, dict]) -> None:
    with ZONES_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_zones(user_id: int) -> Optional[List[Tuple[int, int]]]:
    """
    Возвращает список зон [(min, max), ...] для пользователя или None,
    если индивидуальные зоны не заданы.
    """
    data = _load_all()
    entry = data.get(str(user_id))
    if not entry:
        return None
    zones_raw = entry.get("zones")
    if not isinstance(zones_raw, list):
        return None

    result: List[Tuple[int, int]] = []
    for item in zones_raw:
        try:
            zmin = int(item["min"])
            zmax = int(item["max"])
            result.append((zmin, zmax))
        except Exception:
            return None

    return result or None


def set_user_zones(user_id: int, zones: List[Tuple[int, int]]) -> None:
    """
    Сохраняет пульсовые зоны пользователя.
    zones: список из 5 кортежей (min, max).
    """
    data = _load_all()
    data[str(user_id)] = {
        "zones": [{"min": zmin, "max": zmax} for zmin, zmax in zones],
    }
    _save_all(data)

