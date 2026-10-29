-- Keep every version UUID and all telemetry/pasture/event references intact.
ALTER TABLE geofences ADD COLUMN geofence_key uuid;
WITH roots AS (
  SELECT id, first_value(id) OVER (PARTITION BY farm_id, sector_id ORDER BY version, created_at, id) AS root
  FROM geofences
)
UPDATE geofences g SET geofence_key=r.root FROM roots r WHERE r.id=g.id;
ALTER TABLE geofences ALTER COLUMN geofence_key SET DEFAULT gen_random_uuid();
ALTER TABLE geofences ALTER COLUMN geofence_key SET NOT NULL;
DROP INDEX geofence_one_active;
ALTER TABLE geofences DROP CONSTRAINT geofences_sector_id_version_key;
ALTER TABLE geofences ADD CONSTRAINT geofence_identity_version UNIQUE (geofence_key, version);
CREATE UNIQUE INDEX geofence_one_active_identity ON geofences(geofence_key) WHERE active;

-- Associations are versioned along with the geometry. sector_id remains the
-- primary/default sector for compatibility; it is included in this relation.
CREATE TABLE geofence_sectors (
  geofence_id uuid NOT NULL,
  sector_id uuid NOT NULL,
  farm_id uuid NOT NULL,
  PRIMARY KEY (geofence_id, sector_id),
  FOREIGN KEY (geofence_id, farm_id) REFERENCES geofences(id, farm_id),
  FOREIGN KEY (sector_id, farm_id) REFERENCES sectors(id, farm_id)
);
INSERT INTO geofence_sectors SELECT id,sector_id,farm_id FROM geofences;
CREATE INDEX geofence_sectors_by_sector ON geofence_sectors(farm_id,sector_id);

ALTER TABLE events ADD COLUMN last_position_id uuid;
ALTER TABLE events ADD CONSTRAINT event_position_same_farm
  FOREIGN KEY (last_position_id,farm_id) REFERENCES telemetry(id,farm_id);
-- Only observations actually received before detection and attributed to the
-- same collar/animal assignment count. Late arrivals cannot rewrite history.
UPDATE events e SET last_position_id=(
  SELECT t.id FROM telemetry t
  JOIN assignments a ON a.id=t.assignment_id AND a.device_id=e.device_id AND a.animal_id=e.animal_id
  WHERE t.farm_id=e.farm_id AND t.device_id=e.device_id AND t.animal_id=e.animal_id
    AND a.valid_from<=e.opened_at AND (a.valid_to IS NULL OR a.valid_to>e.opened_at)
    AND t.observed_at>=a.valid_from AND (a.valid_to IS NULL OR t.observed_at<a.valid_to)
    AND t.gnss_valid AND t.longitude IS NOT NULL AND t.latitude IS NOT NULL
    AND t.observed_at<=e.opened_at AND t.received_at<=e.opened_at
  ORDER BY t.observed_at DESC,t.received_at DESC,t.id DESC LIMIT 1
) WHERE e.type='communication_timeout';
CREATE INDEX telemetry_assignment_valid_position ON telemetry(assignment_id,observed_at DESC,received_at DESC) WHERE gnss_valid;

CREATE FUNCTION protect_event_position_v4() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' THEN
    IF NEW.last_position_id IS DISTINCT FROM OLD.last_position_id THEN
      RAISE EXCEPTION 'La posición histórica del evento es inmutable' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.last_position_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM telemetry t JOIN assignments a ON a.id=t.assignment_id
    WHERE t.id=NEW.last_position_id AND t.farm_id=NEW.farm_id
      AND t.device_id=NEW.device_id AND t.animal_id=NEW.animal_id
      AND a.device_id=NEW.device_id AND a.animal_id=NEW.animal_id
      AND a.valid_from<=NEW.opened_at AND (a.valid_to IS NULL OR a.valid_to>NEW.opened_at)
      AND t.observed_at>=a.valid_from AND (a.valid_to IS NULL OR t.observed_at<a.valid_to)
      AND t.gnss_valid AND t.latitude IS NOT NULL AND t.longitude IS NOT NULL
      AND t.observed_at<=NEW.opened_at AND t.received_at<=NEW.opened_at
  ) THEN
    RAISE EXCEPTION 'Posición incompatible con la detección y la asociación histórica' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER event_position_v4 BEFORE INSERT OR UPDATE ON events FOR EACH ROW EXECUTE FUNCTION protect_event_position_v4();
