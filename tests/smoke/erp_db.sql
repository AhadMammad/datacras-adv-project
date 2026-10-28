-- Generated smoke test for erp_db. Runs in one transaction and rolls back.
\set ON_ERROR_STOP on
BEGIN;

INSERT INTO vendor.invoice (invoice_status, vendor_reference_number)
VALUES ('received', 'smoke invoice.vendor_reference_number');
INSERT INTO vendor.io_line (vendor_io_media_insertion_order_id, line_number, line_status)
VALUES (uuidv7(), 1, (SELECT code FROM ref.line_status ORDER BY sort_order LIMIT 1));
INSERT INTO vendor.performance_evaluation (evaluation_number, evaluation_status)
VALUES ('VPE-0000-000000', 'draft');
INSERT INTO vendor.reconciliation (reconciliation_number, reconciliation_status)
VALUES ('REC-0000-000000', 'draft');
INSERT INTO finance.finance_budget (budget_name, budget_number)
VALUES ('smoke finance_budget.budget_name', 'AAAAAA');
INSERT INTO finance.cost_center (cost_center_code, cost_center_name, cost_center_status)
VALUES ('AAAA', 'smoke cost_center.cost_center_name', 'active');
INSERT INTO finance.gl_account (account_code, account_name, company_code, gl_account_status)
VALUES ('0000', 'smoke gl_account.account_name', 'AAAA', 'active');
INSERT INTO finance.client_invoice (invoice_number, invoice_status)
VALUES ('INV-00000000', (SELECT code FROM ref.invoice_status ORDER BY sort_order LIMIT 1));
INSERT INTO finance.media_cost_reconciliation (reconciliation_document_number, reconciliation_status)
VALUES ('REC-AAAAAAAA', 'open');
INSERT INTO finance.payment (payment_status, reference_number)
VALUES ('pending', 'AAAAAAAA');
INSERT INTO finance.revenue_recognition (recognition_status)
VALUES ('pending');
INSERT INTO finance.vendor_payable (payable_document_number, payment_status)
VALUES ('AAAAAAAA', 'open');
INSERT INTO finance.budget_line (finance_budget_id, line_number)
VALUES ((SELECT finance_budget_id FROM finance.finance_budget LIMIT 1), 1);
INSERT INTO finance.invoice_line (client_invoice_id, billing_status, line_number)
VALUES ((SELECT client_invoice_id FROM finance.client_invoice LIMIT 1), (SELECT code FROM ref.billing_status ORDER BY sort_order LIMIT 1), 1);

DO $$ BEGIN
    IF (SELECT count(*) FROM vendor.invoice) <> 1 OR (SELECT count(*) FROM vendor.io_line) <> 1 OR (SELECT count(*) FROM vendor.performance_evaluation) <> 1 OR (SELECT count(*) FROM vendor.reconciliation) <> 1 OR (SELECT count(*) FROM finance.budget_line) <> 1 OR (SELECT count(*) FROM finance.cost_center) <> 1 OR (SELECT count(*) FROM finance.finance_budget) <> 1 OR (SELECT count(*) FROM finance.gl_account) <> 1 OR (SELECT count(*) FROM finance.client_invoice) <> 1 OR (SELECT count(*) FROM finance.invoice_line) <> 1 OR (SELECT count(*) FROM finance.media_cost_reconciliation) <> 1 OR (SELECT count(*) FROM finance.payment) <> 1 OR (SELECT count(*) FROM finance.revenue_recognition) <> 1 OR (SELECT count(*) FROM finance.vendor_payable) <> 1 THEN
        RAISE EXCEPTION 'smoke: expected exactly one row per table';
    END IF;
END $$;

-- audit trigger: updated_* maintained, created_* immutable
SET LOCAL app.actor = 'smoke_user';
UPDATE vendor.invoice SET created_by = 'tamper', updated_by = 'tamper';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM vendor.invoice
                   WHERE updated_at > created_at AND updated_by = 'smoke_user' AND created_by <> 'tamper') THEN
        RAISE EXCEPTION 'smoke: audit trigger failed on vendor.invoice';
    END IF;
END $$;

-- expect foreign_key_violation: code set FK on vendor.invoice.delivery_data_source
DO $$ BEGIN
    UPDATE vendor.invoice SET delivery_data_source = '__invalid__';
    RAISE EXCEPTION 'smoke: code set FK on vendor.invoice.delivery_data_source not enforced';
EXCEPTION WHEN foreign_key_violation THEN NULL;
END $$;

-- expect check_violation: CHECK on vendor.invoice.invoice_status
DO $$ BEGIN
    UPDATE vendor.invoice SET invoice_status = '__invalid__';
    RAISE EXCEPTION 'smoke: CHECK on vendor.invoice.invoice_status not enforced';
EXCEPTION WHEN check_violation THEN NULL;
END $$;

ROLLBACK;
