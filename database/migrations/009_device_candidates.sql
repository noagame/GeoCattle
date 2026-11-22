CREATE TABLE device_candidates (
    id uuid PRIMARY KEY,
    farm_id uuid NOT NULL REFERENCES farms,
    hardware_id text NOT NULL CHECK (hardware_id ~ '^[A-Za-z0-9_:-]{1,100}$'),
    transport text NOT NULL CHECK (transport IN ('academic', 'lorawan')),
    dev_eui text CHECK (dev_eui ~ '^[0-9a-f]{16}$'),
    interval_seconds integer NOT NULL CHECK (interval_seconds BETWEEN 30 AND 86400),
    firmware_version text,
    source text NOT NULL CHECK (source IN ('usb', 'radio')),
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL CHECK (last_seen_at >= first_seen_at),
    seen_count bigint NOT NULL CHECK (seen_count > 0),
    last_payload jsonb NOT NULL CHECK (jsonb_typeof(last_payload) = 'object'),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'dismissed')),
    resolved_at timestamptz,
    resolved_by uuid REFERENCES users,
    device_id uuid,
    UNIQUE (id, farm_id, hardware_id),
    FOREIGN KEY (device_id, farm_id) REFERENCES devices (id, farm_id),
    CHECK ((status = 'pending' AND resolved_at IS NULL AND resolved_by IS NULL)
        OR (status <> 'pending' AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL)),
    CHECK ((status = 'approved') = (device_id IS NOT NULL))
);

CREATE UNIQUE INDEX device_candidates_pending_identity
    ON device_candidates (farm_id, hardware_id) WHERE status = 'pending';
CREATE INDEX device_candidates_farm_status_seen
    ON device_candidates (farm_id, status, last_seen_at DESC);

-- A capture acknowledged as a detection remains a detection on redelivery,
-- including after the collar is approved or dismissed.
CREATE TABLE device_candidate_captures (
    farm_id uuid NOT NULL,
    hardware_id text NOT NULL,
    session_id text NOT NULL,
    seq bigint NOT NULL CHECK (seq >= 0),
    candidate_id uuid NOT NULL,
    PRIMARY KEY (farm_id, hardware_id, session_id, seq),
    FOREIGN KEY (candidate_id, farm_id, hardware_id) REFERENCES device_candidates (id, farm_id, hardware_id)
);
