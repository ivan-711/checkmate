"""Q13: the parallel evaluation sweep (ADR-012).

A sweep is a set of manifests: seeds x scorer versions x tiers. ``manifest`` freezes and hashes that set,
``evaluate`` runs the unchanged harness for one entry, ``executors`` runs the entries on a local process
pool (the fallback and the reference) or on Modal (``modal_app``, imported lazily), ``results`` reduces the
entries to one table with each metric's mean and 95% interval across seeds. ``python -m eval.sweep`` ties
them together. Thresholds, ``eval/expectations`` and the harness's numbers are untouched.
"""
