#!/usr/bin/env python3
"""
Локально повторяет выход команды /run в боте для заданного .fit:

  <stem>.txt      — полный дамп сообщений FIT (JSON внутри, как после convert_fit_to_txt)
  <stem>_run.json — анализ беговой тренировки (те же поля, что отправляет бот)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from analysis_run import build_run_metrics
from fit_common import decode_fit_to_messages
from parse_fit import convert_fit_to_txt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Конвертировать .fit в .txt и *_run.json, как при /run в боте."
    )
    parser.add_argument(
        "fit_file",
        type=Path,
        help="Путь к входному .fit",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Каталог для .txt и _run.json (по умолчанию — каталог входного файла)",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Telegram user id для персональных порогов зон (как в боте); можно не указывать",
    )
    args = parser.parse_args()

    fit_path = args.fit_file.expanduser().resolve()
    if not fit_path.is_file():
        print(f"Файл не найден: {fit_path}", file=sys.stderr)
        return 1
    if fit_path.suffix.lower() != ".fit":
        print("Ожидается расширение .fit", file=sys.stderr)
        return 1

    out_dir = (args.output_dir.expanduser().resolve() if args.output_dir else fit_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = fit_path.stem
    txt_path = out_dir / f"{stem}.txt"
    run_json_path = out_dir / f"{stem}_run.json"

    convert_fit_to_txt(str(fit_path), str(txt_path))
    if not txt_path.exists() or txt_path.stat().st_size == 0:
        print("Конвертация в .txt не создала файл (проверьте, что это валидный FIT).", file=sys.stderr)
        return 1

    messages = decode_fit_to_messages(str(fit_path))
    run_metrics = build_run_metrics(messages, user_id=args.user_id)
    payload = run_metrics.model_dump(mode="json")
    run_json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"TXT:       {txt_path}")
    print(f"Run JSON:  {run_json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
