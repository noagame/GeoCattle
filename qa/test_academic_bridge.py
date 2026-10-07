"""Ensayos de cola del puente; no representan ensayos de radio."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

spec = importlib.util.spec_from_file_location('academic_bridge', Path(__file__).resolve().parents[1] / 'adapters' / 'academic_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class Handler(BaseHTTPRequestHandler):
    status = 201
    def do_POST(self):
        json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(self.status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'id': 'test-persisted-id'}).encode())
    def log_message(self, *_):
        pass


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.spool = bridge.Spool(Path(self.temp.name) / 'queue.sqlite3')
        self.payload = {'hardware_id': 'academic-qa', 'session_id': 'boot-a', 'seq': 1, 'observed_at': '2026-10-07T12:00:00Z', 'gnss_valid': False}
        self.acks = []
        Handler.status = 201
        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/ingest'
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()
    def test_recovery_and_ack_after_success(self):
        self.spool.enqueue(dict(self.payload))
        Handler.status = 503
        self.assertEqual(self.spool.deliver(self.url, 'qa-only', self.acks.append), 0)
        self.assertEqual(self.spool.remaining(), 1)
        self.assertEqual(self.acks, [])
        # Abrir la misma cola conserva el paquete aunque reinicie el proceso.
        recovered = bridge.Spool(self.spool.path)
        Handler.status = 201
        self.assertEqual(recovered.deliver(self.url, 'qa-only', self.acks.append), 1)
        self.assertEqual(recovered.remaining(), 0)
        self.assertTrue(self.acks[0]['persisted'])
        self.assertEqual(self.acks[0]['seq'], 1)
    def test_rejected_payload_is_retained_without_ack(self):
        self.spool.enqueue(dict(self.payload))
        Handler.status = 422
        self.assertEqual(self.spool.deliver(self.url, 'qa-only', self.acks.append), 0)
        self.assertEqual(self.spool.remaining(), 1)
        self.assertEqual(self.acks, [])
        with self.spool.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM queue').fetchone()[0], 'failed')
    def test_duplicate_identity_and_changed_payload(self):
        self.spool.enqueue(dict(self.payload))
        self.spool.enqueue(dict(self.payload))
        self.assertEqual(self.spool.remaining(), 1)
        with self.assertRaises(ValueError):
            self.spool.enqueue({**self.payload, 'battery_mv': 3200})
    def test_capture_timezone_required(self):
        with self.assertRaises(ValueError):
            self.spool.enqueue({**self.payload, 'observed_at': '2026-10-07T12:00:00'})
        self.assertEqual(self.spool.remaining(), 0)


if __name__ == '__main__':
    unittest.main()
