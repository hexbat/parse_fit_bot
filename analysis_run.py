from __future__ import annotations

import math
from typing import List, Optional, Tuple

from analysis_models import Cadence, RunMetrics, SplitKm, Zones, ZoneValues
from fit_common import FitMessages, extract_common_metrics
from fit_records import get_record_cadence, get_record_hr, get_record_timestamp
from zones_store import get_user_zones

# FIT: часто 65.535 м/с как «пустая» скорость uint16; выше ~25 м/с для бега не используем.
_MAX_SANE_RUN_SPEED_MPS = 25.0
_FIT_SPEED_SENTINEL_HI = 65.0

# GPS: отсекаем телепорты и нереальную мгновенную скорость между точками.
_MAX_GPS_INSTANT_MPS = 12.0
_MAX_GPS_SEGMENT_M = 280.0

# Доля интервалов с принятой GPS-дистанцией и расхождение с total_distance сессии.
_MIN_GPS_ACCEPTED_DT_FRAC = 0.25
_GPS_VS_SESSION_MAX_REL_ERR = 0.12


def _get_record_speed(rec: dict) -> float:
    """Возвращает скорость в м/с для записи."""
    speed = rec.get("enhanced_speed")
    if speed is None:
        speed = rec.get("speed")
    try:
        return float(speed or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _get_latlon_deg(rec: dict) -> Optional[Tuple[float, float]]:
    """Широта/долгота в градусах из semicircle (FIT) или уже градусы."""
    raw_lat = rec.get("position_lat")
    raw_lon = rec.get("position_long")
    if raw_lat is None or raw_lon is None:
        return None
    try:
        lat_f = float(raw_lat)
        lon_f = float(raw_lon)
    except (TypeError, ValueError):
        return None
    if abs(lat_f) <= 90.0 and abs(lon_f) <= 180.0:
        lat_d, lon_d = lat_f, lon_f
    else:
        lat_d = lat_f * (180.0 / (2**31))
        lon_d = lon_f * (180.0 / (2**31))
    if abs(lat_d) > 90.0 or abs(lon_d) > 180.0:
        return None
    return lat_d, lon_d


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r1, lonr1, r2, lonr2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = r2 - r1
    dlon = lonr2 - lonr1
    h = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(h)))
    return 6_371_000.0 * c


def _speed_mps_sane(rec: dict) -> float:
    """Скорость в м/с без FIT-артефактов (для не-street режима)."""
    v = _get_record_speed(rec)
    if v <= 0:
        return 0.0
    if v >= _FIT_SPEED_SENTINEL_HI or v > _MAX_SANE_RUN_SPEED_MPS:
        return 0.0
    return v


def _gps_raw_segment_list(records: List[dict]) -> Tuple[List[float], float, float]:
    """
    По парам соседних record: дистанция haversine или 0 (нет координат / выброс).
    Возвращает (список длин сегментов м, суммарная длина м, доля dt с принятым GPS).
    """
    segs: List[float] = []
    accepted_dt = 0.0
    total_dt = 0.0
    n = len(records)
    for i in range(n - 1):
        ts0 = get_record_timestamp(records[i])
        ts1 = get_record_timestamp(records[i + 1])
        if ts0 is None or ts1 is None:
            segs.append(0.0)
            continue
        dt = (ts1 - ts0).total_seconds()
        if dt <= 0:
            segs.append(0.0)
            continue
        total_dt += dt
        ll0 = _get_latlon_deg(records[i])
        ll1 = _get_latlon_deg(records[i + 1])
        d = 0.0
        if ll0 is not None and ll1 is not None:
            dm = _haversine_m(ll0[0], ll0[1], ll1[0], ll1[1])
            v_ins = dm / dt
            if dm <= _MAX_GPS_SEGMENT_M and v_ins <= _MAX_GPS_INSTANT_MPS:
                d = dm
                accepted_dt += dt
        segs.append(d)
    frac = (accepted_dt / total_dt) if total_dt > 0 else 0.0
    return segs, sum(segs), frac


