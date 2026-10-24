"""Validación local del contrato; datos ficticios, sin radio ni base de datos."""
import sys
import unittest
from pathlib import Path
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from geocattle.schemas import TelemetryIn, DeviceIn


def example_payload():
    return {
        'schema_version': 1, 'hardware_id': 'REAL01',
        'session_id': '0123456789abcdef', 'seq': 1,
        # Fecha ficticia explícita: el firmware actual todavía no la envía.
        'observed_at': '2026-10-21T15:00:00Z',
        'latitude': -33.123456, 'longitude': -70.123456,
        'gnss_valid': True, 'surface_temperature_c': 24.5,
        'activity_index': None, 'battery_mv': 3950, 'source': 'academic',
        'quality': {
            'wire_protocol_version': 4, 'uptime_ms': 15000,
            'gps_age_ms': 300, 'flags': 0, 'period_ms': 15000,
            'acceleration_g': {'x': 0.001, 'y': 0.002, 'z': 1.0},
            'battery_percent_estimated': 65, 'battery_present': True,
            'battery_charging': False,
            'radio': {'rssi_dbm': -50, 'snr_db': 8.5},
            'test_fixture': True,
        },
    }


class ESP32ContractTests(unittest.TestCase):
    def test_proposed_mapping_is_valid(self):
        value = TelemetryIn.model_validate(example_payload())
        self.assertEqual(value.hardware_id, 'REAL01')
        self.assertEqual(value.quality['acceleration_g']['z'], 1.0)

    def test_no_fix_and_no_battery(self):
        data = example_payload()
        data.update(gnss_valid=False, latitude=None, longitude=None, battery_mv=None)
        data['quality'].update(battery_present=False, battery_percent_estimated=None,
                               battery_charging=None)
        self.assertIsNone(TelemetryIn.model_validate(data).latitude)

    def test_capture_time_is_required(self):
        data = example_payload()
        del data['observed_at']
        with self.assertRaises(ValidationError):
            TelemetryIn.model_validate(data)

    def test_device_source_needs_mapping(self):
        data = example_payload()
        data['source'] = 'device'
        with self.assertRaises(ValidationError):
            TelemetryIn.model_validate(data)

    def test_radio_version_is_not_api_version(self):
        data = example_payload()
        data['schema_version'] = 4
        with self.assertRaises(ValidationError):
            TelemetryIn.model_validate(data)

    def test_acceleration_is_metadata_not_top_level(self):
        data = example_payload()
        data['acceleration_g'] = {'x': 0, 'y': 0, 'z': 1}
        with self.assertRaises(ValidationError):
            TelemetryIn.model_validate(data)

    def test_device_interval_does_not_allow_15_seconds(self):
        with self.assertRaises(ValidationError):
            DeviceIn(hardware_id='REAL01', name='Collar 01', transport='academic',
                     interval_seconds=15)


if __name__ == '__main__':
    unittest.main()
