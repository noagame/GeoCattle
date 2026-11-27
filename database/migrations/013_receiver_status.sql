CREATE TABLE receiver_status (
    farm_id uuid PRIMARY KEY REFERENCES farms(id) ON DELETE CASCADE,
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    received_at timestamptz NOT NULL
);
