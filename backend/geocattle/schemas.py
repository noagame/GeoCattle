from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
class LoginIn(Strict):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)
class AnimalIn(Strict):
    diio: str = Field(min_length=1,max_length=64,pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1,max_length=100)
    orientation: Literal["meat","milk"]
    sector_id: UUID | None = None
class AnimalPatch(Strict):
    name: str | None = Field(default=None,min_length=1,max_length=100)
    orientation: Literal["meat","milk"] | None = None
    sector_id: UUID | None = None
    enabled: bool | None = None
class DeviceIn(Strict):
    hardware_id: str = Field(min_length=1,max_length=100,pattern=r"^[A-Za-z0-9_:-]+$")
    dev_eui: str | None = Field(default=None,pattern=r"^[0-9a-fA-F]{16}$")
    name: str = Field(min_length=1,max_length=100)
    transport: Literal["academic","lorawan"]
    interval_seconds: int = Field(default=300,ge=30,le=86400)
class AssignmentIn(Strict):
    animal_id: UUID
    device_id: UUID
    effective_at: datetime | None = None
    replace: bool = False
    @field_validator("effective_at")
    @classmethod
    def aware(cls,v): return check_time(v)
class SectorIn(Strict):
    land_use: Literal["grazing","available","cropped","restricted","other"] = "grazing"
    description: str | None = Field(default=None,max_length=1000)
    name: str = Field(min_length=1,max_length=100)
class GeofenceIn(Strict):
    geofence_key: UUID | None = None
    sector_id: UUID | None = None
    sector_ids: list[UUID] = Field(default_factory=list, max_length=100)
    name: str = Field(min_length=1,max_length=100)
    geometry: dict
    expected_version: int = Field(ge=0)
    confirm_impact: bool
    @model_validator(mode="after")
    def sectors(self):
        if not self.sector_ids and self.sector_id is None: raise ValueError("Seleccione al menos un sector")
        if len(set(self.sector_ids)) != len(self.sector_ids): raise ValueError("Sectores repetidos")
        if self.sector_id and self.sector_ids and self.sector_id not in self.sector_ids: raise ValueError("Sector principal no asociado")
        return self
    @field_validator("geometry")
    @classmethod
    def polygon(cls,v):
        if set(v) != {"type","coordinates"} or v.get("type") != "Polygon": raise ValueError("Se requiere GeoJSON Polygon")
        rings=v.get("coordinates")
        if not isinstance(rings,list) or not rings or len(rings)>100: raise ValueError("Polígono sin anillos o demasiado complejo")
        if len(rings)!=1:raise ValueError("Geocerca sin huecos interiores")
        count=0
        for ring in rings:
            if not isinstance(ring,list) or len(ring)<5 or ring[0]!=ring[-1]: raise ValueError("Cada anillo requiere al menos cuatro vértices distintos y cierre")
            for p in ring:
                if not isinstance(p,list) or len(p)!=2 or isinstance(p[0],bool) or isinstance(p[1],bool) or not isinstance(p[0],(float,int)) or not isinstance(p[1],(float,int)) or not -180<=p[0]<=180 or not -90<=p[1]<=90: raise ValueError("Coordenadas WGS84 inválidas")
            if len({tuple(p) for p in ring[:-1]})<4:raise ValueError("Se requieren cuatro vértices distintos")
            if len({tuple(p) for p in ring[:-1]}) != len(ring)-1:raise ValueError("No se permiten vértices repetidos")
            count+=len(ring)
        if count>10000: raise ValueError("Máximo 10000 vértices")
        return v
class PastureIn(Strict):
    animal_id: UUID
    geofence_id: UUID
    effective_at: datetime | None = None
    @field_validator("effective_at")
    @classmethod
    def aware(cls,v): return check_time(v)
class ActionIn(Strict):
    action: Literal["acknowledge","review","conclude","reopen"]
    note: str = Field(min_length=1,max_length=2000)
class ConfigIn(Strict):
    interval_seconds: int = Field(ge=30,le=86400)
    expected_version: int = Field(ge=0)
