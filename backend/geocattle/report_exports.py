import csv
from datetime import date, datetime
from decimal import Decimal
from io import TextIOWrapper
from math import isfinite
from tempfile import TemporaryFile
from typing import Literal

from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from xlsxwriter import Workbook


ExportFormat = Literal['csv', 'xlsx']
CsvDelimiter = Literal['comma', 'semicolon']
EXPORT_LIMIT = 50_000
XLSX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def display_value(value, zone):
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.astimezone(zone).isoformat(timespec='seconds')
    if isinstance(value, bool):
        return 'Sí' if value else 'No'
    return str(value)


def csv_cell(value, zone, delimiter, legacy_telemetry):
    if isinstance(value, str) and (value.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@'))):
        return "'" + value
    if delimiter == 'semicolon' and isinstance(value, (float, Decimal)):
        return str(value).replace('.', ',')
    if legacy_telemetry:
        if isinstance(value, datetime):
            return (value if delimiter == 'comma' else value.astimezone(zone)).isoformat()
        if delimiter == 'comma' and isinstance(value, bool):
            return str(value)
    return display_value(value, zone)


def write_csv(output, columns, rows, zone, delimiter, legacy_telemetry):
    text_output = TextIOWrapper(output, encoding='utf-8', newline='')
    try:
        text_output.write('\ufeff')
        writer = csv.writer(text_output, delimiter=';' if delimiter == 'semicolon' else ',')
        writer.writerow(columns)
        writer.writerows([csv_cell(value, zone, delimiter, legacy_telemetry) for value in row] for row in rows)
    finally:
        text_output.detach()


def write_xlsx(output, columns, rows, zone, title, metadata, formats=None, sheets=()):
    with Workbook(output, {'constant_memory': True}) as workbook:
        header = workbook.add_format({'bold': True, 'bg_color': '#E3EFE4', 'font_color': '#234C37'})
        date_format = workbook.add_format({'num_format': 'yyyy-mm-dd'})
        datetime_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss'})
        number_formats = {index: workbook.add_format({'num_format': pattern}) for index, pattern in (formats or {}).items()}

        def write_cell(sheet, row_index, column_index, value, cell_formats):
            if value is None:
                return 0
            if isinstance(value, datetime):
                local = value.astimezone(zone).replace(tzinfo=None)
                sheet.write_datetime(row_index, column_index, local, datetime_format)
                return 19
            if isinstance(value, date):
                sheet.write_datetime(row_index, column_index, value, date_format)
                return 10
            if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and isfinite(value):
                sheet.write_number(row_index, column_index, value, cell_formats.get(column_index))
                return min(20, len(str(value)))
            label = display_value(value, zone)
            sheet.write_string(row_index, column_index, label)
            return max(map(len, label.split('\n')))

        def table(sheet, columns, rows, cell_formats):
            widths = [len(column) for column in columns]
            for column_index, column in enumerate(columns):
                sheet.write_string(0, column_index, column, header)
            last_row = 0
            for last_row, row in enumerate(rows, 1):
                for column_index, value in enumerate(row):
                    width = write_cell(sheet, last_row, column_index, value, cell_formats)
                    widths[column_index] = max(widths[column_index], width)
            for column_index, width in enumerate(widths):
                sheet.set_column(column_index, column_index, min(64, max(12, width + 4)))
            sheet.freeze_panes(1, 0)
            sheet.autofilter(0, 0, last_row, len(columns) - 1)

        table(workbook.add_worksheet(title), columns, rows, number_formats)
        for sheet_title, sheet_columns, sheet_rows in sheets:
            table(workbook.add_worksheet(sheet_title), sheet_columns, sheet_rows, {})
        table(workbook.add_worksheet('Metadatos'), ('Campo', 'Valor'), metadata, {})


def export_response(columns, rows, *, format: ExportFormat, filename, title, zone, metadata,
                    delimiter: CsvDelimiter = 'comma', legacy_telemetry=False, headers=None, formats=None, sheets=()):
    output = TemporaryFile()
    try:
        if format == 'xlsx':
            write_xlsx(output, columns, rows, zone, title, metadata, formats, sheets)
            media_type = XLSX_MEDIA_TYPE
        else:
            write_csv(output, columns, rows, zone, delimiter, legacy_telemetry)
            media_type = 'text/csv'
        size = output.tell()
        output.seek(0)
    except BaseException:
        output.close()
        raise

    def chunks():
        with output:
            yield from iter(lambda: output.read(64 * 1024), b'')

    return StreamingResponse(chunks(), media_type=media_type, background=BackgroundTask(output.close),
                             headers={**(headers or {}), 'Content-Length': str(size),
                                      'Content-Disposition': f'attachment; filename="{filename}.{format}"'})
