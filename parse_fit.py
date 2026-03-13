import argparse
import json
import logging

from garmin_fit_sdk import Decoder, Stream

logger = logging.getLogger(__name__)

def convert_fit_to_txt(fit_file_path, txt_file_path):
    """
    Конвертирует Garmin FIT файл в текстовый формат.

    Args:
        fit_file_path (str): Путь к исходному .fit файлу.
        txt_file_path (str): Путь для сохранения результирующего .txt файла.
    """
    logger.info("Чтение файла: %s", fit_file_path)

    try:
        # Создаем поток данных из файла
        stream = Stream.from_file(fit_file_path)
        decoder = Decoder(stream)

        # Проверяем, является ли файл корректным FIT файлом
        if not decoder.is_fit():
            logger.error("Файл не является валидным FIT файлом (отсутствует заголовок .FIT).")
            return

        # Декодируем файл с опциями для человеко-читаемого вывода
        # Все опции включены по умолчанию, но мы указываем их явно для наглядности [citation:1]
        messages, errors = decoder.read(
            apply_scale_and_offset=True,        # Применяем масштабы и смещения (например, для высоты)
            convert_datetimes_to_dates=True,    # Преобразуем время FIT в объекты datetime
            convert_types_to_strings=True,      # Преобразуем числовые типы в строки (например, спорт)
            expand_sub_fields=True,              # Раскрываем подполя
            expand_components=True,               # Раскрываем компоненты полей
            merge_heart_rates=True                # Объединяем данные ЧСС с записями
        )

        # Обрабатываем возможные ошибки декодирования
        if errors:
            logger.warning("При декодировании возникли ошибки: %s", errors)

        if not messages:
            logger.warning("В файле не найдено сообщений.")
            return

        # Сохраняем результат в текстовый файл
        with open(txt_file_path, 'w', encoding='utf-8') as txt_file:
            # Используем json.dumps для красивого форматирования, так как messages - это словарь
            # Альтернативно можно написать кастомный парсер для более специфичного вывода
            txt_file.write(json.dumps(messages, indent=4, default=str, ensure_ascii=False))

        logger.info("Успешно сконвертировано. Результат сохранен в: %s", txt_file_path)

    except FileNotFoundError:
        logger.error("Файл '%s' не найден.", fit_file_path)
    except Exception as e:  # noqa: BLE001
        logger.exception("Произошла непредвиденная ошибка при конвертации '%s': %s", fit_file_path, e)

def main():
    # Настройка парсера аргументов командной строки
    parser = argparse.ArgumentParser(description='Конвертация Garmin FIT файла в текстовый формат.')
    parser.add_argument('input_fit', help='Путь к входному .fit файлу')
    parser.add_argument('-o', '--output', help='Путь к выходному .txt файлу (по умолчанию: имя_входного_файла.txt)')

    args = parser.parse_args()

    # Определяем имя выходного файла
    if args.output:
        output_file = args.output
    else:
        # Если выходной файл не указан, заменяем расширение .fit на .txt
        if args.input_fit.lower().endswith('.fit'):
            output_file = args.input_fit[:-4] + '.txt'
        else:
            output_file = args.input_fit + '.txt'

    # Запускаем конвертацию
    convert_fit_to_txt(args.input_fit, output_file)

if __name__ == "__main__":
    main()
