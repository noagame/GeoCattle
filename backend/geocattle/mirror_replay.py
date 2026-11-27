"""In-process replay context carried by a worker-owned ASGI transport."""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Replay:
    db: Session
    outbox_id: UUID
    actor_id: UUID
    farm_id: UUID | None
    kind: str


# A Python object key can only be supplied by an in-process ASGI caller.
_REPLAY = object()


def replay_for(request):
    return request.scope.get(_REPLAY)


def replay_transport(app, replay):
    async def forward(scope, receive, send):
        await app({**scope, _REPLAY: replay}, receive, send)

    return forward
