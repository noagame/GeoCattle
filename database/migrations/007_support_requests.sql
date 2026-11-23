CREATE TABLE support_requests (
  id uuid PRIMARY KEY,
  requester_id uuid NOT NULL REFERENCES users(id),
  kind text NOT NULL CHECK (kind IN ('close_account', 'change_email', 'access_issue')),
  description text NOT NULL CHECK (length(btrim(description)) BETWEEN 1 AND 2000),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved', 'rejected')),
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  resolved_by uuid REFERENCES users(id),
  response text CHECK (length(btrim(response)) BETWEEN 1 AND 2000),
  read_at timestamptz,
  CHECK (
    (status = 'pending' AND resolved_at IS NULL AND resolved_by IS NULL AND response IS NULL AND read_at IS NULL)
    OR (status IN ('resolved', 'rejected') AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL AND response IS NOT NULL)
  )
);

CREATE INDEX support_requests_requester_time ON support_requests(requester_id, created_at DESC, id);
CREATE INDEX support_requests_pending_time ON support_requests(created_at DESC, id) WHERE status = 'pending';

-- Preserva las referencias existentes y usa el motivo registrado más reciente para cada folio.
INSERT INTO support_requests(id, requester_id, kind, description, created_at)
SELECT t.id, t.user_id, 'close_account',
       coalesce(nullif(btrim(a.after->>'reason'), ''), 'Motivo sin registrar'), t.created_at
FROM account_tokens t
LEFT JOIN LATERAL (
  SELECT after FROM audit_log
  WHERE action = 'account_closure_requested' AND object_id = t.id::text AND actor_id = t.user_id
  ORDER BY at DESC, id DESC LIMIT 1
) a ON true
WHERE t.purpose = 'close_account' AND t.consumed_at IS NULL;
