from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import Request
from .mirror_replay import replay_for
from .settings import settings
engine = create_engine(settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
def get_db(request: Request):
    replay = replay_for(request)
    if replay is not None:
        # The worker commits the operation and its result together.
        with replay.db.begin_nested():
            yield replay.db
        return
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
