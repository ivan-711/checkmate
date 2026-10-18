"""Retry timing shared by the loop and the adapters (ADR-016 §8, v0.5.1 note a).

The loop makes exactly one retry, after ``RETRY_DELAY_S``, and only for a retryable ``ErrorStep``.
A 429 is retryable only when its ``Retry-After`` fits inside that delay: the pinned ``ErrorStep``
carries no wait time, so a longer ``Retry-After`` cannot be honoured and the turn degrades instead.
"""

RETRY_DELAY_S = 1.0
RETRY_AFTER_MAX_S = RETRY_DELAY_S
