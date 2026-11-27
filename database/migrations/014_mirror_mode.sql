-- Modo espejo: el PC del campo es el sistema principal y el servidor web lo replica.
-- Se aplica igual en ambos lados; cada tabla se usa según backend/geocattle/mirror_tables.py.

-- Pulso del PC (una fila por instalación de campo). Se replica para medir frescura.
CREATE TABLE mirror_heartbeat (
  source text PRIMARY KEY CHECK (source ~ '^[a-z0-9-]{1,32}$'),
  at timestamptz NOT NULL,
  schema_version text NOT NULL,
  inbox_checked_at timestamptz,
  details jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Borradores de solicitudes. Se escriben en el PC (directo o por revisiones web) y se replican.
CREATE TABLE change_drafts (
  id uuid PRIMARY KEY,
  farm_id uuid NOT NULL REFERENCES farms ON DELETE CASCADE,
  author_id uuid NOT NULL REFERENCES users,
  action text NOT NULL CHECK (action IN ('animal_profile', 'health_record', 'health_schedule')),
  animal_id uuid REFERENCES animals,
  expected_version integer CHECK (expected_version > 0),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'discarded')),
  conflict_of uuid REFERENCES change_drafts,
  request_id uuid REFERENCES change_requests,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'submitted') = (request_id IS NOT NULL))
);
CREATE INDEX change_drafts_author ON change_drafts(farm_id, author_id, updated_at DESC);

-- Envíos hechos en la web espejo, pendientes de aplicar en el PC. Solo servidor.
CREATE TABLE mirror_outbox (
  id uuid PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('admin_order', 'remote_change', 'draft_revision')),
  actor_id uuid NOT NULL,
  farm_id uuid,
  method text NOT NULL CHECK (method IN ('POST', 'PUT', 'PATCH', 'DELETE')),
  path text NOT NULL CHECK (path ~ '^/api/'),
  body jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'delivered')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz
);
CREATE INDEX mirror_outbox_pending ON mirror_outbox(created_at) WHERE status IN ('queued', 'delivered');
CREATE INDEX mirror_outbox_actor ON mirror_outbox(actor_id, created_at DESC);

-- Resultado de cada envío aplicado en el PC. Se escribe en el PC y se replica: el
-- servidor deriva de aquí el estado final ("aplicada", "pendiente del dueño", "rechazada").
CREATE TABLE mirror_inbox_results (
  outbox_id uuid PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('admin_order', 'remote_change', 'draft_revision')),
  actor_id uuid NOT NULL,
  status text NOT NULL CHECK (status IN ('applied', 'pending_owner', 'rejected', 'conflict', 'failed')),
  http_status integer NOT NULL,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER mirror_inbox_results_immutable BEFORE UPDATE OR DELETE ON mirror_inbox_results
  FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation();

-- Contador anti-reuso de TOTP en el servidor (el del PC viaja en mfa_factors). Solo servidor.
CREATE TABLE mirror_totp_use (
  factor_id uuid PRIMARY KEY,
  last_counter bigint NOT NULL,
  used_at timestamptz NOT NULL DEFAULT now()
);

-- Auditoría de lo que ocurre solo en la web espejo (accesos, envíos). Solo servidor.
CREATE TABLE mirror_audit_log (
  id uuid PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  actor_id uuid,
  farm_id uuid,
  action text NOT NULL,
  object_type text NOT NULL,
  object_id text,
  after jsonb
);
CREATE INDEX mirror_audit_log_at ON mirror_audit_log(at DESC);
CREATE TRIGGER mirror_audit_log_immutable BEFORE UPDATE OR DELETE ON mirror_audit_log
  FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation();

-- Avisos marcados como leídos en la web, sin tocar notifications replicadas. Solo servidor.
CREATE TABLE mirror_notification_reads (
  notification_id uuid NOT NULL,
  user_id uuid NOT NULL,
  read_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (notification_id, user_id)
);
