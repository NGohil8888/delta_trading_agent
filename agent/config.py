"""
agent/config.py -- every environment-derived constant, in one place.

IMPORTANT for anyone adding tests: every other module in this package reads
these values via `from agent import config; config.SOMETHING`, NOT via
`from agent.config import SOMETHING`. That distinction matters: patching
`config.WORKSPACE_DIR` with unittest.mock only actually changes behavior if
the code that uses it looks it up as `config.WORKSPACE_DIR` at call time.
`from agent.config import WORKSPACE_DIR` copies the value once at import
time into a new name, and patching config.WORKSPACE_DIR afterwards would
NOT affect that copy. Keep the qualified-access pattern everywhere.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

try:
    import ollama
except ImportError:  # pragma: no cover - dependency may be absent in some envs
    ollama = None

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

WORKSPACE_DIR = BASE_DIR / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)

# Module-level, patchable. Tests MUST patch this alongside WORKSPACE_DIR --
# previously this was recomputed inline as `BASE_DIR / "status.json"` in
# multiple places, which meant tests that only patched WORKSPACE_DIR
# silently wrote fake failure entries into the real project's status.json.
STATUS_FILE = BASE_DIR / "status.json"

# NOTE: the Ollama Python client appends "/api/chat" to the host, so the host
# must NOT already include "/api". A previous default of "https://ollama.com/api"
# caused every chat to 404 at "/api/api/chat". For local Ollama use
# OLLAMA_HOST=http://localhost:11434. For Ollama cloud use https://ollama.com.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com")
# Default cloud model. Override with OLLAMA_MODEL in .env to pin a specific tag.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "minimax-m3:cloud")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

DELTA_BASE_URL = os.getenv("DELTA_BASE_URL") or os.getenv("BASE_URL") or "https://cdn-ind.testnet.deltaex.org"
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
ACCOUNT_BALANCE = os.getenv("ACCOUNT_BALANCE", "")
BALANCE_OVERRIDE = os.getenv("BALANCE_OVERRIDE", "")

MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "5"))
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "0.01"))
# AGENTS.md: "Focus on high-probability setups only" / "If a trade does not
# have positive expected value, skip it." Ideas below this bar are blocked
# at confirm time regardless of who proposed them.
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.55"))
TESTNET_ONLY = os.getenv("TESTNET_ONLY", "true").lower() == "true"

# Autonomous mode: the agent scans/proposes/journals on its own timer,
# without waiting to be asked. Every file operation it performs is
# hard-scoped to workspace/ (see agent/workspace_tools.py) -- it can never
# read, write, or delete engine.py, dashboard.py, index.html, AGENTS.md,
# README.md, .env, or the test files, no matter what it decides to do. It
# also never calls trade confirmation -- proactive research and proactive
# trading are different things, and only the former is unattended here.
AUTONOMOUS_MODE = os.getenv("AUTONOMOUS_MODE", "false").lower() == "true"
AUTONOMOUS_INTERVAL_SECONDS = int(os.getenv("AUTONOMOUS_INTERVAL_SECONDS", "300"))
# Script execution is a much bigger trust boundary than file I/O: a .py
# file living under workspace/ can still do anything the OS user running
# this process can do (network, filesystem outside workspace/, etc) once
# it's actually executed. Off by default.
AUTONOMOUS_ALLOW_EXEC = os.getenv("AUTONOMOUS_ALLOW_EXEC", "false").lower() == "true"

VALID_ACTIONS = {
    "chat", "status", "scan", "propose_trade",
    "confirm_trade", "cancel_trade", "create_note", "create_strategy",
}