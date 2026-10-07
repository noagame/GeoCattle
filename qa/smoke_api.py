#!/usr/bin/env python3
"""Prueba funcional HTTP real, exclusiva de la base de simulación.

Usa sólo Python stdlib, cookies HttpOnly y CSRF. Lee .env sin imprimir secretos.
No borra datos: agrega un conjunto pequeño identificado por UUID en simulación.
BASE_URL=http://localhost:8080 python3 qa/smoke_api.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def private_env(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


class API:
    def __init__(self, base: str):
        self.base = base.rstrip("/") + "/api/v1"
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.csrf = None

    def call(self, method, path, body=None, *, csrf=True, headers=None):
        h = {"Accept": "application/json"}
        if body is not None:
            h["Content-Type"] = "application/json"
        if csrf and self.csrf and method not in ("GET", "HEAD", "OPTIONS"):
            h["X-CSRF-Token"] = self.csrf
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, method=method, headers=h)
        try:
            response = self.opener.open(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                payload = json.loads(raw) if raw else None
            except (ValueError, UnicodeDecodeError):
                payload = None
            return response.status, payload, dict(response.headers)

    def login(self, username, password):
        code, data, headers = self.call("POST", "/auth/login", {"username": username, "password": password})
        if code != 200:
            raise RuntimeError(f"Login QA rechazado: HTTP {code}; no se imprimen credenciales")
        self.csrf = data["csrf_token"]
        return data, headers


class Smoke:
    def __init__(self, api, config, base):
        self.api, self.config, self.base = api, config, base
        self.run_id = uuid4().hex[:12]
        self.results = []
        self.seq = 0
        self.last_time = datetime.now(timezone.utc)

    def check(self, name, passed):
        self.results.append({"check": name, "passed": bool(passed)})
        print(("PASS " if passed else "FAIL ") + name)
        return passed

    def request(self, method, path, body=None, expected=200, **kwargs):
        code, data, _ = self.api.call(method, path, body, **kwargs)
        allowed = (expected,) if isinstance(expected, int) else expected
        self.check(f"{method} {path.split('?')[0]} HTTP {code}", code in allowed)
        if code not in allowed:
            raise RuntimeError(f"HTTP inesperado {code} en {method} {path.split('?')[0]}")
        return data

    def event_rows(self, animal_id):
        data = self.request("GET", "/events?limit=500")
        return [e for e in data["items"] if e["animal_id"] == animal_id]

    def device(self, device_id):
        return next(d for d in self.request("GET", "/devices")["items"] if d["id"] == device_id)

    def ingest(self, longitude=-72.645, latitude=-38.745, valid=True, observed=None, config_version=None):
        self.seq += 1
        now = datetime.now(timezone.utc)
        observed = observed or max(now, self.last_time + timedelta(microseconds=1))
        self.last_time = max(self.last_time, observed)
        body = {
            "schema_version": 1, "hardware_id": self.hardware,
            "session_id": "qa-" + self.run_id, "seq": self.seq,
            "observed_at": observed.isoformat(), "longitude": longitude if valid else None,
            "latitude": latitude if valid else None, "gnss_valid": valid,
            "surface_temperature_c": 35.0, "activity_index": 2.0, "battery_mv": 4100,
            "source": "sim", "quality": {"qa_run": self.run_id, "synthetic": True},
        }
        if config_version is not None:
            body["config_version"] = config_version
        result = self.request("POST", "/ingest/telemetry", body, 201, csrf=False,
                              headers={"X-Ingest-Key": self.config["INGEST_KEY"]})
        return body, result

    def run(self):
        # BEFORE login or any writable API: require local AND remote simulation.
        if self.config.get("APP_ENV") != "simulation" or self.config.get("SIMULATION_ENABLED", "").lower() != "true":
            raise RuntimeError("Guard: sólo APP_ENV=simulation y SIMULATION_ENABLED=true permiten ejecutar QA")
        health = self.request("GET", "/health")
        if health.get("environment") != "simulation":
            raise RuntimeError("Guard: API remota no es simulation; no se hacen escrituras")
        self.check("Guard local y remoto de simulación", True)
        password = self.config.get("SMOKE_PASSWORD") or self.config.get("DEMO_PASSWORD")
        if not password or not self.config.get("INGEST_KEY"):
            raise RuntimeError("Faltan credenciales privadas de simulación")
        username = self.config.get("SMOKE_USERNAME", "demo@geocattle.local")
        identity, headers = self.api.login(username, password)
        self.check("Login owner y token CSRF", identity["user"]["role"] == "owner" and bool(self.api.csrf))
        cookie = next((value for key, value in headers.items() if key.lower() == "set-cookie"), "").lower()
        self.check("Cookie HttpOnly y SameSite", "httponly" in cookie and "samesite=lax" in cookie)
        me = self.request("GET", "/auth/me")
        self.check("Sesión recuperable", me["user"]["id"] == identity["user"]["id"])
        immediate_codes = []
        for _ in range(5):
            probe = API(self.base)
            probe.login(username, password)
            immediate_codes.append(probe.call("GET", "/auth/me")[0])
            probe.call("POST", "/auth/logout")
        self.check("Cinco sesiones confirmadas antes de respuesta", immediate_codes == [200] * 5)
        baseline = self.request("GET", "/dashboard")
        if baseline["farm"]["environment"] != "simulation":
            raise RuntimeError("Guard: predio no es simulation; no se crean datos")
        self.check("Dashboard contiene base de 70 bovinos", baseline["summary"]["total"] >= 70)
        self.check("Resumen corresponde a lista", baseline["summary"]["total"] == len(baseline["animals"]))

        anon = API(self.base)
        code, _, _ = anon.call("GET", "/dashboard")
        self.check("Sin sesión GET dashboard 401", code == 401)
        code, _, _ = self.api.call("POST", "/sectors", {"name": "csrf-" + self.run_id}, csrf=False)
        self.check("Sin CSRF escritura 403", code == 403)
        code, _, _ = self.api.call("POST", "/sectors", {"name": "origin-" + self.run_id},
                                    headers={"Origin": "https://qa-invalid.example"})
        self.check("Origen externo escritura 403", code == 403)
        self.request("GET", "/animals/" + str(uuid4()), expected=403)

        sector = self.request("POST", "/sectors", {"name": "QA " + self.run_id}, 201)
        animal_body = {"diio": "QA" + self.run_id, "name": "Ensayo " + self.run_id,
                       "orientation": "milk", "sector_id": sector["id"]}
        animal = self.request("POST", "/animals", animal_body, 201)
        self.animal_id = animal["id"]
        self.request("POST", "/animals", animal_body, 409)
        self.hardware = "qa-" + self.run_id
        device = self.request("POST", "/devices", {"hardware_id": self.hardware,
                              "name": "Collar QA " + self.run_id, "transport": "academic", "interval_seconds": 300}, 201)
        device_id = device["id"]
        assignment_body = {"animal_id": animal["id"], "device_id": device_id,
                           "effective_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}
        self.request("POST", "/assignments", assignment_body, 201)
        self.request("POST", "/assignments", assignment_body, 409)

        polygon = {"type": "Polygon", "coordinates": [[[-72.65,-38.75],[-72.64,-38.75],
                    [-72.64,-38.74],[-72.65,-38.74],[-72.65,-38.75]]]}
        fence_body = {"sector_id": sector["id"], "name": "Zona QA " + self.run_id,
                      "geometry": polygon, "expected_version": 0, "confirm_impact": True}
        fence = self.request("POST", "/geofences", fence_body, 201)
        self.request("POST", "/geofences", fence_body, 409)
        invalid = {"type": "Polygon", "coordinates": [[[-72.65,-38.75],[-72.64,-38.74],
                   [-72.64,-38.75],[-72.65,-38.74],[-72.65,-38.75]]]}
        self.request("POST", "/geofences", dict(fence_body, geometry=invalid, expected_version=1), 422)
        self.request("POST", "/geofences", dict(fence_body, expected_version=1, confirm_impact=False), 422)
        current = [g for g in self.request("GET", "/geofences")["items"] if g["sector_id"] == sector["id"]]
        self.check("Errores conservan versión activa", len(current) == 1 and current[0]["active"] and current[0]["version"] == 1)
        self.request("POST", "/pasture-assignments", {"animal_id": animal["id"], "geofence_id": fence["id"]}, 201)

        body, first = self.ingest()
        first_time = datetime.fromisoformat(body["observed_at"])
        state = self.request("GET", "/animals/" + animal["id"])
        self.check("Lectura interior asociada y vigente", first["animal_id"] == animal["id"] and
                   state["geofence_status"] == "inside" and state["position_status"] == "fresh")
        self.ingest(-72.65,-38.745)  # Edge: ST_Covers includes it.
        state = self.request("GET", "/animals/" + animal["id"])
        self.check("Borde se incluye en geocerca", state["geofence_status"] == "inside")
        self.ingest(-72.66,-38.745)
        self.check("Primer exterior no confirma salida", not any(e["type"] == "escape" for e in self.event_rows(animal["id"])))
        self.ingest(valid=False)
        self.ingest(-72.66,-38.745)
        self.check("Sin fix rompe dos exteriores consecutivos", not any(e["type"] == "escape" for e in self.event_rows(animal["id"])))
        packet, escaped = self.ingest(-72.66,-38.745)
        escapes = [e for e in self.event_rows(animal["id"]) if e["type"] == "escape" and e["condition"] == "active"]
        self.check("Dos exteriores generan una salida crítica", len(escapes) == 1 and escapes[0]["severity"] == "critical")
        if not escapes:
            raise RuntimeError("No se creó evento de salida requerido para seguir QA")
        event = escapes[0]
        self.check("Evento conserva lectura y geocerca causantes", event.get("telemetry_id") == escaped["id"] and
                   event.get("geofence_id") == fence["id"])
        received_before = self.device(device_id)["last_received_at"]
        duplicate = self.request("POST", "/ingest/telemetry", packet, 201, csrf=False,
                                 headers={"X-Ingest-Key": self.config["INGEST_KEY"]})
        self.check("Deduplicación global y recibo intacto", duplicate["duplicate"] and duplicate["id"] == escaped["id"] and
                   self.device(device_id)["last_received_at"] == received_before)
        acknowledged = self.request("POST", f"/events/{event['id']}/actions", {"action": "acknowledge", "note": "Ensayo auditable " + self.run_id})
        self.check("Reconocer no resuelve condición", acknowledged["condition"] == "active" and acknowledged["attention"] == "acknowledged")
        self.check("Acción conserva actor y fecha", len(acknowledged["actions"]) == 1 and acknowledged["actions"][0]["actor_id"] == identity["user"]["id"])
        self.ingest(valid=False)
        self.check("GNSS nulo no resuelve salida", any(e["id"] == event["id"] and e["condition"] == "active" for e in self.event_rows(animal["id"])))
        self.ingest()
        returned = next(e for e in self.event_rows(animal["id"]) if e["id"] == event["id"])
        self.check("Regreso válido resuelve y conserva atención", returned["condition"] == "resolved" and returned["attention"] == "acknowledged" and returned["resolved_at"] is not None)
        self.ingest(valid=False)
        state = self.request("GET", "/animals/" + animal["id"])
        self.check("GNSS nulo muestra geocerca desconocida", state["geofence_status"] == "unknown" and state["last_telemetry"]["longitude"] is None)
        self.check("Calidad desconocida no se pinta normal", state["status"] != "normal")
        _, latest = self.ingest()
        received_before = self.device(device_id)["last_received_at"]
        _, late = self.ingest(-72.66,-38.745, observed=first_time + timedelta(microseconds=1))
        state = self.request("GET", "/animals/" + animal["id"])
        self.check("Tardío sólo completa historia", not late.get("state_updated", True) and state["last_telemetry"]["id"] == latest["id"])
        self.check("Tardío no rejuvenece comunicación", self.device(device_id)["last_received_at"] == received_before)
        history = self.request("GET", f"/animals/{animal['id']}/history?limit=500")
        self.check("Historia única y ordenada", len({t["id"] for t in history["items"]}) == history["total"] and
                   [t["observed_at"] for t in history["items"]] == sorted(t["observed_at"] for t in history["items"]))
        self.check("Fuente simulada y campos independientes", all(t["source"] == "sim" for t in history["items"]) and
                   any(not t["gnss_valid"] and t["surface_temperature_c"] == 35 for t in history["items"]))
        self.request("GET", f"/animals/{animal['id']}/history?limit=1&offset=1")
        query = urlencode({"start": datetime.now(timezone.utc).isoformat(), "end": first_time.isoformat()})
        self.request("GET", f"/animals/{animal['id']}/history?{query}", expected=422)

        config = self.request("POST", f"/devices/{device_id}/config", {"interval_seconds": 180, "expected_version": 0}, 201)
        pending = self.device(device_id)
        self.check("Guardar T sólo solicita configuración", config["status"] == "requested" and pending["interval_seconds"] == 300 and
                   pending["config_version"] == 0 and pending["pending_config"]["version"] == config["version"])
        self.request("POST", f"/devices/{device_id}/config", {"interval_seconds": 180, "expected_version": 0}, 409)
        self.request("POST", f"/devices/{device_id}/config", {"interval_seconds": 0, "expected_version": config["version"]}, 422)
        self.ingest(config_version=config["version"])
        applied = self.device(device_id)
        self.check("Nodo confirma T aplicado", applied["interval_seconds"] == 180 and applied["config_version"] == config["version"] and applied["pending_config"] is None)

        updated = self.request("POST", "/geofences", dict(fence_body, expected_version=1), 201)
        versions = [g for g in self.request("GET", "/geofences")["items"] if g["sector_id"] == sector["id"]]
        self.check("Geocerca conserva versión anterior", len(versions) == 2 and updated["version"] == 2 and sum(g["active"] for g in versions) == 1)
        self.request("POST", "/pasture-assignments", {"animal_id": animal["id"], "geofence_id": fence["id"]}, 409)
        self.ingest()
        self.check("Nueva versión conserva asignación vigente", self.request("GET", "/animals/" + animal["id"])["geofence_status"] == "inside")
        self.request("POST", "/simulation/scenarios", {"scenario": "timeout", "animal_id": animal["id"]})
        timeout = [e for e in self.event_rows(animal["id"]) if e["type"] == "communication_timeout" and e["condition"] == "active"]
        self.check("Temporizador independiente genera ausencia", len(timeout) == 1 and
                   self.request("GET", "/animals/" + animal["id"])["communication_status"] == "absent")
        self.check("Ausencia usa 3T+30 segundos", bool(timeout) and timeout[0]["detail"].get("threshold_seconds") == 570)
        self.ingest()
        self.check("Paquete nuevo resuelve ausencia", not any(e["type"] == "communication_timeout" and e["condition"] == "active" for e in self.event_rows(animal["id"])))
        bad_packet = dict(packet, seq=999999)
        code, _, _ = anon.call("POST", "/ingest/telemetry", bad_packet)
        self.check("Ingesta sin credencial 401", code == 401)
        code, _, _ = anon.call("POST", "/ingest/telemetry", bad_packet, headers={"X-Ingest-Key": "invalid-qa-key"})
        self.check("Ingesta credencial inválida 401", code == 401)
        notifications = self.request("GET", "/notifications")
        self.check("Salida local conserva aviso en cola", any(n["event_id"] == event["id"] for n in notifications["items"]))
        audit = self.request("GET", "/audit?limit=500")
        self.check("Cambios y reconocimiento auditados", any(a["object_id"] == event["id"] and a["action"] == "acknowledge" for a in audit["items"]))
        maintenance_body = {"device_id": device_id, "kind": "inspection", "result": "Inspección simulada QA " + self.run_id}
        maintenance = self.request("POST", "/maintenance", maintenance_body, 201)
        self.check("Mantenimiento registra responsable de sesión", maintenance["responsible_id"] == identity["user"]["id"])
        listed_maintenance = self.request("GET", "/maintenance?" + urlencode({"device_id": device_id}))
        self.check("Mantenimiento recuperable por dispositivo", any(m["id"] == maintenance["id"] for m in listed_maintenance["items"]))
        report = self.request("GET", "/reports")
        self.check("Reporte identifica origen simulado", report["simulated_samples"] == report["telemetry_count"] and report["telemetry_count"] > 0)

        # Optional seed roles: each is only tested when explicitly provisioned.
        for role in ("viewer", "operator", "other"):
            role_username = self.config.get("SMOKE_" + role.upper() + "_USERNAME")
            if not role_username:
                continue
            role_api = API(self.base)
            role_identity, _ = role_api.login(role_username, password)
            if role == "other":
                code, other_dashboard, _ = role_api.call("GET", "/dashboard")
                self.check("Sesión de otro predio consulta dashboard", code == 200)
                if code != 200:
                    raise RuntimeError("Login del otro predio no queda disponible para GET dashboard inmediato")
                self.check("Lista otro predio no filtra datos ajenos", all(a["id"] != animal["id"] for a in other_dashboard["animals"]))
                code, _, _ = role_api.call("GET", "/animals/" + animal["id"])
                self.check("Otro predio no consulta animal 403", code == 403 and role_identity["user"]["farm_id"] != identity["user"]["farm_id"])
                code, _, _ = role_api.call("POST", f"/events/{event['id']}/actions", {"action": "review", "note": "QA aislamiento"})
                self.check("Otro predio no modifica evento 403", code == 403)
                code, _, _ = role_api.call("POST", "/maintenance", maintenance_body)
                self.check("Otro predio no registra mantenimiento ajeno 403", code == 403)
            else:
                code, _, _ = role_api.call("GET", "/animals/" + animal["id"])
                self.check(f"Rol {role} puede consultar predio 200", code == 200)
                code, _, _ = role_api.call("POST", "/animals", dict(animal_body, diio="DENIED" + uuid4().hex))
                self.check(f"Rol {role} no administra animales 403", code == 403)
                if role == "viewer":
                    code, _, _ = role_api.call("POST", f"/events/{event['id']}/actions", {"action": "review", "note": "QA permisos"})
                    self.check("Viewer no modifica atención 403", code == 403)
                    code, _, _ = role_api.call("POST", "/maintenance", maintenance_body)
                    self.check("Viewer no registra mantenimiento 403", code == 403)
                else:
                    code, data, _ = role_api.call("POST", f"/events/{event['id']}/actions", {"action": "review", "note": "QA operador"})
                    self.check("Operator puede revisar sin alterar condición", code == 200 and data["condition"] == "resolved" and data["attention"] == "in_review")
                    code, _, _ = role_api.call("POST", "/maintenance", dict(maintenance_body, kind="recharge"))
                    self.check("Operator registra mantenimiento autorizado", code == 201)
            role_api.call("POST", "/auth/logout")

        second_animal = self.request("POST", "/animals", dict(animal_body, diio="QA2" + self.run_id, name="Reasignación QA " + self.run_id), 201)
        self.request("POST", "/assignments", {"animal_id": second_animal["id"], "device_id": device_id, "replace": True}, 201)
        historical_body, historical = self.ingest(observed=first_time + timedelta(microseconds=2))
        self.check("Reasignación conserva asociación histórica", historical["animal_id"] == animal["id"] and not historical.get("state_updated", True))
        dedup_global = self.request("POST", "/ingest/telemetry", body, 201, csrf=False,
                                    headers={"X-Ingest-Key": self.config["INGEST_KEY"]})
        self.check("Deduplicación anterior a resolver asignación", dedup_global["duplicate"] and dedup_global["id"] == first["id"] and dedup_global["animal_id"] == animal["id"])
        _, newest = self.ingest()
        self.check("Nueva captura pertenece a animal reasignado", newest["animal_id"] == second_animal["id"])
        retired = self.request("PATCH", "/devices/" + device_id, {"enabled": False})
        self.check("Retiro técnico explícito", not retired["enabled"])
        self.request("PATCH", "/animals/" + animal["id"], {"enabled": False})
        self.request("PATCH", "/animals/" + second_animal["id"], {"enabled": False})
        self.request("POST", "/auth/logout", expected=204)
        code, _, _ = self.api.call("GET", "/auth/me")
        self.check("Logout invalida sesión 401", code == 401)

    def save(self, output, error=None):
        data = {"run_id": self.run_id, "at": datetime.now(timezone.utc).isoformat(),
                "base_url": self.base, "environment": self.config.get("APP_ENV", "unknown"), "checks": self.results,
                "passed": sum(r["passed"] for r in self.results),
                "failed": sum(not r["passed"] for r in self.results), "aborted": error is not None,
                "error": error, "limits": ["No acredita pruebas de terreno, hardware, WAN ni SLA.",
                  "Roles y otro predio sólo ejecutados si SMOKE_*_USERNAME están provisionados."]}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(f"Resultado: {data['passed']} aprobadas, {data['failed']} fallidas; evidencia {output.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, default=ROOT / "qa" / "smoke_latest.json")
    args = parser.parse_args()
    try:
        config = private_env(args.env_file)
    except OSError:
        print("No se pudo leer el archivo privado de configuración; no se ejecutó QA", file=sys.stderr)
        return 2
    config.update({k: v for k, v in os.environ.items() if k in config or k.startswith("SMOKE_")})
    base = os.environ.get("BASE_URL", "http://localhost:8080")
    smoke = Smoke(API(base), config, base)
    error = None
    try:
        smoke.run()
    except (RuntimeError, URLError, KeyError, StopIteration, TypeError, ValueError) as exc:
        # Never serialize request/response bodies or configuration/secrets.
        error = str(exc) if isinstance(exc, RuntimeError) else "Prueba abortada: " + type(exc).__name__
        print(error, file=sys.stderr)
    smoke.save(args.output, error)
    return 1 if error or any(not r["passed"] for r in smoke.results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
