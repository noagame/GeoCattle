ALTER TABLE mirror_outbox
  DROP CONSTRAINT mirror_outbox_kind_check,
  ADD CONSTRAINT mirror_outbox_kind_check
    CHECK (kind IN ('admin_order', 'remote_change', 'draft_revision', 'support_request'));

ALTER TABLE mirror_inbox_results
  DROP CONSTRAINT mirror_inbox_results_kind_check,
  ADD CONSTRAINT mirror_inbox_results_kind_check
    CHECK (kind IN ('admin_order', 'remote_change', 'draft_revision', 'support_request'));
