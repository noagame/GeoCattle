"""Regression: a new assignment does not inherit a prior collar timeout.

Uses the migrated TEST_DATABASE_URL and rollback fixture only, no live API.
"""
from datetime import timedelta
import os

import pytest
from sqlalchemy import select

from geocattle.domain import check_timeouts, ingest
from geocattle.models import Event
from test_integration import data, packet

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
    reason="Requiere PostgreSQL/PostGIS de prueba migrado")


@pytest.mark.parametrize('interval', [180, 300])
def test_new_assignment_does_not_inherit_earlier_radio_silence(data, interval):
    db, _, _, _, animal, device, _, assignment, now = data
    threshold = 3 * interval + 30
    device.interval_seconds = interval
    device.last_received_at = now - timedelta(seconds=threshold + 1)
    assignment.valid_from = now
    db.flush()

    check_timeouts(db, now + timedelta(seconds=1))

    assert db.scalar(select(Event).where(Event.device_id == device.id,
        Event.type == 'communication_timeout', Event.condition == 'active')) is None


@pytest.mark.parametrize('interval', [180, 300])
def test_timeout_uses_applied_interval_exact_boundary_and_fresh_packet_recovery(data, interval):
    db, _, _, _, animal, device, _, assignment, now = data
    device.interval_seconds = interval
    threshold = 3 * interval + 30
    ingest(db, packet(device, now, 1), now)

    check_timeouts(db, now + timedelta(seconds=threshold))
    query = select(Event).where(Event.device_id == device.id, Event.type == 'communication_timeout')
    assert db.scalar(query) is None

    check_timeouts(db, now + timedelta(seconds=threshold + 1))
    event = db.scalar(query)
    assert event is not None and event.condition == 'active'
    assert event.detail['threshold_seconds'] == threshold
    assert event.animal_id == animal.id

    recovered = now + timedelta(seconds=threshold + 2)
    ingest(db, packet(device, recovered, 2), recovered)
    assert event.condition == 'resolved'
    assert event.resolved_at == recovered
    assert device.last_received_at == recovered
