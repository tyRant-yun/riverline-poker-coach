"""Test isolation: never let a local .env or user shell environment change
AppConfig-derived behavior under pytest.

``poker_coach.api.app`` loads the repository-root ``.env`` at import time.
This conftest runs before any test module imports the app, and blanks every
environment variable that ``AppConfig.from_environment`` reads, so tests are
hermetic regardless of the developer's local ``.env``. Existing variables are
set to an empty string (not removed) so ``load_dotenv(override=False)`` will
not re-populate them from ``.env``.

``POKER_COACH_TEST_PG_URL`` is intentionally left alone: the live
PostgreSQL regression reads it directly and must honor the shell value.
"""

from __future__ import annotations

import os

_APP_CONFIG_VARS = (
    "POKER_COACH_APP_VERSION",
    "POKER_COACH_ANALYSIS_VERSION",
    "POKER_COACH_DB_PATH",
    "POKER_COACH_DATABASE_URL",
    "POKER_COACH_REDIS_URL",
    "POKER_COACH_REDIS_WORKER_IN_PROCESS",
    "POKER_COACH_LLM_BASE_URL",
    "POKER_COACH_LLM_API_KEY",
    "POKER_COACH_LLM_MODEL",
    "POKER_COACH_LLM_TIMEOUT_SECONDS",
    "POKER_COACH_MAX_REQUEST_BYTES",
    "POKER_COACH_MAX_TIMEOUT_SECONDS",
    "POKER_COACH_RATE_LIMIT_PER_MINUTE",
    "POKER_COACH_STORE_USER_TEXT",
)

for _name in _APP_CONFIG_VARS:
    os.environ[_name] = ""

# The live-PostgreSQL regression reads POKER_COACH_TEST_PG_URL directly and
# must honor an explicit shell value. But without an explicit shell value the
# repository .env would populate it (via load_dotenv) and the live tests would
# hang trying to reach a database that is not running. Blank it unless the
# shell explicitly set it.
if "POKER_COACH_TEST_PG_URL" not in os.environ:
    os.environ["POKER_COACH_TEST_PG_URL"] = ""
