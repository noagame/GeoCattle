"""MQTT QoS1 -> durable spool -> PostgreSQL transaction -> application receipt.

SQLite holds only a delivery queue. It is never an application-data backend.
ChirpStack must provide the versioned decoded object, including observation
clock, session_id and sequence; these are not invented from MQTT arrival.
"""
import hashlib
import json
import logging
import os
import signal
import sqlite3
import threading
import time
from pathlib import Path
import paho.mqtt.client as mqtt
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from .db import SessionLocal
from .domain import ingest
from .models import Device
from .schemas import TelemetryIn
from .settings import settings
log=logging.getLogger("geocattle.ingestor")

class Spool:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.path=path
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS messages (key TEXT PRIMARY KEY, topic TEXT NOT NULL, payload BLOB NOT NULL, mid INTEGER, qos INTEGER, generation INTEGER, received REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending', error TEXT)")
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        return db
    def put(self,topic,payload,mid,qos,generation):
        key=hashlib.sha256(topic.encode()+b"\0"+payload).hexdigest()
        with self.connect() as db:
            db.execute("INSERT INTO messages(key,topic,payload,mid,qos,generation,received) VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET mid=excluded.mid,qos=excluded.qos,generation=excluded.generation",(key,topic,payload,mid,qos,generation,time.time()))
        return key
    def is_rejected(self,key):
        with self.connect() as db:return db.execute("SELECT status FROM messages WHERE key=?",(key,)).fetchone()==("rejected",)
    def pending(self):
        with self.connect() as db:return db.execute("SELECT key,topic,payload,mid,qos,generation,received FROM messages WHERE status='pending' ORDER BY received LIMIT 50").fetchall()
    def done(self,key):
        with self.connect() as db:db.execute("DELETE FROM messages WHERE key=?",(key,))
    def reject(self,key,error):
        with self.connect() as db:db.execute("UPDATE messages SET status='rejected',error=? WHERE key=?",(error[:2000],key))

def decode(db,topic,raw):
    if len(raw)>65536:raise ValueError("Payload excede 64 KiB")
    data=json.loads(raw)
    if not isinstance(data,dict):raise ValueError("Contrato requiere objeto JSON")
    if "/event/up" in topic:
        decoded=data.get("object")
        if not isinstance(decoded,dict):raise ValueError("ChirpStack requiere object decodificado v1")
        info=data.get("deviceInfo",{})
        dev_eui=info.get("devEui") or data.get("devEui")
        if not dev_eui:raise ValueError("ChirpStack sin DevEUI autenticado")
        device=db.scalar(select(Device).where(Device.dev_eui==dev_eui.lower()))
        if not device:raise ValueError("DevEUI no registrado")
        data=dict(decoded)
        data["hardware_id"]=device.hardware_id
        data["source"]="lorawan"
        quality=dict(data.get("quality",{}));quality["transport"]="chirpstack"
        quality["rx_info"]=json.loads(raw).get("rxInfo",[])[:10]
        data["quality"]=quality
    return TelemetryIn.model_validate(data)

class Ingestor:
    def __init__(self,cfg=None):
        self.cfg=cfg or settings();self.spool=Spool(self.cfg.mqtt_spool_path);self.stop=threading.Event();self.generation=0
        self.client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=self.cfg.mqtt_client_id,clean_session=False,manual_ack=True)
        if self.cfg.mqtt_username:self.client.username_pw_set(self.cfg.mqtt_username,self.cfg.mqtt_password)
        if self.cfg.mqtt_tls:self.client.tls_set()
        self.client.on_connect=self.on_connect;self.client.on_message=self.on_message
        self.client.reconnect_delay_set(min_delay=1,max_delay=60)
    def on_connect(self,client,userdata,flags,reason_code,properties):
        if reason_code.is_failure:log.error("MQTT conexión rechazada: %s",reason_code);return
        self.generation+=1
        for topic in self.cfg.mqtt_topic.split(","):client.subscribe(topic.strip(),qos=1)
        log.info("MQTT conectado; cola persistente activa")
    def on_message(self,client,userdata,msg):
        try:
            key=self.spool.put(msg.topic,msg.payload,msg.mid,msg.qos,self.generation)
            if self.spool.is_rejected(key) and msg.qos:
                # Quarantine is already durable; no application committed receipt.
                client.ack(msg.mid,msg.qos)
        except Exception:
            log.exception("No se pudo guardar cola; mensaje sin acuse para redelivery")
            client.disconnect()
    def drain(self):
        for key,topic,payload,mid,qos,generation,received in self.spool.pending():
            try:
                with SessionLocal.begin() as db:
                    body=decode(db,topic,payload)
                    # Preserve queue arrival, so an outage does not rejuvenate communication.
                    from datetime import datetime,timezone
                    result=ingest(db,body,datetime.fromtimestamp(received,timezone.utc))
                # Database transaction has committed before any successful receipt.
                receipt={**result,"hardware_id":body.hardware_id,"session_id":body.session_id,"seq":body.seq,"status":"committed"}
                publish=self.client.publish(self.cfg.mqtt_ack_topic,json.dumps(receipt),qos=1)
                if publish.rc!=mqtt.MQTT_ERR_SUCCESS:continue
                publish.wait_for_publish(timeout=5)
                if not publish.is_published():continue
                if generation==self.generation and self.client.is_connected() and qos:self.client.ack(mid,qos)
                self.spool.done(key)
            except (ValidationError,ValueError,HTTPException) as exc:
                message=exc.detail if isinstance(exc,HTTPException) else str(exc)
                self.spool.reject(key,str(message))
                # Rejected data retained in durable quarantine, never reported committed.
                if generation==self.generation and self.client.is_connected() and qos:self.client.ack(mid,qos)
                log.warning("Payload en cuarentena: %s",str(message)[:200])
            except Exception:
                log.exception("PostgreSQL o transporte no disponible; cola conservada")
                break
    def run(self):
        self.client.connect_async(self.cfg.mqtt_host,self.cfg.mqtt_port,keepalive=60)
        self.client.loop_start()
        try:
            while not self.stop.wait(1):self.drain()
        finally:self.client.disconnect();self.client.loop_stop()

def main():
    logging.basicConfig(level=logging.INFO)
    runner=Ingestor()
    signal.signal(signal.SIGTERM,lambda *_:runner.stop.set());signal.signal(signal.SIGINT,lambda *_:runner.stop.set())
    runner.run()
if __name__=="__main__":main()
