ALTER TABLE gateways ALTER COLUMN gateway_eui DROP NOT NULL;
ALTER TABLE gateways ADD COLUMN node_id smallint CHECK (node_id IN (1, 2));
ALTER TABLE gateways ADD COLUMN node_linked_at timestamptz;
ALTER TABLE gateways ADD CONSTRAINT gateways_node_link CHECK ((node_id IS NULL) = (node_linked_at IS NULL));
ALTER TABLE gateways ADD CONSTRAINT gateways_identity_present CHECK (gateway_eui IS NOT NULL OR node_id IS NOT NULL);
CREATE UNIQUE INDEX gateways_active_node ON gateways(farm_id, node_id) WHERE archived_at IS NULL;

CREATE TABLE gateway_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    farm_id uuid NOT NULL REFERENCES farms(id),
    node_id smallint CHECK (node_id IN (1, 2)),
    reserved_node_id smallint CHECK (reserved_node_id IN (1, 2)),
    gateway_eui text CHECK (gateway_eui ~ '^[0-9a-f]{16}$'),
    firmware text CHECK (length(firmware) BETWEEN 1 AND 100),
    source text NOT NULL CHECK (source IN ('usb', 'radio')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'dismissed')),
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL CHECK (last_seen_at >= first_seen_at),
    seen_count bigint NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
    resolved_at timestamptz,
    resolved_by uuid REFERENCES users(id),
    gateway_id uuid,
    FOREIGN KEY (gateway_id, farm_id) REFERENCES gateways(id, farm_id),
    CHECK ((source = 'usb') = (gateway_eui IS NOT NULL)),
    CHECK ((source = 'usb') = (firmware IS NOT NULL)),
    CHECK (source = 'usb' OR node_id IS NOT NULL),
    CHECK (reserved_node_id IS NULL OR (source = 'usb' AND status = 'pending')),
    CHECK ((status = 'pending') = (resolved_at IS NULL) AND (resolved_at IS NULL) = (resolved_by IS NULL)),
    CHECK ((status = 'approved') = (gateway_id IS NOT NULL))
);
CREATE UNIQUE INDEX gateway_candidates_pending_usb ON gateway_candidates(farm_id, gateway_eui)
    WHERE status = 'pending' AND source = 'usb';
CREATE UNIQUE INDEX gateway_candidates_pending_radio ON gateway_candidates(farm_id, node_id)
    WHERE status = 'pending' AND source = 'radio';
CREATE UNIQUE INDEX gateway_candidates_reserved_node ON gateway_candidates(farm_id, reserved_node_id)
    WHERE reserved_node_id IS NOT NULL;
CREATE INDEX gateway_candidates_farm_seen ON gateway_candidates(farm_id, status, last_seen_at DESC);

CREATE TABLE gateway_bus_receipts (
    farm_id uuid NOT NULL REFERENCES farms(id),
    hardware_id text NOT NULL,
    session_id text NOT NULL,
    seq bigint NOT NULL,
    node_id smallint NOT NULL CHECK (node_id IN (1, 2)),
    PRIMARY KEY (farm_id, hardware_id, session_id, seq, node_id)
);
