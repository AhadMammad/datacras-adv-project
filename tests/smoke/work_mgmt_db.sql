-- Generated smoke test for work_mgmt_db. Runs in one transaction and rolls back.
\set ON_ERROR_STOP on
BEGIN;

INSERT INTO creative.brand_guideline (effective_date, guideline_status, guideline_version)
VALUES ('2026-10-15', 'draft', 'smoke brand_guideline.guideline_version');
INSERT INTO creative.concept (concept_code, concept_status, title)
VALUES ('smoke concept.concept_code', (SELECT code FROM ref.concept_status ORDER BY sort_order LIMIT 1), 'smoke concept.title');
INSERT INTO creative.creative_brief (brand_id, campaign_id, brief_name, brief_number, creative_brief_status)
VALUES (uuidv7(), uuidv7(), 'smoke creative_brief.brief_name', 'CB-000000', 'draft');
INSERT INTO creative.spec (spec_code, spec_name, spec_status)
VALUES ('smoke spec.spec_code', 'smoke spec.spec_name', 'active');
INSERT INTO creative.asset (asset_name, asset_type, dam_asset_ref)
VALUES ('smoke asset.asset_name', (SELECT code FROM ref.asset_type ORDER BY sort_order LIMIT 1), 'smoke asset.dam_asset_ref');
INSERT INTO creative.creative_deliverable (deliverable_code, deliverable_name, deliverable_status)
VALUES ('smoke creative_deliverable.deliverable_code', 'smoke creative_deliverable.deliverable_name', (SELECT code FROM ref.deliverable_status ORDER BY sort_order LIMIT 1));
INSERT INTO creative.production_job (job_name, job_number, job_status)
VALUES ('smoke production_job.job_name', 'AA-000000', (SELECT code FROM ref.job_status ORDER BY sort_order LIMIT 1));
INSERT INTO project.initiative (initiative_name, initiative_status, project_code)
VALUES ('smoke initiative.initiative_name', 'briefing', 'AAAAAA');
INSERT INTO project.project_brief (campaign_id, brief_status, title)
VALUES (uuidv7(), 'draft', 'smoke project_brief.title');
INSERT INTO project.resource_plan (plan_status)
VALUES ('draft');
INSERT INTO creative.asset_version (asset_id, version_number, version_status)
VALUES ((SELECT asset_id FROM creative.asset LIMIT 1), 1, 'draft');
INSERT INTO project.deliverable_tracker (initiative_id, deliverable_name, deliverable_status)
VALUES ((SELECT initiative_id FROM project.initiative LIMIT 1), 'smoke deliverable_tracker.deliverable_name', (SELECT code FROM ref.deliverable_status ORDER BY sort_order LIMIT 1));
INSERT INTO project.project_budget (initiative_id, budget_status, currency_code, total_approved_budget)
VALUES ((SELECT initiative_id FROM project.initiative LIMIT 1), 'draft', 'AAA', 1);
INSERT INTO project.work_package (initiative_id, wbs_code, work_package_name, work_package_status)
VALUES ((SELECT initiative_id FROM project.initiative LIMIT 1), 'A', 'smoke work_package.work_package_name', 'not_started');
INSERT INTO creative.proof (asset_version_id, proof_name, proof_number, proof_status)
VALUES ((SELECT asset_version_id FROM creative.asset_version LIMIT 1), 'smoke proof.proof_name', 'PRF-00000000', (SELECT code FROM ref.proof_status ORDER BY sort_order LIMIT 1));
INSERT INTO project.task (work_package_id, task_name, task_status)
VALUES ((SELECT work_package_id FROM project.work_package LIMIT 1), 'smoke task.task_name', 'not_started');
INSERT INTO project.milestone (initiative_id, work_package_id, milestone_name, project_milestone_status)
VALUES ((SELECT initiative_id FROM project.initiative LIMIT 1), (SELECT work_package_id FROM project.work_package LIMIT 1), 'smoke milestone.milestone_name', 'upcoming');
INSERT INTO project.assignment (initiative_id, task_id, assignment_status)
VALUES ((SELECT initiative_id FROM project.initiative LIMIT 1), (SELECT task_id FROM project.task LIMIT 1), 'active');
INSERT INTO project.time_entry (task_id, approval_status, entry_date, hours_logged)
VALUES ((SELECT task_id FROM project.task LIMIT 1), 'draft', '2026-10-15', 1);

DO $$ BEGIN
    IF (SELECT count(*) FROM creative.brand_guideline) <> 1 OR (SELECT count(*) FROM creative.concept) <> 1 OR (SELECT count(*) FROM creative.creative_brief) <> 1 OR (SELECT count(*) FROM creative.spec) <> 1 OR (SELECT count(*) FROM creative.asset) <> 1 OR (SELECT count(*) FROM creative.asset_version) <> 1 OR (SELECT count(*) FROM creative.creative_deliverable) <> 1 OR (SELECT count(*) FROM creative.production_job) <> 1 OR (SELECT count(*) FROM creative.proof) <> 1 OR (SELECT count(*) FROM project.assignment) <> 1 OR (SELECT count(*) FROM project.deliverable_tracker) <> 1 OR (SELECT count(*) FROM project.task) <> 1 OR (SELECT count(*) FROM project.time_entry) <> 1 OR (SELECT count(*) FROM project.initiative) <> 1 OR (SELECT count(*) FROM project.milestone) <> 1 OR (SELECT count(*) FROM project.project_brief) <> 1 OR (SELECT count(*) FROM project.project_budget) <> 1 OR (SELECT count(*) FROM project.resource_plan) <> 1 OR (SELECT count(*) FROM project.work_package) <> 1 THEN
        RAISE EXCEPTION 'smoke: expected exactly one row per table';
    END IF;
END $$;

-- audit trigger: updated_* maintained, created_* immutable
SET LOCAL app.actor = 'smoke_user';
UPDATE creative.brand_guideline SET created_by = 'tamper', updated_by = 'tamper';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM creative.brand_guideline
                   WHERE updated_at > created_at AND updated_by = 'smoke_user' AND created_by <> 'tamper') THEN
        RAISE EXCEPTION 'smoke: audit trigger failed on creative.brand_guideline';
    END IF;
END $$;

-- expect foreign_key_violation: code set FK on creative.concept.approval_status
DO $$ BEGIN
    UPDATE creative.concept SET approval_status = '__invalid__';
    RAISE EXCEPTION 'smoke: code set FK on creative.concept.approval_status not enforced';
EXCEPTION WHEN foreign_key_violation THEN NULL;
END $$;

-- expect check_violation: CHECK on creative.brand_guideline.guideline_status
DO $$ BEGIN
    UPDATE creative.brand_guideline SET guideline_status = '__invalid__';
    RAISE EXCEPTION 'smoke: CHECK on creative.brand_guideline.guideline_status not enforced';
EXCEPTION WHEN check_violation THEN NULL;
END $$;

ROLLBACK;
