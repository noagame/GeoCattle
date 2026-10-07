"""Independent timer and notification outbox. No provider call when unconfigured."""
import logging
import signal
import threading
from datetime import timedelta
import httpx
from sqlalchemy import func, select, text
from .db import SessionLocal
from .models import Event, Notification, NotificationAttempt, utcnow
from .domain import check_timeouts
from .settings import settings
log=logging.getLogger("geocattle.worker")

def process_outbox(db,event_id=None):
    cfg=settings();now=utcnow()
    query=select(Notification).where(Notification.status=="pending",Notification.next_attempt_at<=now)
    if event_id is not None:query=query.where(Notification.event_id==event_id)
    rows=db.scalars(query.order_by(Notification.created_at).with_for_update(skip_locked=True).limit(20)).all()
    for n in rows:
        e=db.get(Event,n.event_id)
        attempt=(db.scalar(select(func.max(NotificationAttempt.attempt)).where(NotificationAttempt.notification_id==n.id)) or 0)+1
        error=None;provider_id=None
        if not cfg.notification_webhook_url:
            status="disabled";error="Canal externo sin configurar; alerta local disponible"
        elif now-n.created_at>timedelta(hours=cfg.notification_expiry_hours) or e.condition=="resolved":
            status="expired";error="Ocurrencia resuelta o aviso vencido"
        else:
            try:
                headers={"Idempotency-Key":str(n.id)}
                if cfg.notification_webhook_token:headers["Authorization"]="Bearer "+cfg.notification_webhook_token
                response=httpx.post(cfg.notification_webhook_url,json={"event_id":str(e.id),"type":e.type,"severity":e.severity,"opened_at":e.opened_at.isoformat(),"condition":e.condition,"detail":e.detail,"meaning":"Entrega al proveedor; no prueba lectura humana"},headers=headers,timeout=5,follow_redirects=False)
                if response.is_success:status="accepted";provider_id=response.headers.get("X-Request-ID","")[:200] or None
                else:status="failed";error=f"Proveedor respondió HTTP {response.status_code}"
            except httpx.HTTPError as exc:status="failed";error=type(exc).__name__
        db.add(NotificationAttempt(notification_id=n.id,attempt=attempt,status=status,provider_id=provider_id,error=error))
        if status=="failed" and attempt<cfg.notification_max_attempts:
            n.next_attempt_at=now+timedelta(seconds=min(3600,60*2**(attempt-1)))
        else:n.status=status

def run_once():
    with SessionLocal.begin() as db:
        # Prevent duplicate workers from competing for condition creation.
        if db.scalar(text("SELECT pg_try_advisory_xact_lock(804193812)")):check_timeouts(db)
    with SessionLocal.begin() as db:
        from .downlink import dispatch_configs
        dispatch_configs(db)
    with SessionLocal.begin() as db:process_outbox(db)

def main():
    logging.basicConfig(level=logging.INFO)
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    while not stop.is_set():
        try:run_once()
        except Exception:log.exception("Falló ciclo; datos locales conservados, se reintentará")
        stop.wait(settings().worker_interval_seconds)
if __name__=="__main__":main()
