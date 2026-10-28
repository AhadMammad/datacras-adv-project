-- Generated smoke test for media_ops_db. Runs in one transaction and rolls back.
\set ON_ERROR_STOP on
BEGIN;

INSERT INTO campaign.campaign (campaign_code, campaign_name, campaign_status, start_date)
VALUES ('smoke campaign.campaign_code', 'smoke campaign.campaign_name', 'draft', '2026-10-15');
INSERT INTO campaign.campaign_kpi_target (target_status)
VALUES ('draft');
INSERT INTO campaign.targeting_rule (rule_name)
VALUES ('smoke targeting_rule.rule_name');
INSERT INTO campaign.creative_assignment (trafficking_status)
VALUES ('smoke creative_assignment.trafficking_status');
INSERT INTO media.ad_channel (channel_code, channel_name, channel_status)
VALUES ('AA', 'smoke ad_channel.channel_name', 'active');
INSERT INTO media.ad_format (format_code, format_name, format_status)
VALUES ('AAA', 'smoke ad_format.format_name', 'active');
INSERT INTO media.placement (placement_code, placement_name, placement_status)
VALUES ('smoke placement.placement_code', 'smoke placement.placement_name', 'active');
INSERT INTO media.publisher_property (property_code, property_name, property_status)
VALUES ('smoke publisher_property.property_code', 'smoke publisher_property.property_name', 'active');
INSERT INTO vendor.accreditation (accreditation_status, certification_name)
VALUES ('active', 'smoke accreditation.certification_name');
INSERT INTO vendor.publisher (publisher_type)
VALUES ('digital');
INSERT INTO vendor.supplier (legal_name, onboarding_status)
VALUES ('smoke supplier.legal_name', 'prospect');
INSERT INTO vendor.tech_partner (platform_type)
VALUES ((SELECT code FROM ref.platform_type ORDER BY sort_order LIMIT 1));
INSERT INTO vendor.vendor_rate_card (rate_card_name, rate_card_number, rate_card_status, version)
VALUES ('smoke vendor_rate_card.rate_card_name', 'RC-AAAA', 'draft', 'v0.0');
INSERT INTO campaign.budget_allocation (campaign_id, allocation_status)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), 'draft');
INSERT INTO campaign.flight (campaign_id, end_date, flight_code, flight_name, flight_status, start_date)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), '2026-10-15', 'smoke flight.flight_code', 'smoke flight.flight_name', 'draft', '2026-10-15');
INSERT INTO campaign.pacing_rule (campaign_id, pacing_status, rule_name)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), 'active', 'smoke pacing_rule.rule_name');
INSERT INTO campaign.trafficking_order (campaign_id, trafficking_order_number, trafficking_status)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), 'TO-00000000', (SELECT code FROM ref.trafficking_status ORDER BY sort_order LIMIT 1));
INSERT INTO media.plan (campaign_id, plan_name, plan_number, plan_status)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), 'smoke plan.plan_name', 'MP-0000-000000', (SELECT code FROM ref.plan_status ORDER BY sort_order LIMIT 1));
INSERT INTO media.schedule (campaign_id, schedule_name, schedule_number)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), 'smoke schedule.schedule_name', 'smoke schedule.schedule_number');
INSERT INTO media.programmatic_deal (campaign_id, deal_code, deal_name, deal_status)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), 'smoke programmatic_deal.deal_code', 'smoke programmatic_deal.deal_name', 'draft');
INSERT INTO media.trafficking_instruction (campaign_id, instruction_number, instruction_status)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), 'smoke trafficking_instruction.instruction_number', 'pending');
INSERT INTO campaign.line_item (campaign_id, flight_id, delivery_status, end_date, line_item_code, line_item_name, start_date)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), (SELECT flight_id FROM campaign.flight LIMIT 1), (SELECT code FROM ref.delivery_status ORDER BY sort_order LIMIT 1), '2026-10-15', 'smoke line_item.line_item_code', 'smoke line_item.line_item_name', '2026-10-15');
INSERT INTO media.plan_line (plan_id, buying_status, line_name, line_number)
VALUES ((SELECT plan_id FROM media.plan LIMIT 1), (SELECT code FROM ref.buying_status ORDER BY sort_order LIMIT 1), 'smoke plan_line.line_name', 1);
INSERT INTO media.media_insertion_order (plan_id, io_name, io_number, io_status, version_number)
VALUES ((SELECT plan_id FROM media.plan LIMIT 1), 'smoke media_insertion_order.io_name', 'IO-000000', 'draft', 1);
INSERT INTO campaign.ad (campaign_id, line_item_id, ad_name, ad_status)
VALUES ((SELECT campaign_id FROM campaign.campaign LIMIT 1), (SELECT line_item_id FROM campaign.line_item LIMIT 1), 'smoke ad.ad_name', (SELECT code FROM ref.ad_status ORDER BY sort_order LIMIT 1));
INSERT INTO media.media_placement (media_insertion_order_id, placement_code, placement_name, placement_status)
VALUES ((SELECT media_insertion_order_id FROM media.media_insertion_order LIMIT 1), 'smoke media_placement.placement_code', 'smoke media_placement.placement_name', 'active');
INSERT INTO media.buy (media_placement_id, plan_line_id, buy_number, buy_status)
VALUES ((SELECT media_placement_id FROM media.media_placement LIMIT 1), (SELECT plan_line_id FROM media.plan_line LIMIT 1), 'smoke buy.buy_number', 'pending');

