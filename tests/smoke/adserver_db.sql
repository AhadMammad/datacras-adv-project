-- Generated smoke test for adserver_db. Runs in one transaction and rolls back.
\set ON_ERROR_STOP on
BEGIN;

INSERT INTO performance.attribution_model (attribution_model_status, model_code, model_name)
VALUES ('active', 'smoke attribution_model.model_code', 'smoke attribution_model.model_name');
INSERT INTO performance.conversion_event (conversion_status, conversion_timestamp)
VALUES ('confirmed', '2026-10-15 12:00:00+00');
INSERT INTO performance.performance_kpi_target (target_name, target_status)
VALUES ('smoke performance_kpi_target.target_name', 'draft');
INSERT INTO performance.tracking_pixel (deployment_status, pixel_code, pixel_name)
VALUES ('active', 'smoke tracking_pixel.pixel_code', 'smoke tracking_pixel.pixel_name');
INSERT INTO performance.click_event (impression_event_id, click_timestamp)
VALUES (uuidv7(), '2026-10-15 12:00:00+00');
INSERT INTO performance.delivery_pacing (campaign_id, line_item_id, measurement_timestamp, pacing_period_end, pacing_period_start, pacing_status)
VALUES (uuidv7(), uuidv7(), '2026-10-15 12:00:00+00', '2026-10-15 12:00:00+00', '2026-10-15 12:00:00+00', 'on_pace');
INSERT INTO performance.impression_event (campaign_id, media_placement_id, impression_timestamp)
VALUES (uuidv7(), uuidv7(), '2026-10-15 12:00:00+00');
INSERT INTO performance.video_completion_event (event_timestamp)
VALUES ('2026-10-15 12:00:00+00');
INSERT INTO performance.viewability_measurement (measurement_date, measurement_timestamp)
VALUES ('2026-10-15', '2026-10-15 12:00:00+00');

DO $$ BEGIN
    IF (SELECT count(*) FROM performance.attribution_model) <> 1 OR (SELECT count(*) FROM performance.conversion_event) <> 1 OR (SELECT count(*) FROM performance.performance_kpi_target) <> 1 OR (SELECT count(*) FROM performance.tracking_pixel) <> 1 OR (SELECT count(*) FROM performance.click_event) <> 1 OR (SELECT count(*) FROM performance.delivery_pacing) <> 1 OR (SELECT count(*) FROM performance.impression_event) <> 1 OR (SELECT count(*) FROM performance.video_completion_event) <> 1 OR (SELECT count(*) FROM performance.viewability_measurement) <> 1 THEN
        RAISE EXCEPTION 'smoke: expected exactly one row per table';
    END IF;
END $$;

-- audit trigger: updated_* maintained, created_* immutable
SET LOCAL app.actor = 'smoke_user';
UPDATE performance.attribution_model SET created_by = 'tamper', updated_by = 'tamper';
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM performance.attribution_model
                   WHERE updated_at > created_at AND updated_by = 'smoke_user' AND created_by <> 'tamper') THEN
        RAISE EXCEPTION 'smoke: audit trigger failed on performance.attribution_model';
    END IF;
END $$;

-- expect foreign_key_violation: code set FK on performance.performance_kpi_target.kpi_type
DO $$ BEGIN
    UPDATE performance.performance_kpi_target SET kpi_type = '__invalid__';
    RAISE EXCEPTION 'smoke: code set FK on performance.performance_kpi_target.kpi_type not enforced';
EXCEPTION WHEN foreign_key_violation THEN NULL;
END $$;

-- expect check_violation: CHECK on performance.attribution_model.attribution_model_status
DO $$ BEGIN
    UPDATE performance.attribution_model SET attribution_model_status = '__invalid__';
    RAISE EXCEPTION 'smoke: CHECK on performance.attribution_model.attribution_model_status not enforced';
EXCEPTION WHEN check_violation THEN NULL;
END $$;

DO $$ BEGIN
    IF (SELECT tableoid::regclass::text FROM performance.conversion_event) <> 'performance.conversion_event_p202610' THEN
        RAISE EXCEPTION 'smoke: performance.conversion_event row not routed to monthly partition';
    END IF;
END $$;

DO $$ BEGIN
    IF (SELECT tableoid::regclass::text FROM performance.click_event) <> 'performance.click_event_p202610' THEN
        RAISE EXCEPTION 'smoke: performance.click_event row not routed to monthly partition';
    END IF;
END $$;

DO $$ BEGIN
    IF (SELECT tableoid::regclass::text FROM performance.delivery_pacing) <> 'performance.delivery_pacing_p202610' THEN
        RAISE EXCEPTION 'smoke: performance.delivery_pacing row not routed to monthly partition';
    END IF;
END $$;

DO $$ BEGIN
    IF (SELECT tableoid::regclass::text FROM performance.impression_event) <> 'performance.impression_event_p202610' THEN
        RAISE EXCEPTION 'smoke: performance.impression_event row not routed to monthly partition';
    END IF;
END $$;

DO $$ BEGIN
    IF (SELECT tableoid::regclass::text FROM performance.video_completion_event) <> 'performance.video_completion_event_p202610' THEN
        RAISE EXCEPTION 'smoke: performance.video_completion_event row not routed to monthly partition';
    END IF;
END $$;

DO $$ BEGIN
    IF (SELECT tableoid::regclass::text FROM performance.viewability_measurement) <> 'performance.viewability_measurement_p202610' THEN
        RAISE EXCEPTION 'smoke: performance.viewability_measurement row not routed to monthly partition';
    END IF;
END $$;

ROLLBACK;
