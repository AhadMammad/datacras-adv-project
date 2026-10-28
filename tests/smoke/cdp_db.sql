-- Generated smoke test for cdp_db. Runs in one transaction and rolls back.
\set ON_ERROR_STOP on
BEGIN;

INSERT INTO audience.segment (audience_segment_name, audience_segment_status)
VALUES ('smoke segment.audience_segment_name', 'active');
INSERT INTO audience.demographic_profile (profile_code, profile_name)
VALUES ('smoke demographic_profile.profile_code', 'smoke demographic_profile.profile_name');
INSERT INTO audience.persona (persona_code, persona_name, persona_status)
VALUES ('AAA', 'smoke persona.persona_name', 'active');
INSERT INTO audience.taxonomy (category_name, taxonomy_code)
VALUES ('smoke taxonomy.category_name', 'AA');
INSERT INTO audience.activation (activation_status)
VALUES ('Pending');
INSERT INTO audience.lookalike_model (model_name, model_status)
VALUES ('smoke lookalike_model.model_name', 'draft');
INSERT INTO audience.suppression_list (list_code, list_name, list_status)
VALUES ('smoke suppression_list.list_code', 'smoke suppression_list.list_name', 'active');
INSERT INTO audience.behavioral_profile (primary_behavioral_audience_segment_id, profile_name, profile_status)
VALUES ((SELECT segment_id FROM audience.segment LIMIT 1), 'smoke behavioral_profile.profile_name', 'active');
INSERT INTO audience.segment_membership (segment_id, audience_identifier, identifier_type, membership_status)
VALUES ((SELECT segment_id FROM audience.segment LIMIT 1), 'smoke segment_membership.audience_identifier', 'cookie_id', 'active');

DO $$ BEGIN
    IF (SELECT count(*) FROM audience.behavioral_profile) <> 1 OR (SELECT count(*) FROM audience.demographic_profile) <> 1 OR (SELECT count(*) FROM audience.persona) <> 1 OR (SELECT count(*) FROM audience.segment) <> 1 OR (SELECT count(*) FROM audience.taxonomy) <> 1 OR (SELECT count(*) FROM audience.activation) <> 1 OR (SELECT count(*) FROM audience.lookalike_model) <> 1 OR (SELECT count(*) FROM audience.segment_membership) <> 1 OR (SELECT count(*) FROM audience.suppression_list) <> 1 THEN
        RAISE EXCEPTION 'smoke: expected exactly one row per table';
    END IF;
END $$;

-- audit trigger: updated_* maintained, created_* immutable
SET LOCAL app.actor = 'smoke_user';
UPDATE audience.behavioral_profile SET created_by = 'tamper', updated_by = 'tamper';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM audience.behavioral_profile
                   WHERE updated_at > created_at AND updated_by = 'smoke_user' AND created_by <> 'tamper') THEN
        RAISE EXCEPTION 'smoke: audit trigger failed on audience.behavioral_profile';
    END IF;
END $$;

-- expect foreign_key_violation: code set FK on audience.demographic_profile.employment_category
DO $$ BEGIN
    UPDATE audience.demographic_profile SET employment_category = '__invalid__';
    RAISE EXCEPTION 'smoke: code set FK on audience.demographic_profile.employment_category not enforced';
EXCEPTION WHEN foreign_key_violation THEN NULL;
END $$;

-- expect check_violation: CHECK on audience.behavioral_profile.consent_status
DO $$ BEGIN
    UPDATE audience.behavioral_profile SET consent_status = '__invalid__';
    RAISE EXCEPTION 'smoke: CHECK on audience.behavioral_profile.consent_status not enforced';
EXCEPTION WHEN check_violation THEN NULL;
END $$;

ROLLBACK;
