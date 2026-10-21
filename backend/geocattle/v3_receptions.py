"""Scoped radio receptions: one sensor reading may reach several gateways."""
from pydantic import ValidationError
from sqlalchemy import text
from .schemas import ReceptionIn


def chirpstack_receptions(rx_info):
    """Invalid radio metadata never discards an otherwise valid decoded uplink."""
    if not isinstance(rx_info,list):
        return []
    receptions=[]
    for item in rx_info[:10]:
        if not isinstance(item,dict):
            continue
        candidate={"gateway_eui":item.get("gatewayId"),"rssi_dbm":item.get("rssi"),"snr_db":item.get("snr")}
        if item.get("time") is not None:
            candidate["received_at"]=item["time"]
        try:
            receptions.append(ReceptionIn.model_validate(candidate))
        except ValidationError:
            continue
    return receptions


def persist_receptions(db,telemetry,receptions,server_received_at):
    """Ignore unknown/foreign gateways and leave device freshness untouched.

    Only a newly persisted pair advances the gateway clock. This avoids turning
    MQTT redelivery into fresh radio evidence. Queue arrival is supplied by the
    caller; an antenna's untrusted clock never advances last_seen_at.
    """
    for reception in sorted(receptions,key=lambda item:item.gateway_eui):
        db.execute(text("""
            WITH inserted AS (
                INSERT INTO telemetry_receptions
                    (telemetry_id,farm_id,gateway_id,received_at,rssi_dbm,snr_db)
                SELECT :telemetry,:farm,g.id,:received,:rssi,:snr
                FROM gateways g WHERE g.farm_id=:farm AND g.gateway_eui=:eui
                ON CONFLICT (telemetry_id,gateway_id) DO NOTHING
                RETURNING gateway_id
            )
            UPDATE gateways g
            SET last_seen_at=CASE WHEN g.last_seen_at IS NULL OR g.last_seen_at<:server_time
                                 THEN :server_time ELSE g.last_seen_at END
            FROM inserted i WHERE g.id=i.gateway_id AND g.farm_id=:farm
        """),{"telemetry":telemetry.id,"farm":telemetry.farm_id,"eui":reception.gateway_eui,
               "received":reception.received_at or server_received_at,
               "rssi":reception.rssi_dbm,"snr":reception.snr_db,"server_time":server_received_at})
