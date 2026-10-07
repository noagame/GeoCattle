CREATE TABLE maintenance (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, device_id uuid NOT NULL, battery_id text, kind text NOT NULL CHECK(kind IN ('inspection','recharge','replacement','retirement')), at timestamptz NOT NULL, responsible_id uuid NOT NULL REFERENCES users, result text NOT NULL, FOREIGN KEY(device_id,farm_id) REFERENCES devices(id,farm_id));
CREATE INDEX maintenance_farm_time ON maintenance(farm_id,at DESC);
CREATE TRIGGER maintenance_immutable BEFORE UPDATE OR DELETE ON maintenance FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation();
