from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Literal, Optional, Tuple, TypedDict

from fit_common import FitMessages, extract_common_metrics


class IntervalEntry(TypedDict):
    start: str
    stop: str
    duration: str
    type: Literal["warm-up", "up", "down", "cool-down"]
    HRmin: int
    HRavg: int
    HRmax: int


@dataclass
class _HrPoint:
    t_sec: int
    hr: int


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


def _get_record_hr(rec: dict) -> Optional[int]:
    hr = rec.get("heart_rate")
    if hr is None:
        return None
    try:
        return int(hr)
    except (TypeError, ValueError):
        return None


def _build_hr_series(messages: FitMessages) -> List[_HrPoint]:
    records = [r for r in messages.records if _get_record_timestamp(r) is not None]
    records.sort(key=_get_record_timestamp)
    if not records:
        return []

    base_ts = _get_record_timestamp(records[0])
    assert base_ts is not None

    series: List[_HrPoint] = []
    for rec in records:
        ts = _get_record_timestamp(rec)
        hr = _get_record_hr(rec)
        if ts is None or hr is None:
            continue
        t_sec = int((ts - base_ts).total_seconds())
        if series and t_sec == series[-1].t_sec:
            # если несколько измерений в одну секунду — усредним по ходу
            prev = series[-1]
            new_hr = int(round((prev.hr + hr) / 2))
            series[-1] = _HrPoint(t_sec=t_sec, hr=new_hr)
        else:
            series.append(_HrPoint(t_sec=t_sec, hr=hr))

    return series


def _moving_average(values: List[float], window: int) -> List[float]:
    if not values or window <= 1:
        return values[:]
    half = window // 2
    n = len(values)
    result: List[float] = []
    for i in range(n):
        start = max(0, i - half)
        end = min(n, i + half + 1)
        segment = values[start:end]
        result.append(sum(segment) / len(segment))
    return result


def _detect_extrema(series: List[_HrPoint]) -> List[Tuple[int, str, float]]:
    """
    Реализует логику из interval_detection.md для поиска up/down-пиков.
    Возвращает список (t_sec, type, dHR_smooth).
    """
    if not series:
        return []

    # строим HR_20 и производные
    hr_vals = [float(p.hr) for p in series]
    t_vals = [p.t_sec for p in series]

    hr_20 = _moving_average(hr_vals, window=20)
    dhr_20 = [0.0]
    for i in range(1, len(hr_20)):
        dhr_20.append(hr_20[i] - hr_20[i - 1])
    dhr_20_40 = _moving_average(dhr_20, window=40)

    # отбрасываем первые 2 минуты
    filtered_times: List[int] = []
    filtered_dhr: List[float] = []
    for t, v in zip(t_vals, dhr_20_40):
        if t >= 120:
            filtered_times.append(t)
            filtered_dhr.append(v)

    def detect_peaks(times: List[int], values: List[float], is_max: bool, threshold: float) -> List[int]:
        """
        Плато‑поход: находим отрезки выше/ниже порога и берём одну точку с экстремумом.
        """
        n = len(values)
        peaks: List[int] = []
        start = 0
        while start < n:
            if is_max:
                cond = values[start] >= threshold
            else:
                cond = values[start] <= -threshold
            if not cond:
                start += 1
                continue

            end = start
            while end + 1 < n:
                if is_max:
                    if values[end + 1] < threshold:
                        break
                else:
                    if values[end + 1] > -threshold:
                        break
                end += 1

            segment = values[start : end + 1]
            if is_max:
                rel_idx = int(max(range(len(segment)), key=lambda i: segment[i]))
            else:
                rel_idx = int(min(range(len(segment)), key=lambda i: segment[i]))
            peak_idx = start + rel_idx
            peaks.append(peak_idx)
            start = end + 1

        return peaks

    up_idx = detect_peaks(filtered_times, filtered_dhr, is_max=True, threshold=0.25)
    down_idx = detect_peaks(filtered_times, filtered_dhr, is_max=False, threshold=0.40)

    raw_extrema: List[Tuple[int, str, float]] = []
    for i in up_idx:
        raw_extrema.append((filtered_times[i], "up", filtered_dhr[i]))
    for i in down_idx:
        raw_extrema.append((filtered_times[i], "down", filtered_dhr[i]))
    raw_extrema.sort(key=lambda x: x[0])

    # схлопываем подряд идущие однотипные
    extrema: List[Tuple[int, str, float]] = []
    for t_sec, kind, val in raw_extrema:
        if not extrema or extrema[-1][1] != kind:
            extrema.append((t_sec, kind, val))
        else:
            continue
    return extrema


