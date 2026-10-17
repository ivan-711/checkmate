"""Frozen version strings, timeouts and limits. Named constants; never magic numbers."""

CONTRACT_VERSION = "contracts-v1"
API_PREFIX = "/api/v1"

POLICY_VERSION = "frontdesk-gate/1"
TOOL_SCHEMA_VERSION = "fd-tools/1"
RULE_ID = "BL-AMOX-01"
RULE_VERSION = "v1"

# FrontDesk agent loop (ADR-016 §8, architecture §22.2)
MODEL_TIMEOUT_MS = 8_000          # per model call
TURN_BUDGET_S = 25                # per typed turn
TURN_LEASE_S = 40                 # IN_PROGRESS older than this is marked FAILED
MAX_TOOL_CALLS_PER_TURN = 6
MAX_TURNS_PER_SESSION = 12
MAX_IDENTICAL_CALLS_PER_SESSION = 3
MAX_USER_TEXT_CHARS = 500
MAX_CANDIDATES_IN_TOOL_CALL_RECORD = 10
MAX_DEGRADED_TURNS_BEFORE_TEMPLATE = 2
AUTO_MODE_PROBE_S = 1.5
REPLAY_PACING_CAP_MS = 2_000

# Lists (architecture §5 bounded lists)
LIST_LIMIT_DEFAULT = 50
LIST_LIMIT_MAX = 200
MATCH_RUN_QUEUED_PAIR_IDS_MAX = 50
TOP_CONTRIBUTIONS_IN_LIST_VIEWS = 10

# Matching (architecture §3)
BLOCK_MAX_RECORDS = 100           # oversized blocks skipped in match runs and eval, never in the gate
WHAT_IF_P95_MS = 300

# Database (architecture §2)
POOL_SIZE = 10
POOL_MAX_OVERFLOW = 5
POOL_TIMEOUT_S = 5
STATEMENT_TIMEOUT_S = 5

# Fixture labels decided by the team lead at the contracts hour
REGISTRAR_LABELS = ("Registrar A", "Registrar B", "Registrar C")
