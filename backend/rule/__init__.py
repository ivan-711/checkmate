"""Rule BL-AMOX-01 (spec: evaluation/synthea-and-clinical-rule.md section 5; ADR-011).

A pure function of the entity members' parsed resources and the committed terminology
cache. No model call, no network call, no clock: the caller supplies the timestamp.
"""
