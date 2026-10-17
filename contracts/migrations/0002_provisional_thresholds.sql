-- Fork #12, decided by Ivan (option A): the provisional high cutoff follows the scorer's
-- hand-set design (backend.core.band DEMO_THRESHOLDS, c_high 4.0) instead of the 2.0 placeholder
-- seeded in 0001. A new current row is inserted; provisional-0 stays as history and is never edited
-- beyond losing the current flag. The harness-derived cutoffs replace this row before the 20:00 freeze,
-- again as a new row. Author: Christian Flores (lead session).
BEGIN;
UPDATE threshold_set SET is_current = false WHERE is_current AND thresholds_id = 'provisional-0';
INSERT INTO threshold_set (thresholds_id, c_low, c_high, auto_link_enabled, is_calibrated, is_current)
SELECT 'provisional-1', 0.0, 4.0, false, false, true
WHERE NOT EXISTS (SELECT 1 FROM threshold_set WHERE is_current);
COMMIT;
