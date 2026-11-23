from collections import defaultdict, deque
from time import monotonic
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

from geocattle import main
from geocattle.schemas import LoginIn
from geocattle.security import check_session_csrf, service_auth
from geocattle.settings import settings


@pytest.mark.parametrize(
    ('header', 'validate', 'expected_status'),
    [
        (b'x-csrf-token', lambda request, secret: check_session_csrf(
            request, SimpleNamespace(csrf_token=secret)), 403),
        (b'x-ingest-key', lambda request, secret: service_auth(request), 401),
    ],
)
def test_auth_header_rejects_missing_incorrect_and_non_ascii_bytes(
    monkeypatch, header, validate, expected_status,
):
    secret = 'qa-only-secret'
    monkeypatch.setattr(settings(), 'ingest_key', secret)
    for headers in ([], [(header, b'incorrect')], [(header, 'inválido'.encode())]):
        with pytest.raises(HTTPException) as error:
            validate(Request({'type': 'http', 'headers': headers}), secret)
        assert error.value.status_code == expected_status

    validate(Request({'type': 'http', 'headers': [(header, secret.encode())]}), secret)


def test_login_rejects_when_attempt_budget_is_already_exhausted(monkeypatch):
    username = 'qa@example.test'
    address = '127.0.0.1'
    attempts = defaultdict(deque, {(address, username): deque([monotonic()] * 10)})
    monkeypatch.setattr(main, 'login_attempts', attempts)
    request = Request({'type': 'http', 'client': (address, 12345), 'headers': []})
    with pytest.raises(HTTPException) as error:
        main.login(LoginIn(username=username, password='qa-only-password'), request, Response(), db=None)
    assert error.value.status_code == 429
