"""Create explicitly synthetic trial data; rejects every non-simulation environment."""
import json
import random
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import func, select, text
from .db import SessionLocal
from .models import *
from .security import hash_password
from .schemas import TelemetryIn
from .domain import ingest,append_audit
from .settings import settings

def main():
    cfg=settings()
    if cfg.app_env!="simulation" or not cfg.simulation_enabled:raise SystemExit("Seed requiere APP_ENV=simulation y SIMULATION_ENABLED=true")
    if not cfg.demo_password or len(cfg.demo_password)<12:raise SystemExit("Defina DEMO_PASSWORD único de al menos 12 caracteres")
    random.seed(20261007)
    with SessionLocal.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(804193813)"))
        if db.scalar(select(User).where(User.username=="demo@geocattle.local")):
            print("Demo ya existe; no se modificó información ni contraseña");return
        farm=Farm(id=uuid4(),name="Predio demostrativo GeoCattle · Datos simulados",environment="simulation")
        db.add(farm);db.flush()
        owner=User(id=uuid4(),farm_id=farm.id,username="demo@geocattle.local",password_hash=hash_password(cfg.demo_password),role="owner",active=True)
        db.add(owner);db.add(RuleSettings(farm_id=farm.id,temperature_enabled=False,activity_enabled=False,proximity_enabled=False));db.flush()
        now=utcnow();since=now-timedelta(hours=24)
        sectors=[];fences=[]
        # Chilean WGS84 synthetic polygons. No claims about a real farm boundary.
        for idx,name in enumerate(["Potrero Norte","Potrero Centro","Potrero Sur"]):
            west=-72.65+idx*0.012;south=-38.75
            sector=Sector(id=uuid4(),farm_id=farm.id,name=name);db.add(sector);db.flush()
            geometry={"type":"Polygon","coordinates":[[[west,south],[west+.010,south],[west+.010,south+.010],[west,south+.010],[west,south]]]}
            fence=Geofence(id=uuid4(),farm_id=farm.id,sector_id=sector.id,name=name+" · Simulación",version=1,geometry=func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)),4326),active=True,created_at=since)
            db.add(fence);db.flush();sectors.append(sector);fences.append((fence,west,south))
        animals=[]
        for i in range(70):
            ix=i%3;fence,west,south=fences[ix]
            animal=Animal(id=uuid4(),farm_id=farm.id,diio=f"SIM-{i+1:06d}",name=f"Animal {i+1:02d}",orientation="milk" if i%4==0 else "meat",enabled=True,sector_id=sectors[ix].id)
            device=Device(id=uuid4(),farm_id=farm.id,hardware_id=f"sim-collar-{i+1:03d}",name=f"Collar simulado {i+1:02d}",transport="academic",enabled=True,interval_seconds=300,config_version=0,installed_at=since)
            db.add(animal);db.add(device);db.flush()
            db.add(Assignment(id=uuid4(),farm_id=farm.id,animal_id=animal.id,device_id=device.id,valid_from=since))
            db.add(PastureAssignment(id=uuid4(),farm_id=farm.id,animal_id=animal.id,geofence_id=fence.id,valid_from=since));db.flush()
            lon=west+.002+random.random()*.006;lat=south+.002+random.random()*.006
            # Seven actual trial hours, never presented as a completed 30-day history.
            for h in range(7,-1,-1):
                at=now-timedelta(hours=h,minutes=1)
                row=TelemetryIn(hardware_id=device.hardware_id,session_id="seed-simulation-v1",seq=8-h,observed_at=at,longitude=lon,latitude=lat,gnss_valid=True,surface_temperature_c=34+random.random()*2,activity_index=.4+random.random()*.3,battery_mv=3750,source="sim",quality={"simulation":True,"scenario":"seed","sensor_algorithm":"synthetic-v1"})
                ingest(db,row,received_at=at)
            animals.append((animal,device,fence,west,south))
        # Visible conditions generated through the same real ingestion/rules path.
        for i in (0,1):
            animal,device,fence,west,south=animals[i]
            for seq,offset in ((10,20),(11,0)):
                ingest(db,TelemetryIn(hardware_id=device.hardware_id,session_id="seed-escape",seq=seq,observed_at=now-timedelta(seconds=offset),longitude=west+.011,latitude=south+.005,gnss_valid=True,battery_mv=3750,source="sim",quality={"simulation":True,"scenario":"escape"}),received_at=now)
        for i in (3,4,5):
            animal,device,fence,west,south=animals[i]
            ingest(db,TelemetryIn(hardware_id=device.hardware_id,session_id="seed-battery",seq=1,observed_at=now,longitude=west+.005,latitude=south+.005,gnss_valid=True,battery_mv=3150,source="sim",quality={"simulation":True,"scenario":"low_battery"}),received_at=now)
        for i in (6,7):
            animal,device,fence,west,south=animals[i]
            ingest(db,TelemetryIn(hardware_id=device.hardware_id,session_id="seed-no-fix",seq=1,observed_at=now,gnss_valid=False,battery_mv=3700,source="sim",quality={"simulation":True,"scenario":"no_fix"}),received_at=now)
        # No notifications are sent by this command.
        append_audit(db,farm.id,owner.id,"farm",farm.id,"seed_simulation",after={"animals":70,"source":"sim","history_hours":7})
        print("Demo creada: 70 animales, historia sintética 7 h. Usuario demo@geocattle.local. Contraseña tomada de DEMO_PASSWORD.")
if __name__=="__main__":main()
