-- Archival is independent of installed/maintenance/retired and preserves radio history.
ALTER TABLE gateways ADD COLUMN archived_at timestamptz;
ALTER TABLE gateways ADD COLUMN archived_by uuid REFERENCES users(id);
ALTER TABLE gateways ADD COLUMN version bigint NOT NULL DEFAULT 1 CHECK (version>=1);
ALTER TABLE gateways ADD CONSTRAINT gateway_archive_actor CHECK ((archived_at IS NULL)=(archived_by IS NULL));
ALTER TABLE gateways ADD CONSTRAINT gateway_position_wgs84 CHECK (
    position IS NULL OR (NOT ST_IsEmpty(position) AND
        ST_X(position) BETWEEN -180 AND 180 AND ST_Y(position) BETWEEN -90 AND 90)
);
CREATE INDEX gateways_operational_farm ON gateways(farm_id,name,id) WHERE archived_at IS NULL;
CREATE INDEX receptions_gateway_history ON telemetry_receptions(farm_id,gateway_id,received_at DESC,telemetry_id);

CREATE FUNCTION gateway_identity_immutable_v5() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.gateway_eui IS DISTINCT FROM OLD.gateway_eui OR NEW.farm_id IS DISTINCT FROM OLD.farm_id THEN
        RAISE EXCEPTION 'Identidad y predio del gateway son inmutables' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER gateway_identity_v5 BEFORE UPDATE ON gateways FOR EACH ROW EXECUTE FUNCTION gateway_identity_immutable_v5();
