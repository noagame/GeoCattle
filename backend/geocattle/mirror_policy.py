"""Write allowlist shared by the replica and the field replay."""
import base64
import hashlib
import re
from uuid import UUID

from cryptography.fernet import Fernet

from .settings import settings


V3 = '/api/v1/v3'
CHANGES = V3 + '/changes'
DRAFTS = V3 + '/drafts'
CREATE_OWNER = V3 + '/admin/owners'
SUPPORT_REQUESTS = '/api/v1/auth/support-requests'
CHANGE_ACTIONS = frozenset({'animal_profile', 'health_record', 'health_schedule'})
WRITE_DENIED = 'Este cambio se registra en el PC del campo'

_LOCAL_POSTS = frozenset('/api/v1/auth/' + suffix for suffix in (
    'login', 'logout', 'mfa/verify', 'context', 'step-up',
))
_ITEM_WRITES = {
    ('PATCH', V3 + '/admin/owners', ''): 'admin_order',
    ('PATCH', V3 + '/admin/users', ''): 'admin_order',
    ('POST', V3 + '/admin/users', '/owner'): 'admin_order',
    ('POST', SUPPORT_REQUESTS, '/decision'): 'admin_order',
    ('POST', CHANGES, '/decision'): 'admin_order',
    ('PUT', DRAFTS, ''): 'draft_revision',
    ('DELETE', DRAFTS, ''): 'draft_revision',
    ('POST', DRAFTS, '/submit'): 'draft_revision',
    ('POST', V3 + '/notifications', '/read'): 'local',
}


def write_target(method, path):
    if method == 'POST':
        if path in _LOCAL_POSTS:
            return 'local'
        if path == CREATE_OWNER:
            return 'admin_order'
        if path == SUPPORT_REQUESTS:
            return 'support_request'
        if path == CHANGES:
            return 'change'
        if path == DRAFTS:
            return 'draft_revision'
    match = re.fullmatch(r'(.+)/([\da-fA-F-]{36})(/[^/]+)?', path, flags=re.ASCII)
    if match:
        try:
            UUID(match[2])
        except ValueError:
            return None
        return _ITEM_WRITES.get((method, match[1], match[3] or ''))
    return None


def write_kind(method, path, body, *, platform_admin, veterinarian):
    target = write_target(method, path)
    if target == 'change':
        if body.get('device_id') or body.get('action') == 'battery_replacement':
            return None
        if platform_admin:
            return 'admin_order'
        action = body.get('action')
        if veterinarian and isinstance(action, str) and action in CHANGE_ACTIONS:
            return 'remote_change'
    if target == 'admin_order' and platform_admin:
        return target
    if target == 'draft_revision' and veterinarian:
        return target
    if target == 'support_request':
        return target
    return None


def kind_enabled(kind):
    config = settings()
    return config.mirror_remote_admin if kind == 'admin_order' else config.mirror_remote_changes


def owner_password_cipher():
    key = hashlib.sha256(b'geocattle-mirror-owner-password:' + settings().mirror_sync_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))