class SettingsIn(Strict):
    expected_version: int = Field(ge=1)
    battery_low_mv: int = Field(ge=0,le=20000)
    temperature_high_c: float | None = Field(default=None,ge=-60,le=100)
    activity_low_threshold: float | None = Field(default=None,ge=0,le=1000000)
    activity_window_minutes: int = Field(ge=1,le=1440)
    proximity_meters: float = Field(ge=0,le=1000)
    temperature_enabled: bool
    activity_enabled: bool
    proximity_enabled: bool
    @model_validator(mode="after")
    def thresholds(self):
        if self.temperature_enabled and self.temperature_high_c is None: raise ValueError("Umbral térmico requerido")
        if self.activity_enabled and self.activity_low_threshold is None: raise ValueError("Umbral actividad requerido")
        return self
class ReceptionIn(Strict):
    gateway_eui: str = Field(pattern=r"^[0-9a-fA-F]{16}$")
    rssi_dbm: float = Field(strict=True,allow_inf_nan=False,ge=-200,le=20)
    snr_db: float = Field(strict=True,allow_inf_nan=False,ge=-100,le=100)
    received_at: datetime | None = None
    @field_validator("gateway_eui")
    @classmethod
    def normalized_eui(cls,v): return v.lower()
    @field_validator("received_at")
    @classmethod
    def aware(cls,v): return check_time(v)

class TelemetryIn(Strict):
    schema_version: Literal[1] = 1
    hardware_id: str = Field(min_length=1,max_length=100)
    session_id: str = Field(min_length=1,max_length=100)
    seq: int = Field(ge=0,le=9223372036854775807)
    observed_at: datetime
    longitude: float | None = Field(default=None,ge=-180,le=180)
    latitude: float | None = Field(default=None,ge=-90,le=90)
    gnss_valid: bool
    surface_temperature_c: float | None = Field(default=None,ge=-60,le=100)
    activity_index: float | None = Field(default=None,ge=0,le=1000000)
    battery_mv: int | None = Field(default=None,ge=0,le=20000)
    source: Literal["sim","academic","lorawan"]
    quality: dict = Field(default_factory=dict)
    config_version: int | None = Field(default=None,ge=0)
    receptions: list[ReceptionIn] = Field(default_factory=list,max_length=10)
    @field_validator("observed_at")
    @classmethod
    def aware(cls,v): return check_time(v)
    @model_validator(mode="after")
    def fix(self):
        if self.gnss_valid and (self.longitude is None or self.latitude is None): raise ValueError("Fix válido requiere longitud y latitud")
        if not self.gnss_valid and (self.longitude is not None or self.latitude is not None): raise ValueError("Sin fix las coordenadas deben ser nulas")
        import json
        if len(json.dumps(self.quality))>16384: raise ValueError("Quality demasiado grande")
        return self
class ScenarioIn(Strict):
    scenario: Literal["normal","escape","return","low_battery","no_fix","timeout"]
    animal_id: UUID | None = None

def check_time(v):
    if v is not None:
        if v.tzinfo is None or v.utcoffset() is None: raise ValueError("Fecha requiere zona horaria")
        return v.astimezone(timezone.utc)
    return v
class MaintenanceIn(Strict):
    device_id: UUID
    battery_id: str | None = Field(default=None,max_length=100)
    kind: Literal["inspection","recharge","replacement","retirement"]
    at: datetime | None = None
    result: str = Field(min_length=1,max_length=2000)
    @field_validator("at")
    @classmethod
    def aware(cls,v):return check_time(v)
class DevicePatch(Strict):
    enabled: bool

class SectorPatch(Strict):
    name: str | None = Field(default=None,min_length=1,max_length=100)
    land_use: Literal["grazing","available","cropped","restricted","other"] | None = None
    usage: Literal["grazing","available","cropped","restricted","other"] | None = None
    description: str | None = Field(default=None,max_length=1000)
    active: bool | None = None