def _sec_to_hhmmss(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _sec_to_mmss(sec: int) -> str:
    m = sec // 60
    s = sec % 60
    return f"{m:02d}:{s:02d}"


def _hr_stats_in_range(series: List[_HrPoint], start_sec: int, stop_sec: int) -> Tuple[int, int, int]:
    pts = [p.hr for p in series if start_sec <= p.t_sec < stop_sec]
    if not pts:
        return 0, 0, 0
    hr_min = min(pts)
    hr_max = max(pts)
    hr_avg = int(round(sum(pts) / len(pts)))
    return hr_min, hr_avg, hr_max


def build_interval_entries(messages: FitMessages) -> List[IntervalEntry]:
    """
    Строит список отрезков интервальной тренировки:
    warm-up / up / down / cool-down.
    """
    series = _build_hr_series(messages)
    if not series:
        return []

    extrema = _detect_extrema(series)
    if not extrema:
        return []

    start_time = series[0].t_sec
    end_time = series[-1].t_sec

    entries: List[IntervalEntry] = []

    # разминка: от 0 до первого up-пика
    first_up = next((t for t, kind, _ in extrema if kind == "up"), None)
    warmup_end = first_up if first_up is not None else series[0].t_sec
    if warmup_end > start_time:
        hr_min, hr_avg, hr_max = _hr_stats_in_range(series, start_time, warmup_end)
        entries.append(
            IntervalEntry(
                start=_sec_to_hhmmss(start_time),
                stop=_sec_to_hhmmss(warmup_end),
                duration=_sec_to_mmss(warmup_end - start_time),
                type="warm-up",
                HRmin=hr_min,
                HRavg=hr_avg,
                HRmax=hr_max,
            )
        )

    # интервальные отрезки up/down
    # предполагаем, что up/down чередуются
    for i, (t_sec, kind, _) in enumerate(extrema):
        if kind == "up":
            # up-сегмент до следующего down или до конца данных
            next_down_t = None
            for j in range(i + 1, len(extrema)):
                t2, kind2, _ = extrema[j]
                if kind2 == "down":
                    next_down_t = t2
                    break
            stop_t = next_down_t if next_down_t is not None else end_time
            if stop_t > t_sec:
                hr_min, hr_avg, hr_max = _hr_stats_in_range(series, t_sec, stop_t)
                entries.append(
                    IntervalEntry(
                        start=_sec_to_hhmmss(t_sec),
                        stop=_sec_to_hhmmss(stop_t),
                        duration=_sec_to_mmss(stop_t - t_sec),
                        type="up",
                        HRmin=hr_min,
                        HRavg=hr_avg,
                        HRmax=hr_max,
                    )
                )
        elif kind == "down":
            # down-сегмент до следующего up или до конца данных
            next_up_t = None
            for j in range(i + 1, len(extrema)):
                t2, kind2, _ = extrema[j]
                if kind2 == "up":
                    next_up_t = t2
                    break
            stop_t = next_up_t if next_up_t is not None else end_time
            if stop_t > t_sec:
                hr_min, hr_avg, hr_max = _hr_stats_in_range(series, t_sec, stop_t)
                entries.append(
                    IntervalEntry(
                        start=_sec_to_hhmmss(t_sec),
                        stop=_sec_to_hhmmss(stop_t),
                        duration=_sec_to_mmss(stop_t - t_sec),
                        type="down",
                        HRmin=hr_min,
                        HRavg=hr_avg,
                        HRmax=hr_max,
                    )
                )

    # заминка: от последнего down (или последнего экстремума) до конца тренировки
    last_down = None
    for t_sec, kind, _ in reversed(extrema):
        if kind == "down":
            last_down = t_sec
            break
    cooldown_start = last_down if last_down is not None else extrema[-1][0]
    if cooldown_start < end_time:
        hr_min, hr_avg, hr_max = _hr_stats_in_range(series, cooldown_start, end_time)
        entries.append(
            IntervalEntry(
                start=_sec_to_hhmmss(cooldown_start),
                stop=_sec_to_hhmmss(end_time),
                duration=_sec_to_mmss(end_time - cooldown_start),
                type="cool-down",
                HRmin=hr_min,
                HRavg=hr_avg,
                HRmax=hr_max,
            )
        )

    return entries


def build_interval_json(messages: FitMessages) -> dict:
    """
    Собирает JSON для /interval:
    - базовые поля как в common.json,
    - раздел intervals с отрезками warm-up / up / down / cool-down.
    """
    common = extract_common_metrics(messages)
    base = common.model_dump(mode="json")

    intervals = build_interval_entries(messages)
    base["workout_type"] = "intervals"
    base["intervals"] = intervals
    return base

