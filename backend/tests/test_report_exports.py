import csv
from decimal import Decimal
from io import BytesIO, StringIO
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from geocattle.report_exports import write_csv, write_xlsx


def test_exports_preserve_literal_text_and_distinguish_it_from_numeric_values():
    zone = ZoneInfo('America/Santiago')
    labels = ['=texto', '+texto', '-texto', '@texto', '  =texto', '\ttexto', '00123', 'Línea; "1"\nLínea 2']
    rows = [(label, Decimal('-1.25')) for label in labels]
    columns = ('Texto', 'Medida')
    xlsx = BytesIO()
    write_xlsx(xlsx, columns, rows, zone, 'Datos', [('Nombre del predio', '=Predio QA')])
    book = load_workbook(xlsx)
    assert book['Metadatos']['B2'].data_type == 's'
    assert book['Metadatos']['B2'].value == '=Predio QA'
    for (text_cell, numeric_cell), label in zip(list(book['Datos'].rows)[1:], labels, strict=True):
        assert text_cell.data_type == 's' and text_cell.value == label
        assert numeric_cell.data_type == 'n' and numeric_cell.value == -1.25
    for mode, separator, number in (('comma', ',', '-1.25'), ('semicolon', ';', '-1,25')):
        output = BytesIO()
        write_csv(output, columns, rows, zone, mode, False)
        payload = output.getvalue()
        assert payload.startswith(b'\xef\xbb\xbf')
        table = list(csv.reader(StringIO(payload.decode('utf-8-sig'), newline=''), delimiter=separator))
        assert table == [list(columns), *[["'" + label, number] for label in labels[:6]],
                         *[[label, number] for label in labels[6:]]]
