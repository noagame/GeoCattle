#!/usr/bin/env python3
"""Prueba MQTT/QoS1 real con PostgreSQL y cola SQLite, sólo en simulation.

Usa backend/.venv/bin/python; lee .env privada sin imprimir credenciales.
BASE_URL=http://127.0.0.1:8000 backend/.venv/bin/python qa/test_mqtt_ingestion.py
No requiere un ingestor Docker: inicia uno local con tópicos/cola exclusivos QA.
"""
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import sqlite3
import sys
import threading
import time
from urllib.parse import quote
from uuid import uuid4

from smoke_api import API, private_env

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = private_env(ROOT / ".env")
    if config.get("APP_ENV") != "simulation" or config.get("SIMULATION_ENABLED", "").lower() != "true":
        raise SystemExit("MQTT QA requiere simulation explícitamente habilitada")
    run_id = uuid4().hex[:12]
    base = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
    api = API(base)
    code, health, _ = api.call("GET", "/health")
    if code != 200 or health.get("environment") != "simulation":
        raise SystemExit("API simulation requerida antes de cualquier escritura")
    identity, _ = api.login("demo@geocattle.local", config["DEMO_PASSWORD"])
    code, dashboard, _ = api.call("GET", "/dashboard")
    if code != 200 or dashboard["farm"]["environment"] != "simulation":
        raise SystemExit("Predio de simulación requerido")

    # Global backend modules must be imported only after the private local URL.
    os.environ.update(config)
    os.environ["DATABASE_URL"] = ("postgresql+psycopg://geocattle_app:" + quote(config["APP_DATABASE_PASSWORD"], safe="") +
                                  "@127.0.0.1:" + config["DB_PORT"] + "/" + config["POSTGRES_DB"])
    sys.path.insert(0, str(ROOT / "backend"))
    import paho.mqtt.client as mqtt
    from geocattle.ingestor import Ingestor, Spool
    from geocattle.settings import settings

    logging.disable(logging.CRITICAL)  # Never emit exception parameters/secrets.
    topic = "geocattle/qa/" + run_id + "/telemetry"
    ack_topic = "geocattle/qa/" + run_id + "/committed"
    spool_path = ROOT / "qa" / "spool" / ("mqtt-" + run_id + ".sqlite3")
    cfg = settings().model_copy(update={"mqtt_host": "127.0.0.1", "mqtt_port": int(config["MQTT_PORT"]),
             "mqtt_topic": topic, "mqtt_ack_topic": ack_topic, "mqtt_client_id": "qa-ingestor-" + run_id,
             "mqtt_spool_path": str(spool_path)})
    hardware = "mqtt-qa-" + run_id
    checks, receipts = [], Queue()
    runner = worker = publisher = anonymous = None
    animal = device = None
    error = None

    def check(name, success):
        checks.append({"check": name, "passed": bool(success)})
        print(("PASS " if success else "FAIL ") + name, flush=True)
        if not success:
            raise RuntimeError(name)

    def request(method, path, body=None, expected=200):
        status, result, _ = api.call(method, path, body)
        if status != expected:
            raise RuntimeError(f"HTTP {status} en {method} {path}")
        return result

    def wait_until(predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(.02)
        return False

    def wait_receipt(sequence):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                value = receipts.get(timeout=max(.01, deadline-time.monotonic()))
            except Empty:
                break
            if value.get("hardware_id") == hardware and value.get("seq") == sequence:
                return value
        raise RuntimeError("No se recibió confirmación de aplicación MQTT")

    def payload(sequence, observed=None):
        return {"schema_version": 1, "hardware_id": hardware, "session_id": "mqtt-session-" + run_id,
                "seq": sequence, "observed_at": (observed or datetime.now(timezone.utc)).isoformat(),
                "longitude": None, "latitude": None, "gnss_valid": False,
                "surface_temperature_c": 35, "activity_index": 1, "battery_mv": 4100,
                "source": "sim", "quality": {"synthetic": True, "qa_run": run_id}}

    def start_ingestor():
        instance = Ingestor(cfg)
        # Observe real transport acknowledgements without replacing their effect.
        original_ack = instance.client.ack
        instance.qa_ack_calls = []
        def observed_ack(mid, qos):
            result = original_ack(mid, qos)
            instance.qa_ack_calls.append((mid, qos, result))
            return result
        instance.client.ack = observed_ack
        subscribed = threading.Event()
        instance.client.on_subscribe = lambda *_: subscribed.set()
        thread = threading.Thread(target=instance.run, daemon=True)
        thread.start()
        if not subscribed.wait(10):
            instance.stop.set()
            thread.join(5)
            raise RuntimeError("Ingestor no pudo suscribirse al broker local")
        return instance, thread

    try:
        # Rejection proves allow_anonymous=false independently of the happy path.
        rejected = threading.Event()
        rejection = []
        anonymous = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="qa-anonymous-" + run_id)
        def on_rejected(client, userdata, flags, reason, properties):
            rejection.append(reason.is_failure)
            rejected.set()
            client.disconnect()
        anonymous.on_connect = on_rejected
        anonymous.connect("127.0.0.1", cfg.mqtt_port, 20)
        anonymous.loop_start()
        check("Broker real rechaza conexión anónima", rejected.wait(5) and rejection == [True])
        anonymous.disconnect()
        anonymous.loop_stop()
        anonymous = None

        animal = request("POST", "/animals", {"diio": "MQTTQA" + run_id, "name": "MQTT QA " + run_id, "orientation": "meat"}, 201)
        device = request("POST", "/devices", {"hardware_id": hardware, "name": "MQTT QA " + run_id,
                         "transport": "academic", "interval_seconds": 300}, 201)
        request("POST", "/assignments", {"animal_id": animal["id"], "device_id": device["id"],
                    "effective_at": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}, 201)

        ready = threading.Event()
        publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="qa-publisher-" + run_id)
        publisher.username_pw_set(config["MQTT_USERNAME"], config["MQTT_PASSWORD"])
        def on_connect(client, userdata, flags, reason, properties):
            if not reason.is_failure:
                client.subscribe(ack_topic, qos=1)
        publisher.on_connect = on_connect
        publisher.on_subscribe = lambda *_: ready.set()
        def on_message(client, userdata, message):
            try:
                receipts.put(json.loads(message.payload))
            except (ValueError, UnicodeDecodeError):
                pass
        publisher.on_message = on_message
        publisher.connect("127.0.0.1", cfg.mqtt_port, 30)
        publisher.loop_start()
        check("Publicador autenticado y suscrito", ready.wait(10))
        runner, worker = start_ingestor()
        check("Ingestor real suscrito con tópico QA aislado", runner.client.is_connected())

        packet = json.dumps(payload(1)).encode()
        sent = publisher.publish(topic, packet, qos=1)
        sent.wait_for_publish(timeout=5)
        check("Broker confirma publicación QoS1", sent.is_published())
        committed = wait_receipt(1)
        check("ACK de aplicación confirma commit PostgreSQL", committed.get("status") == "committed" and not committed["duplicate"])
        history = request("GET", f"/animals/{animal['id']}/history")
        check("Lectura real persistida antes del ACK", history["total"] == 1 and history["items"][0]["id"] == committed["id"])
        received_at = history["items"][0]["received_at"]

        sent = publisher.publish(topic, packet, qos=1)
        sent.wait_for_publish(timeout=5)
        duplicate = wait_receipt(1)
        check("Redelivery produce ACK duplicado sin nueva fila", duplicate["duplicate"] and duplicate["id"] == committed["id"] and
              request("GET", f"/animals/{animal['id']}/history")["total"] == 1)
        check("Redelivery no altera recepción original", request("GET", f"/animals/{animal['id']}/history")["items"][0]["received_at"] == received_at)
        check("Cola confirmada queda vacía", wait_until(lambda: not runner.spool.pending()))

        runner.stop.set()
        worker.join(10)
        check("Ingestor detenido para prueba de recuperación", not worker.is_alive())
        runner = worker = None
        captured = datetime.now(timezone.utc) - timedelta(seconds=120)
        queued = json.dumps(payload(2, captured)).encode()
        spool = Spool(str(spool_path))
        key = spool.put(topic, queued, 0, 1, 0)
        # Controlled arrival time models a previous interruption, not real WAN loss.
        with spool.connect() as db:
            db.execute("UPDATE messages SET received=? WHERE key=?", (captured.timestamp(), key))
        reopened = Spool(str(spool_path))
        check("SQLite conserva pendiente al reabrir", len(reopened.pending()) == 1 and reopened.pending()[0][0] == key)
        runner, worker = start_ingestor()
        replay = wait_receipt(2)
        history = request("GET", f"/animals/{animal['id']}/history")
        row = next(t for t in history["items"] if t["seq"] == 2)
        check("Reinicio drena cola a PostgreSQL una sola vez", replay["status"] == "committed" and not replay["duplicate"] and history["total"] == 2)
        check("Replay conserva hora original de recepción", abs(datetime.fromisoformat(row["received_at"].replace("Z", "+00:00")).timestamp()-captured.timestamp()) < .001)
        check("Replay tardío no retrocede estado reciente", not replay.get("state_updated", True) and request("GET", "/animals/" + animal["id"])["last_telemetry"]["id"] == committed["id"])
        check("Cola recuperada se vacía sólo tras commit", wait_until(lambda: not runner.spool.pending()))

        invalid = payload(3)
        invalid["source"] = "unsupported"
        invalid_raw = json.dumps(invalid).encode()
        acknowledged_before = len(runner.qa_ack_calls)
        publisher.publish(topic, invalid_raw, qos=1).wait_for_publish(timeout=5)
        def quarantine():
            with sqlite3.connect(spool_path) as db:
                return db.execute("SELECT count(*) FROM messages WHERE status='rejected'").fetchone()[0] == 1
        check("Contrato inválido queda en cuarentena durable", wait_until(lambda: quarantine() and
              len(runner.qa_ack_calls) > acknowledged_before and runner.qa_ack_calls[-1][2] == mqtt.MQTT_ERR_SUCCESS))
        acknowledged_before = len(runner.qa_ack_calls)
        publisher.publish(topic, invalid_raw, qos=1).wait_for_publish(timeout=5)
        check("Redelivery inválido conserva una cuarentena", wait_until(lambda: quarantine() and
              len(runner.qa_ack_calls) > acknowledged_before and runner.qa_ack_calls[-1][2] == mqtt.MQTT_ERR_SUCCESS))
        check("Cuarentena no escribe telemetría ni confirma commit", request("GET", f"/animals/{animal['id']}/history")["total"] == 2 and
              not any(receipt.get("seq") == 3 and receipt.get("status") == "committed" for receipt in list(receipts.queue)))
    except Exception as exc:
        # Do not serialize raw exceptions, connection URLs, payloads or config.
        error = str(exc) if isinstance(exc, RuntimeError) else "Prueba abortada: " + type(exc).__name__
        print(error, flush=True)
    finally:
        if runner:
            runner.stop.set()
            worker.join(10)
        if publisher:
            publisher.disconnect()
            publisher.loop_stop()
        if anonymous:
            anonymous.disconnect()
            anonymous.loop_stop()
        if device:
            api.call("PATCH", "/devices/" + device["id"], {"enabled": False})
        if animal:
            api.call("PATCH", "/animals/" + animal["id"], {"enabled": False})
        api.call("POST", "/auth/logout")
        result = {"run_id": run_id, "at": datetime.now(timezone.utc).isoformat(), "environment": "simulation",
                  "broker": "127.0.0.1:" + str(cfg.mqtt_port), "application_backend": "PostgreSQL/PostGIS",
                  "transport_spool": "SQLite WAL/FULL", "checks": checks,
                  "passed": sum(c["passed"] for c in checks), "failed": sum(not c["passed"] for c in checks),
                  "aborted": error is not None, "error": error,
                  "limits": ["No prueba radio, firmware ni codec LoRaWAN físico.",
                             "Recuperación usa reinicio real del ingestor y arribo controlado; no corta WAN ni PostgreSQL."]}
        output = ROOT / "qa" / "mqtt_latest.json"
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(f"MQTT QA: {result['passed']} aprobadas, {result['failed']} fallidas; mqtt_latest.json", flush=True)
    return 1 if error or any(not c["passed"] for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
