CREATE TABLE invitation_mail (
    invitation_id uuid NOT NULL REFERENCES invitations(id),
    kind text NOT NULL CHECK (kind IN ('invitation', 'accepted')),
    recipient text NOT NULL,
    encrypted_token bytea,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed', 'expired', 'cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    PRIMARY KEY (invitation_id, kind),
    CHECK ((kind = 'invitation' AND status = 'pending') = (encrypted_token IS NOT NULL)),
    CHECK ((status = 'sent') = (sent_at IS NOT NULL))
);

CREATE INDEX invitation_mail_due ON invitation_mail(next_attempt_at, invitation_id)
WHERE status = 'pending';