DO $$ BEGIN
    IF (SELECT count(*) FROM campaign.budget_allocation) <> 1 OR (SELECT count(*) FROM campaign.campaign) <> 1 OR (SELECT count(*) FROM campaign.campaign_kpi_target) <> 1 OR (SELECT count(*) FROM campaign.flight) <> 1 OR (SELECT count(*) FROM campaign.pacing_rule) <> 1 OR (SELECT count(*) FROM campaign.targeting_rule) <> 1 OR (SELECT count(*) FROM campaign.ad) <> 1 OR (SELECT count(*) FROM campaign.creative_assignment) <> 1 OR (SELECT count(*) FROM campaign.line_item) <> 1 OR (SELECT count(*) FROM campaign.trafficking_order) <> 1 OR (SELECT count(*) FROM media.media_placement) <> 1 OR (SELECT count(*) FROM media.plan) <> 1 OR (SELECT count(*) FROM media.plan_line) <> 1 OR (SELECT count(*) FROM media.schedule) <> 1 OR (SELECT count(*) FROM media.buy) <> 1 OR (SELECT count(*) FROM media.media_insertion_order) <> 1 OR (SELECT count(*) FROM media.programmatic_deal) <> 1 OR (SELECT count(*) FROM media.trafficking_instruction) <> 1 OR (SELECT count(*) FROM media.ad_channel) <> 1 OR (SELECT count(*) FROM media.ad_format) <> 1 OR (SELECT count(*) FROM media.placement) <> 1 OR (SELECT count(*) FROM media.publisher_property) <> 1 OR (SELECT count(*) FROM vendor.accreditation) <> 1 OR (SELECT count(*) FROM vendor.publisher) <> 1 OR (SELECT count(*) FROM vendor.supplier) <> 1 OR (SELECT count(*) FROM vendor.tech_partner) <> 1 OR (SELECT count(*) FROM vendor.vendor_rate_card) <> 1 THEN
        RAISE EXCEPTION 'smoke: expected exactly one row per table';
    END IF;
END $$;

-- audit trigger: updated_* maintained, created_* immutable
SET LOCAL app.actor = 'smoke_user';
UPDATE campaign.budget_allocation SET created_by = 'tamper', updated_by = 'tamper';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM campaign.budget_allocation
                   WHERE updated_at > created_at AND updated_by = 'smoke_user' AND created_by <> 'tamper') THEN
        RAISE EXCEPTION 'smoke: audit trigger failed on campaign.budget_allocation';
    END IF;
END $$;

-- expect foreign_key_violation: code set FK on campaign.budget_allocation.channel_type
DO $$ BEGIN
    UPDATE campaign.budget_allocation SET channel_type = '__invalid__';
    RAISE EXCEPTION 'smoke: code set FK on campaign.budget_allocation.channel_type not enforced';
EXCEPTION WHEN foreign_key_violation THEN NULL;
END $$;

-- expect check_violation: CHECK on campaign.budget_allocation.allocation_method
DO $$ BEGIN
    UPDATE campaign.budget_allocation SET allocation_method = '__invalid__';
    RAISE EXCEPTION 'smoke: CHECK on campaign.budget_allocation.allocation_method not enforced';
EXCEPTION WHEN check_violation THEN NULL;
END $$;

ROLLBACK;