def _prepare_segment_distances_m(
    records: List[dict],
    *,
    sub_sport: Optional[str],
    distance_m: Optional[float],
    total_timer_time: Optional[float],
) -> Tuple[List[float], Optional[str]]:
    """
    Длина каждого сегмента между records[i] и records[i+1] (метры).
    Для street: по GPS с фильтром; при расхождении с total_distance или редком GPS —
    равномерная средняя по сессии. Для treadmill — средняя по сессии.
    Иначе — интеграл по скорости record (без артефактов скорости).
    """
    n = len(records)
    if n < 2:
        return [], None

    use_treadmill_avg = (
        sub_sport == "treadmill"
        and distance_m is not None
        and total_timer_time is not None
        and total_timer_time > 0
    )
    avg_mps_treadmill = distance_m / total_timer_time if use_treadmill_avg else None

    is_street = sub_sport in ("street", "outdoor", "road")

    length = n - 1
    d_segs = [0.0] * length
    note: Optional[str] = None

    if use_treadmill_avg:
        assert avg_mps_treadmill is not None
        for i in range(length):
            ts0 = get_record_timestamp(records[i])
            ts1 = get_record_timestamp(records[i + 1])
            if ts0 is None or ts1 is None:
                continue
            dt = (ts1 - ts0).total_seconds()
            if dt > 0:
                d_segs[i] = avg_mps_treadmill * dt
        return d_segs, note

    if is_street:
        raw_list, sum_gps, accepted_frac = _gps_raw_segment_list(records)
        has_session = (
            distance_m is not None
            and distance_m > 0
            and total_timer_time is not None
            and total_timer_time > 0
        )
        if has_session:
            rel_err = abs(sum_gps - distance_m) / distance_m  # type: ignore[operator]
            use_avg_fallback = (
                sum_gps < 1.0
                or accepted_frac < _MIN_GPS_ACCEPTED_DT_FRAC
                or rel_err > _GPS_VS_SESSION_MAX_REL_ERR
            )
        else:
            use_avg_fallback = False

        if has_session and use_avg_fallback:
            avg_ref = distance_m / total_timer_time  # type: ignore[operator]
            for i in range(length):
                ts0 = get_record_timestamp(records[i])
                ts1 = get_record_timestamp(records[i + 1])
                if ts0 is None or ts1 is None:
                    continue
                dt = (ts1 - ts0).total_seconds()
                if dt > 0:
                    d_segs[i] = avg_ref * dt
            note = "splits_distance: avg_speed_fallback (sparse GPS or vs total_distance)"
        else:
            if has_session and sum_gps > 0:
                scale = distance_m / sum_gps  # type: ignore[operator]
                for i in range(length):
                    d_segs[i] = raw_list[i] * scale
            else:
                for i in range(length):
                    d_segs[i] = raw_list[i]
        return d_segs, note

    for i in range(length):
        ts0 = get_record_timestamp(records[i])
        ts1 = get_record_timestamp(records[i + 1])
        if ts0 is None or ts1 is None:
            continue
        dt = (ts1 - ts0).total_seconds()
        if dt > 0:
            d_segs[i] = _speed_mps_sane(records[i + 1]) * dt
    return d_segs, note


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

    records = [r for r in messages.records if get_record_timestamp(r) is not None]
    records.sort(key=get_record_timestamp)

    splits: List[SplitKm] = []
    zones_model: Optional[Zones] = None
    cadence_model: Optional[Cadence] = None
    split_note: Optional[str] = None

    if records:
        distance_m = distance_km * 1000.0 if distance_km is not None else None
        d_segs, split_note = _prepare_segment_distances_m(
            records,
            sub_sport=common.sub_sport,
            distance_m=distance_m,
            total_timer_time=total_timer_time,
        )

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
        split_start_time = get_record_timestamp(records[0])
        split_hr_sum = 0.0
        split_hr_count = 0
        split_hr_max = None

        prev_ts = split_start_time

        for i in range(len(records) - 1):
            rec = records[i + 1]
            ts = get_record_timestamp(rec)
            prev_t = get_record_timestamp(records[i])
            if ts is None or prev_t is None:
                continue

            dt = (ts - prev_t).total_seconds()
            if dt <= 0:
                continue

            d_m = d_segs[i] if i < len(d_segs) else 0.0
            acc_distance_m += d_m

            hr = get_record_hr(rec)

            if hr is not None:
                idx = _zone_index(hr, zone_bounds)
                if idx is not None:
                    zone_times[idx] += dt

                split_hr_sum += hr
                split_hr_count += 1
                if split_hr_max is None or hr > split_hr_max:
                    split_hr_max = hr

            cad = get_record_cadence(rec)
            if cad is not None:
                cad_sum += cad
                cad_count += 1
                if cad_min is None or cad < cad_min:
                    cad_min = cad
                if cad_max is None or cad > cad_max:
                    cad_max = cad

            while acc_distance_m >= current_km * 1000:
                if split_start_time is not None:
                    elapsed_min_raw = (ts - split_start_time).total_seconds() / 60.0
                    elapsed_min = round(elapsed_min_raw, 2)
                else:
                    elapsed_min = 0.0

                avg_hr = int(split_hr_sum / split_hr_count) if split_hr_count > 0 else None
                pace = elapsed_min  # минуты на километр
                split_speed = round(60.0 / elapsed_min, 2) if elapsed_min > 0 else None

                split = SplitKm(
                    km=current_km,
                    time_min=elapsed_min,
                    avg_hr=avg_hr,
                    max_hr=split_hr_max,
                    pace=pace,
                    speed=split_speed,
                )
                splits.append(split)

                current_km += 1
                split_start_time = ts
                split_hr_sum = 0.0
                split_hr_count = 0
                split_hr_max = None

            prev_ts = ts

        if split_start_time is not None and prev_ts is not None:
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
                    split_speed = round(60.0 * remaining_km / elapsed_min, 2)
                else:
                    pace = None
                    split_speed = None

                split = SplitKm(
                    km=current_km,
                    time_min=elapsed_min,
                    avg_hr=avg_hr,
                    max_hr=split_hr_max,
                    pace=pace,
                    speed=split_speed,
                )
                splits.append(split)

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
        laps=None,
        zones=zones_model,
        cadence=cadence_model,
        notes=split_note,
    )

    return run_metrics
