from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class HeartRate(BaseModel):
    """Показатели ЧСС за тренировку."""

    min: int
    avg: int
    max: int


class TrainingEffect(BaseModel):
    """Тренировочный эффект, если доступен в FIT."""

    aerobic: Optional[float] = None
    anaerobic: Optional[float] = None


class CommonMetrics(BaseModel):
    """
    Общие поля для всех типов тренировок (см. common.json).
    """

    date: date
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    type: str = Field(..., description="Тип тренировки: running / strength / rest и т.п.")
    sub_sport: Optional[str] = Field(
        None,
        description="Подтип активности: treadmill, outdoor, strength_training и т.п.",
    )
    duration_min: int
    calories: Optional[int] = None
    heart_rate: Optional[HeartRate] = None
    training_effect: Optional[TrainingEffect] = None
    avg_step_length_mm: Optional[float] = None
    training_load_peak: Optional[float] = None
    totals: Optional[Dict[str, float]] = None


class ZoneValues(BaseModel):
    """Набор значений по зонам (минуты или проценты)."""

    zone1: float = 0.0
    zone2: float = 0.0
    zone3: float = 0.0
    zone4: float = 0.0
    zone5: float = 0.0


class Zones(BaseModel):
    """Время в пульсовых зонах в минутах и процентах от общей длительности."""

    min: ZoneValues
    percent: ZoneValues


class SplitKm(BaseModel):
    """Сводка по одному километру для бега."""

    km: int
    time_min: float
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    pace: Optional[float] = None  # минуты на километр
    speed: Optional[float] = None  # км/ч


class Lap(BaseModel):
    """Информация по кругу/лапу."""

    lap_number: int
    distance_km: Optional[float] = None
    time_min: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None


class RunMetrics(CommonMetrics):
    """
    Модель анализа для обычной беговой тренировки (см. run.json).
    """

    type: Literal["running"] = "running"

    distance_km: Optional[float] = None
    splits_km: Optional[List[SplitKm]] = None
    laps: Optional[List[Lap]] = None
    zones: Optional[Zones] = None
    cadence: Optional["Cadence"] = None
    notes: Optional[str] = None


class Cadence(BaseModel):
    """Показатели каденса за тренировку."""

    min: int
    avg: int
    max: int


class IntervalSegment(BaseModel):
    """
    Отдельный сегмент интервальной тренировки (work / rest).
    См. interval.json.
    """

    set: Optional[int] = None
    type: Literal["work", "rest"]

    # Для work
    distance_km: Optional[float] = None
    time_min: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    pace_kmh: Optional[float] = None
    recovery_hr_start: Optional[int] = None
    recovery_hr_end: Optional[int] = None

    # Для rest
    duration_min: Optional[float] = None


class IntervalMetrics(CommonMetrics):
    """
    Модель анализа для интервальной беговой тренировки.
    Близка к примеру interval.json.
    """

    type: Literal["running"] = "running"
    workout_type: Literal["intervals"] = "intervals"

    distance_km: Optional[float] = None
    zones: Optional[Zones] = None
    intervals: List[IntervalSegment]

    # Суммарные показатели (могут быть заполнены/нет)
    total_work_min: Optional[float] = None
    total_rest_min: Optional[float] = None
    work_avg_hr: Optional[float] = None
    rest_avg_hr: Optional[float] = None

    notes: Optional[str] = None


class StrengthSet(BaseModel):
    """Отдельный подход в упражнении."""

    reps: int
    weight_kg: float


class StrengthExercise(BaseModel):
    """Описание одного упражнения (см. strenght.json и UI-пример)."""

    name: str
    machine: Optional[str] = None
    sets: List[StrengthSet]

    # Дополнительные поля, если удастся извлечь
    rest_sec: Optional[int] = None
    avg_hr_set: Optional[float] = None


class StrengthMetrics(CommonMetrics):
    """
    Модель анализа для силовой тренировки.
    См. strenght.json.
    """

    type: Literal["strength"] = "strength"
    exercises: List[StrengthExercise]
    notes: Optional[str] = None


__all__ = [
    "HeartRate",
    "TrainingEffect",
    "CommonMetrics",
    "Zones",
    "ZoneValues",
    "SplitKm",
    "Lap",
    "RunMetrics",
    "Cadence",
    "IntervalSegment",
    "IntervalMetrics",
    "StrengthSet",
    "StrengthExercise",
    "StrengthMetrics",
]

