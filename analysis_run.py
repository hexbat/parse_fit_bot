from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from analysis_models import Cadence, RunMetrics, SplitKm, Zones, ZoneValues
from fit_common import FitMessages, extract_common_metrics
from zones_store import get_user_zones


def _get_record_timestamp(rec: dict) -> Optional[datetime]:
    ts = rec.get("timestamp")
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
    return None


def _get_record_speed(rec: dict) -> float:
    """Возвращает скорость в м/с для записи."""
    speed = rec.get("enhanced_speed")
    if speed is None:
        speed = rec.get("speed")
    try:
        return float(speed or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _get_record_hr(rec: dict) -> Optional[int]:
    hr = rec.get("heart_rate")
    try:
        return int(hr) if hr is not None else None
    except (TypeError, ValueError):
        return None


def _get_record_cadence(rec: dict) -> Optional[int]:
    cad = rec.get("cadence")
    try:
        return int(cad) if cad is not None else None
    except (TypeError, ValueError):
        return None


def _compute_hr_zones(
    max_hr: Optional[int], custom_zones: Optional[List[Tuple[int, int]]] = None
) -> List[Tuple[int, int]]:
    """
    Возвращает список границ пульсовых зон [(low, high), ...] по max_hr.
    Простой вариант: 5 зон как доли от max_hr.
    """
    if custom_zones:
        return custom_zones

    if not max_hr or max_hr <= 0:
        # Фолбек: фиксированные границы
        return [(0, 100), (101, 120), (121, 140), (141, 160), (161, 1000)]

    z1 = int(max_hr * 0.60)
    z2 = int(max_hr * 0.70)
    z3 = int(max_hr * 0.80)
    z4 = int(max_hr * 0.90)
    return [(0, z1), (z1 + 1, z2), (z2 + 1, z3), (z3 + 1, z4), (z4 + 1, 1000)]


def _zone_index(hr: int, zones: List[Tuple[int, int]]) -> Optional[int]:
    for idx, (lo, hi) in enumerate(zones):
        if lo <= hr <= hi:
            return idx
    return None


def build_run_metrics(messages: FitMessages, user_id: Optional[int] = None) -> RunMetrics:
    """
    Строит RunMetrics на основе FitMessages:
    - базовые поля берутся из CommonMetrics (extract_common_metrics);
    - рассчитываются splits_km и zones по record_mesgs.
    """
    common = extract_common_metrics(messages)
    base_data = common.model_dump()

    # Дистанция по сессии (в км), если есть
    distance_km: Optional[float] = None
    total_timer_time: Optional[float] = None
    if messages.sessions:
        total_distance = messages.sessions[0].get("total_distance")
        try:
            if total_distance is not None:
                distance_km = float(total_distance) / 1000.0
        except (TypeError, ValueError):
            distance_km = None
        ttt = messages.sessions[0].get("total_timer_time")
        try:
            if ttt is not None:
                total_timer_time = float(ttt)
        except (TypeError, ValueError):
            total_timer_time = None

    records = [r for r in messages.records if _get_record_timestamp(r) is not None]
    records.sort(key=_get_record_timestamp)

    splits: List[SplitKm] = []
    zones_model: Optional[Zones] = None
    cadence_model: Optional[Cadence] = None

    if records:
        # Для зон — берём max_hr из CommonMetrics, если есть,
        # и переопределяем границы, если для пользователя заданы индивидуальные зоны.
        max_hr = common.heart_rate.max if common.heart_rate else None
        custom = get_user_zones(user_id) if user_id is not None else None
        zone_bounds = _compute_hr_zones(max_hr, custom_zones=custom)
        zone_times = [0.0] * 5  # секунды в каждой зоне

        cad_min: Optional[int] = None
        cad_max: Optional[int] = None
        cad_sum = 0
        cad_count = 0

        current_km = 1
        acc_distance_m = 0.0
        split_start_time = _get_record_timestamp(records[0])
        split_hr_sum = 0.0
        split_hr_count = 0
        split_hr_max = None

        prev_ts = split_start_time

        # Для тредмила используем среднюю скорость (дистанция / время),
        # чтобы сплиты по км были ровнее при постоянном темпе.
        use_avg_speed = (
            common.sub_sport == "treadmill"
            and distance_km is not None
            and total_timer_time is not None
            and total_timer_time > 0
        )
        avg_speed_mps = (
            distance_km * 1000.0 / total_timer_time if use_avg_speed else None
        )

        for rec in records[1:]:
            ts = _get_record_timestamp(rec)
            if ts is None or prev_ts is None:
                prev_ts = ts
                continue

            dt = (ts - prev_ts).total_seconds()
            if dt <= 0:
                prev_ts = ts
                continue

            speed = avg_speed_mps if avg_speed_mps is not None else _get_record_speed(rec)
            hr = _get_record_hr(rec)

            # Обновляем дистанцию
            acc_distance_m += speed * dt

            # Обновляем зоны и каденс
            if hr is not None:
                idx = _zone_index(hr, zone_bounds)
                if idx is not None:
                    zone_times[idx] += dt

                split_hr_sum += hr
                split_hr_count += 1
                if split_hr_max is None or hr > split_hr_max:
                    split_hr_max = hr

            cad = _get_record_cadence(rec)
            if cad is not None:
                cad_sum += cad
                cad_count += 1
                if cad_min is None or cad < cad_min:
                    cad_min = cad
                if cad_max is None or cad > cad_max:
                    cad_max = cad

            # Проверяем, не перешли ли очередной километр
            while acc_distance_m >= current_km * 1000:
                if split_start_time is not None:
                    elapsed_min_raw = (ts - split_start_time).total_seconds() / 60.0
                    elapsed_min = round(elapsed_min_raw, 2)
                else:
                    elapsed_min = 0.0

                avg_hr = int(split_hr_sum / split_hr_count) if split_hr_count > 0 else None
                pace = elapsed_min  # минуты на километр
                speed = round(60.0 / elapsed_min, 2) if elapsed_min > 0 else None

                split = SplitKm(
                    km=current_km,
                    time_min=elapsed_min,
                    avg_hr=avg_hr,
                    max_hr=split_hr_max,
                    pace=pace,
                    speed=speed,
                )
                splits.append(split)

                current_km += 1
                split_start_time = ts
                split_hr_sum = 0.0
                split_hr_count = 0
                split_hr_max = None

            prev_ts = ts

        # Добавляем последний неполный километровый отрезок, если он есть
        if split_start_time is not None and prev_ts is not None:
            # Теоретически пройденная дистанция
            if distance_km is not None:
                total_km = distance_km
            else:
                total_km = acc_distance_m / 1000.0

            last_full_km = current_km - 1
            remaining_km = max(0.0, total_km - last_full_km)

            if remaining_km > 0:
                elapsed_min_raw = (prev_ts - split_start_time).total_seconds() / 60.0
                elapsed_min = round(elapsed_min_raw, 2)

                avg_hr = int(split_hr_sum / split_hr_count) if split_hr_count > 0 else None
                if remaining_km > 0 and elapsed_min > 0:
                    pace = round(elapsed_min / remaining_km, 2)
                    speed = round(60.0 * remaining_km / elapsed_min, 2)
                else:
                    pace = None
                    speed = None

                split = SplitKm(
                    km=current_km,
                    time_min=elapsed_min,
                    avg_hr=avg_hr,
                    max_hr=split_hr_max,
                    pace=pace,
                    speed=speed,
                )
                splits.append(split)

        # Заполняем зоны в минутах и процентах (округление до сотых)
        zone_min = [round(sec / 60.0, 2) for sec in zone_times]
        total_min = sum(zone_min) or (common.duration_min or 0)
        if total_min <= 0:
            zone_pct = [0.0] * 5
        else:
            zone_pct = [round(v / total_min * 100.0, 2) for v in zone_min]

        zones_model = Zones(
            min=ZoneValues(
                zone1=zone_min[0],
                zone2=zone_min[1],
                zone3=zone_min[2],
                zone4=zone_min[3],
                zone5=zone_min[4],
            ),
            percent=ZoneValues(
                zone1=zone_pct[0],
                zone2=zone_pct[1],
                zone3=zone_pct[2],
                zone4=zone_pct[3],
                zone5=zone_pct[4],
            ),
        )

        if cad_count > 0 and cad_min is not None and cad_max is not None:
            cadence_model = Cadence(
                min=cad_min,
                avg=int(cad_sum / cad_count),
                max=cad_max,
            )

    run_metrics = RunMetrics(
        **base_data,
        distance_km=distance_km,
        splits_km=splits or None,
        laps=None,  # при необходимости можно добавить позже
        zones=zones_model,
        cadence=cadence_model,
    )

    return run_metrics

