from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from garmin_fit_sdk import Decoder, Stream

from analysis_models import CommonMetrics, HeartRate, TrainingEffect


@dataclass
class FitMessages:
    """
    Обёртка над словарём messages из garmin_fit_sdk.

    Ожидается структура, аналогичная JSON, который записывает parse_fit.py:
    {
        "session_mesgs": [...],
        "record_mesgs": [...],
        ...
    }
    """

    raw: Dict[str, Any]

    @property
    def sessions(self) -> list[dict]:
        return list(self.raw.get("session_mesgs") or [])

    @property
    def records(self) -> list[dict]:
        return list(self.raw.get("record_mesgs") or [])


def load_messages_from_txt(path: str | Path) -> FitMessages:
    """
    Загружает JSON (txt), сформированный parse_fit.convert_fit_to_txt.
    Полезно для отладки и работы с примерами.
    """
    p = Path(path)
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    return FitMessages(raw=data)


def decode_fit_to_messages(path: str | Path) -> FitMessages:
    """
    Декодирует .fit-файл в структуру messages с помощью garmin_fit_sdk.
    Использует те же опции, что и convert_fit_to_txt (человеко-читаемые значения).
    """
    p = Path(path)
    stream = Stream.from_file(str(p))
    decoder = Decoder(stream)

    if not decoder.is_fit():
        raise ValueError("File is not a valid FIT file")

    messages, errors = decoder.read(
        apply_scale_and_offset=True,
        convert_datetimes_to_dates=True,
        convert_types_to_strings=True,
        expand_sub_fields=True,
        expand_components=True,
        merge_heart_rates=True,
    )

    # Ошибки декодирования не фатальны для общей статистики, но их можно залогировать
    # на уровне вызывающего кода, если нужно.

    return FitMessages(raw=messages)


def _parse_session_date(session: dict) -> date:
    """Определяет дату тренировки по полям start_time / timestamp.

    В messages от garmin_fit_sdk значения могут приходить как строкой,
    так и объектами datetime/date — обрабатываем оба варианта.
    """
    ts = session.get("start_time") or session.get("timestamp")
    if isinstance(ts, datetime):
        return ts.date()
    if isinstance(ts, date):
        return ts
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
            return dt.date()
        except ValueError:
            pass
    # Фолбек: сегодняшняя дата, если парсинг не удался.
    return date.today()


def _normalize_dt(value: object) -> Optional[datetime]:
    """Преобразует значение из session_mesgs в datetime, если возможно."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        # интерпретируем как полночь UTC этого дня
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _map_activity_type(session: dict) -> str:
    """
    Приводит тип тренировки к более удобному виду:
    - strength для силовых
    - иначе ровно sport (running, etc) или 'unknown'.
    """
    sport = session.get("sport")
    sub_sport = session.get("sub_sport")

    if sub_sport == "strength_training" or sport == "strength_training":
        return "strength"
    if sport:
        return str(sport)
    return "unknown"


def extract_common_metrics(messages: FitMessages) -> CommonMetrics:
    """
    Строит CommonMetrics по данным session_mesgs.

    Используются поля:
    - start_time / timestamp -> date
    - sport / sub_sport -> type / sub_sport
    - total_timer_time -> duration_min
    - total_calories -> calories
    - min/avg/max_heart_rate -> heart_rate
    - total_training_effect / total_anaerobic_training_effect -> training_effect
    """
    if not messages.sessions:
        raise ValueError("FIT data does not contain session_mesgs")

    session = messages.sessions[0]

    workout_date = _parse_session_date(session)
    activity_type = _map_activity_type(session)
    sub_sport = session.get("sub_sport")

    duration_sec_raw = session.get("total_timer_time") or 0.0
    try:
        duration_sec = float(duration_sec_raw)
    except (TypeError, ValueError):
        duration_sec = 0.0
    duration_min = int(round(duration_sec / 60.0)) if duration_sec else 0

    calories_raw = session.get("total_calories")
    try:
        calories = int(calories_raw) if calories_raw is not None else None
    except (TypeError, ValueError):
        calories = None

    hr: Optional[HeartRate] = None
    if any(k in session for k in ("min_heart_rate", "avg_heart_rate", "max_heart_rate")):
        try:
            hr = HeartRate(
                min=int(session.get("min_heart_rate") or 0),
                avg=int(session.get("avg_heart_rate") or 0),
                max=int(session.get("max_heart_rate") or 0),
            )
        except (TypeError, ValueError):
            hr = None

    te: Optional[TrainingEffect] = None
    if "total_training_effect" in session or "total_anaerobic_training_effect" in session:
        te = TrainingEffect(
            aerobic=float(session.get("total_training_effect")) if session.get("total_training_effect") is not None else None,
            anaerobic=float(session.get("total_anaerobic_training_effect"))
            if session.get("total_anaerobic_training_effect") is not None
            else None,
        )

    # Прочие агрегаты из session_mesgs
    step_len_raw = session.get("avg_step_length")
    try:
        avg_step_length_mm = float(step_len_raw) if step_len_raw is not None else None
    except (TypeError, ValueError):
        avg_step_length_mm = None

    tlp_raw = session.get("training_load_peak")
    try:
        training_load_peak = float(tlp_raw) if tlp_raw is not None else None
    except (TypeError, ValueError):
        training_load_peak = None

    totals: Dict[str, float] = {}
    for key, value in session.items():
        if key.startswith("total_") and value is not None:
            try:
                totals[key] = float(value)
            except (TypeError, ValueError):
                continue
    if not totals:
        totals = None

    return CommonMetrics(
        date=workout_date,
        start_time=_normalize_dt(session.get("start_time")),
        end_time=_normalize_dt(session.get("timestamp")),
        type=activity_type,
        sub_sport=sub_sport,
        duration_min=duration_min,
        calories=calories,
        heart_rate=hr,
        training_effect=te,
        avg_step_length_mm=avg_step_length_mm,
        training_load_peak=training_load_peak,
        totals=totals,
    )

