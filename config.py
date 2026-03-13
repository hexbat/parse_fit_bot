"""Загрузка конфигурации."""
import json
import shutil
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
CONFIG_EXAMPLE_PATH = Path(__file__).parent / "config.json.example"


def load_config() -> dict:
    """
    Загружает config.json. Если файла нет — копирует из config.json.example.
    """
    if not CONFIG_PATH.exists():
        if CONFIG_EXAMPLE_PATH.exists():
            shutil.copy(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
        else:
            raise FileNotFoundError(
                f"config.json не найден. Создайте его: cp config.json.example config.json"
            )

    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    """Сохраняет конфигурацию в config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
