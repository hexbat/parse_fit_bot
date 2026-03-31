import argparse
import json
import logging
from pathlib import Path

from fit_common import decode_fit_to_messages

logger = logging.getLogger(__name__)


def convert_fit_to_txt(fit_file_path: str, txt_file_path: str) -> None:
    """
    Конвертирует Garmin FIT файл в текстовый формат.

    Args:
        fit_file_path (str): Путь к исходному .fit файлу.
        txt_file_path (str): Путь для сохранения результирующего .txt файла.
    """
    logger.info("Чтение файла: %s", fit_file_path)

    messages = decode_fit_to_messages(fit_file_path)
    output = json.dumps(messages.raw, indent=4, default=str, ensure_ascii=False)
    Path(txt_file_path).write_text(output, encoding="utf-8")
    logger.info("Успешно сконвертировано. Результат сохранен в: %s", txt_file_path)


def _resolve_output_path(input_fit: str, output: str | None) -> str:
    if output:
        return output
    if input_fit.lower().endswith(".fit"):
        return input_fit[:-4] + ".txt"
    return input_fit + ".txt"


def main() -> None:
    # Настройка парсера аргументов командной строки
    parser = argparse.ArgumentParser(description='Конвертация Garmin FIT файла в текстовый формат.')
    parser.add_argument('input_fit', help='Путь к входному .fit файлу')
    parser.add_argument('-o', '--output', help='Путь к выходному .txt файлу (по умолчанию: имя_входного_файла.txt)')

    args = parser.parse_args()

    # Определяем имя выходного файла
    output_file = _resolve_output_path(args.input_fit, args.output)

    # Запускаем конвертацию
    convert_fit_to_txt(args.input_fit, output_file)

if __name__ == "__main__":
    main()
