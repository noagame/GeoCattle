import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.compartir_base import ShareError, check_migrations, checked_archive


class ShareDatabaseTests(unittest.TestCase):
    def test_accepts_current_and_older_migration_histories(self):
        available = ['001_schema.sql', '002_maintenance.sql']
        check_migrations(available, available)
        check_migrations(available[:1], available)

    def test_rejects_empty_newer_and_divergent_migration_histories(self):
        available = ['001_schema.sql', '002_maintenance.sql']
        for applied in ([], available + ['003_new.sql'], ['001_other.sql'], available[1:]):
            with self.subTest(applied=applied), self.assertRaisesRegex(ShareError, 'Migraciones incompatibles'):
                check_migrations(applied, available)

    def test_checks_digest_before_returning_archive_stream(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / 'geocattle.dump'
            archive.write_bytes(b'test archive')
            sidecar = archive.with_suffix('.sha256')
            with self.assertRaisesRegex(ShareError, 'Falta'):
                with checked_archive(archive):
                    self.fail('Missing SHA-256 accepted')
            sidecar.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '\n', encoding='ascii')
            with checked_archive(archive) as stream:
                self.assertEqual(stream.read(), b'test archive')
            archive.write_bytes(b'changed archive')
            with self.assertRaisesRegex(ShareError, 'SHA-256 no coincide'):
                with checked_archive(archive):
                    self.fail('Changed archive accepted')
