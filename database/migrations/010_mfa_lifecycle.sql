ALTER TABLE users ADD COLUMN mfa_enrollment_required boolean NOT NULL DEFAULT false;

ALTER TABLE auth_challenges ADD COLUMN factor_id uuid REFERENCES mfa_factors(id);
ALTER TABLE auth_challenges DROP CONSTRAINT auth_challenges_purpose_check;
ALTER TABLE auth_challenges ADD CONSTRAINT auth_challenges_purpose_check
  CHECK (purpose IN ('login','step_up','mfa_setup','mfa_replace','verify_email','reset_password','close_account'));

-- Los desafíos existentes no identifican el factor para el que fueron emitidos.
UPDATE auth_challenges SET consumed_at=now()
WHERE purpose IN ('login','mfa_setup') AND consumed_at IS NULL;
