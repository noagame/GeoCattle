"""Cada tabla de las migraciones pertenece a una sola clase del modo espejo."""
import re
import unittest
from pathlib import Path

from geocattle import mirror_tables

ROOT = Path(__file__).resolve().parents[1]
CREATE = re.compile(r'CREATE TABLE (?:IF NOT EXISTS )?([a-z_][a-z0-9_]*)\s*\(', re.I)


def migration_tables():
    found = {'schema_migrations'}  # La crea migrate.py.
    for path in sorted((ROOT / 'database/migrations').glob('*.sql')):
        found.update(name.lower() for name in CREATE.findall(path.read_text(encoding='utf-8')))
    return found


class MirrorTablesTest(unittest.TestCase):
    def test_every_table_has_exactly_one_class(self):
        classes = (mirror_tables.MIRROR, mirror_tables.FIELD_ONLY, mirror_tables.SERVER_ONLY)
        tables = migration_tables()
        unclassified = tables.difference(*classes)
        self.assertFalse(unclassified, f'Clasifica en mirror_tables.py: {sorted(unclassified)}')
        missing = set().union(*classes) - tables
        self.assertFalse(missing, f'Tablas clasificadas que no existen: {sorted(missing)}')
        for i, first in enumerate(classes):
            for second in classes[i + 1:]:
                self.assertFalse(first & second, f'Tabla en dos clases: {sorted(first & second)}')

    def test_server_only_tables_never_publish(self):
        self.assertFalse(mirror_tables.SERVER_LOCAL & mirror_tables.MIRROR)
        self.assertEqual(mirror_tables.mirror_tables(), sorted(mirror_tables.MIRROR))


if __name__ == '__main__':
    unittest.main()
