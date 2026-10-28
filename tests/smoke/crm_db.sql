-- Generated smoke test for crm_db. Runs in one transaction and rolls back.
\set ON_ERROR_STOP on
BEGIN;

INSERT INTO client.account_team (assignment_code, assignment_status)
VALUES ('AT-AAAAAA', 'active');
INSERT INTO client.agency_relationship (relationship_code, relationship_status)
VALUES ('AAA', 'active');
INSERT INTO client.client_brief (brief_number, brief_status, title)
VALUES ('BRF-0000-000000', 'draft', 'smoke client_brief.title');
INSERT INTO client.revenue_target (target_code, target_name, target_status)
VALUES ('RT-AAAA', 'smoke revenue_target.target_name', (SELECT code FROM ref.target_status ORDER BY sort_order LIMIT 1));
INSERT INTO client.advertiser (account_status, legal_entity_name)
VALUES ('prospect', 'smoke advertiser.legal_entity_name');
INSERT INTO contract.agreement (agreement_number, agreement_status)
VALUES ('smoke agreement.agreement_number', (SELECT code FROM ref.agreement_status ORDER BY sort_order LIMIT 1));
INSERT INTO client.advertiser_hierarchy (parent_advertiser_id, effective_start_date, hierarchy_code, hierarchy_status)
VALUES ((SELECT advertiser_id FROM client.advertiser LIMIT 1), '2026-10-15', 'AH-AAAAAA', 'active');
INSERT INTO client.brand (primary_client_brand_advertiser_id, brand_code, brand_name, brand_status)
VALUES ((SELECT advertiser_id FROM client.advertiser LIMIT 1), 'AA', 'smoke brand.brand_name', 'active');
INSERT INTO contract.sow (sow_advertiser_id, sow_number, sow_status, title, version_number)
VALUES ((SELECT advertiser_id FROM client.advertiser LIMIT 1), 'SOW-AAAAAA', (SELECT code FROM ref.sow_status ORDER BY sort_order LIMIT 1), 'smoke sow.title', '0.0');
INSERT INTO contract.contract_insertion_order (campaign_id, master_service_agreement_id, io_name, io_number, io_status)
VALUES (uuidv7(), (SELECT agreement_id FROM contract.agreement LIMIT 1), 'smoke contract_insertion_order.io_name', 'IO-AAAAAA', (SELECT code FROM ref.io_status ORDER BY sort_order LIMIT 1));
INSERT INTO contract.contract_rate_card (agreement_id, contract_rate_card_status, rate_card_name, rate_card_number, version_number)
VALUES ((SELECT agreement_id FROM contract.agreement LIMIT 1), (SELECT code FROM ref.contract_rate_card_status ORDER BY sort_order LIMIT 1), 'smoke contract_rate_card.rate_card_name', 'RC-AAAAAA', '1.1');
INSERT INTO contract.amendment (agreement_id, amendment_number, amendment_status)
VALUES ((SELECT agreement_id FROM contract.agreement LIMIT 1), 'smoke amendment.amendment_number', 'draft');
INSERT INTO contract.renewal (agreement_id, renewal_number, renewal_status)
VALUES ((SELECT agreement_id FROM contract.agreement LIMIT 1), 'smoke renewal.renewal_number', (SELECT code FROM ref.renewal_status ORDER BY sort_order LIMIT 1));
INSERT INTO contract.sla (agreement_id, sla_code, sla_name, sla_status)
VALUES ((SELECT agreement_id FROM contract.agreement LIMIT 1), 'smoke sla.sla_code', 'smoke sla.sla_name', 'active');
INSERT INTO contract.term (agreement_id, clause_title)
VALUES ((SELECT agreement_id FROM contract.agreement LIMIT 1), 'smoke term.clause_title');
INSERT INTO contract.contract_deliverable (agreement_id, sow_id, contract_deliverable_status, deliverable_code, deliverable_name)
VALUES ((SELECT agreement_id FROM contract.agreement LIMIT 1), (SELECT sow_id FROM contract.sow LIMIT 1), (SELECT code FROM ref.contract_deliverable_status ORDER BY sort_order LIMIT 1), 'smoke contract_deliverable.deliverable_code', 'smoke contract_deliverable.deliverable_name');
INSERT INTO contract.rate_card_line (contract_rate_card_id, line_status)
VALUES ((SELECT contract_rate_card_id FROM contract.contract_rate_card LIMIT 1), 'draft');

DO $$ BEGIN
    IF (SELECT count(*) FROM client.account_team) <> 1 OR (SELECT count(*) FROM client.agency_relationship) <> 1 OR (SELECT count(*) FROM client.client_brief) <> 1 OR (SELECT count(*) FROM client.revenue_target) <> 1 OR (SELECT count(*) FROM client.advertiser) <> 1 OR (SELECT count(*) FROM client.advertiser_hierarchy) <> 1 OR (SELECT count(*) FROM client.brand) <> 1 OR (SELECT count(*) FROM contract.contract_deliverable) <> 1 OR (SELECT count(*) FROM contract.contract_insertion_order) <> 1 OR (SELECT count(*) FROM contract.contract_rate_card) <> 1 OR (SELECT count(*) FROM contract.rate_card_line) <> 1 OR (SELECT count(*) FROM contract.agreement) <> 1 OR (SELECT count(*) FROM contract.amendment) <> 1 OR (SELECT count(*) FROM contract.renewal) <> 1 OR (SELECT count(*) FROM contract.sla) <> 1 OR (SELECT count(*) FROM contract.sow) <> 1 OR (SELECT count(*) FROM contract.term) <> 1 THEN
        RAISE EXCEPTION 'smoke: expected exactly one row per table';
    END IF;
END $$;

-- audit trigger: updated_* maintained, created_* immutable
SET LOCAL app.actor = 'smoke_user';
UPDATE client.account_team SET created_by = 'tamper', updated_by = 'tamper';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM client.account_team
                   WHERE updated_at > created_at AND updated_by = 'smoke_user' AND created_by <> 'tamper') THEN
        RAISE EXCEPTION 'smoke: audit trigger failed on client.account_team';
    END IF;
END $$;

-- expect foreign_key_violation: code set FK on client.account_team.role
DO $$ BEGIN
    UPDATE client.account_team SET role = '__invalid__';
    RAISE EXCEPTION 'smoke: code set FK on client.account_team.role not enforced';
EXCEPTION WHEN foreign_key_violation THEN NULL;
END $$;

-- expect check_violation: CHECK on client.account_team.account_access_level
DO $$ BEGIN
    UPDATE client.account_team SET account_access_level = '__invalid__';
    RAISE EXCEPTION 'smoke: CHECK on client.account_team.account_access_level not enforced';
EXCEPTION WHEN check_violation THEN NULL;
END $$;

ROLLBACK;
