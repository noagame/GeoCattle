"""Optional ChirpStack queue scheduling; a broker PUBACK is not device application.
Official topic and JSON object contract:
https://www.chirpstack.io/docs/chirpstack/integrations/mqtt.html
Requires validated external codec. Disabled by default, including simulation.
"""
import json
import threading
from datetime import datetime,timezone
from uuid import uuid4
import paho.mqtt.client as mqtt
from sqlalchemy import select
from .domain import append_audit
from .models import Device,DeviceConfig
from .settings import settings

def envelope(cfg,device,config):
    topic=f"application/{cfg.chirpstack_application_id}/device/{device.dev_eui}/command/down"
    payload={"devEui":device.dev_eui,"confirmed":False,"fPort":cfg.config_fport,"object":{"schema_version":1,"config_version":config.version,"interval_seconds":config.interval_seconds}}
    return topic,payload

def send_to_broker(cfg,device,config):
    connected=threading.Event()
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id="geocattle-downlink-"+str(uuid4()))
    def on_connect(client,userdata,flags,reason,properties):
        if not reason.is_failure:connected.set()
    client.on_connect=on_connect
    if cfg.mqtt_username:client.username_pw_set(cfg.mqtt_username,cfg.mqtt_password)
    if cfg.mqtt_tls:client.tls_set()
    client.connect_async(cfg.mqtt_host,cfg.mqtt_port,keepalive=30);client.loop_start()
    try:
        if not connected.wait(5):raise RuntimeError("Sin conexión autenticada al broker")
        topic,payload=envelope(cfg,device,config)
        publication=client.publish(topic,json.dumps(payload),qos=1)
        if publication.rc!=mqtt.MQTT_ERR_SUCCESS:raise RuntimeError("Broker no aceptó publicación")
        publication.wait_for_publish(timeout=5)
        if not publication.is_published():raise RuntimeError("Sin PUBACK; configuración permanece solicitada")
        return {"topic":topic,"mqtt_mid":publication.mid,"meaning":"PUBACK broker; no confirma aplicación ni recepción del módulo"}
    finally:client.disconnect();client.loop_stop()

def dispatch_configs(db,sender=send_to_broker,cfg=None):
    cfg=cfg or settings()
    if not cfg.config_downlink_enabled:return
    rows=db.execute(select(Device,DeviceConfig).join(DeviceConfig,DeviceConfig.device_id==Device.id).where(Device.enabled.is_(True),Device.transport=="lorawan",Device.dev_eui.is_not(None),DeviceConfig.status=="requested").order_by(Device.id).limit(20).with_for_update(skip_locked=True,of=(Device,DeviceConfig))).all()
    for device,config in rows:
        try:
            receipt=sender(cfg,device,config)
        except Exception as exc:
            # Retain requested; independent timeout handles unconfirmed commands.
            config.error=type(exc).__name__
            continue
        config.status="sent";config.sent_at=datetime.now(timezone.utc);config.error=None
        append_audit(db,device.farm_id,None,"device_config",config.id,"sent_to_network_queue",after={"version":config.version,**receipt})
