import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.lora_usb import Archive, decode

WIRE = '4,REAL01,4C29EA44282ED941,3,device,48066,0,-1,nan,nan,nan,0.546,-0.640,-0.448,nan,3,16847,3935,73,1,0'
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)


class DecoderTests(unittest.TestCase):
    def test_diagnostic_no_fix_preserves_axes_and_battery(self):
        p, wire = decode('Contenido: ' + WIRE, NOW, {'rssi_dbm': -26., 'snr_db': 9.})
        self.assertEqual(wire, WIRE)
        self.assertIsNone(p['latitude'])
        self.assertIsNone(p['surface_temperature_c'])
        self.assertEqual(p['battery_mv'], 3935)
        self.assertEqual(p['quality']['acceleration_g']['x'], .546)
        self.assertEqual(p['quality']['time_basis'], 'pc_first_reception')
        json.dumps(p, allow_nan=False)

    def test_normal_receiver_radio(self):
        p, _ = decode(WIRE + ',-27,9.2', NOW)
        self.assertEqual(p['quality']['radio'], {'rssi_dbm': -27., 'snr_db': 9.2})

    def test_usb_without_battery(self):
        p, _ = decode(WIRE.rsplit(',', 4)[0] + ',-1,-1,0,0', NOW)
        self.assertIsNone(p['battery_mv'])
        self.assertFalse(p['quality']['battery_present'])

    def test_reject_simulation_and_nonfinite_and_bad_fix(self):
        for wire in (WIRE.replace(',device,', ',sim,'), WIRE.replace('0.546', 'inf'),
                     WIRE.replace(',0,-1,nan,nan,', ',1,-1,nan,nan,')):
            with self.assertRaises(ValueError): decode(wire, NOW)

    def test_ignore_debug(self):
        self.assertIsNone(decode('[ESTADO] Tiempo=5', NOW))

    def test_duplicate_keeps_first_timestamp_and_conflict_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Archive(temp)
            self.assertTrue(archive.enqueue(*decode(WIRE, NOW)))
            later = NOW.replace(second=20)
            self.assertFalse(archive.enqueue(*decode(WIRE, later)))
            with self.assertRaises(ValueError):
                archive.enqueue(*decode(WIRE.replace('3935', '3934'), later))
            self.assertEqual(archive.stats()['captured'], 1)
            with archive.connection() as db:
                payload = json.loads(db.execute('SELECT payload FROM captures').fetchone()[0])
            self.assertEqual(payload['observed_at'], NOW.isoformat())
            self.assertEqual(Archive(temp).stats()['pending'], 1)

    def test_api_unavailable_keeps_capture_then_confirms_without_deleting_archive(self):
        class Handler(BaseHTTPRequestHandler):
            accepted = False
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(201 if self.accepted else 503)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'id': 'persisted-id', 'seq': body['seq']}).encode())
            def log_message(self, *args): pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                archive = Archive(temp)
                archive.enqueue(*decode(WIRE, NOW))
                url = f'http://127.0.0.1:{server.server_port}'
                archive.deliver(url, 'test-key')
                self.assertEqual(archive.stats()['pending'], 1)
                Handler.accepted = True
                with archive.connection() as db:
                    db.execute('UPDATE captures SET next_attempt=0')
                archive.deliver(url, 'test-key')
                self.assertEqual(archive.stats()['pending'], 0)
                self.assertEqual(archive.stats()['delivered'], 1)
                self.assertEqual(archive.stats()['captured'], 1)
        finally:
            server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__': unittest.main()
