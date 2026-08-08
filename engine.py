"""
engine.py -- thin compatibility facade over the agent/ package.

The actual implementation lives in agent/ (config, models, state_store,
workspace_tools, delta_client, market, trading, llm_chat, autonomy, core).
This file exists so dashboard.py, diagnostics.py, and anything else that
does `import engine` keeps working exactly as before -- same constants,
same TradingAgent class, same CLI entry point.

For tests: this module re-exports config constants as plain values at
import time (`from agent.config import *`), which is fine for read-only
access (dashboard.py, diagnostics.py never patch these). Code that needs
to PATCH a config value for test isolation -- WORKSPACE_DIR, STATUS_FILE,
DELTA_API_KEY, etc. -- must patch `agent.config.X`, not `engine.X`, because
the actual mixins in agent/*.py read `config.X` at call time, not this
module's copy. See test_engine.py.
"""
from agent.config import (
    BASE_DIR,
    WORKSPACE_DIR,
    STATUS_FILE,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_API_KEY,
    DELTA_BASE_URL,
    DELTA_API_KEY,
    DELTA_API_SECRET,
    ACCOUNT_BALANCE,
    BALANCE_OVERRIDE,
    MAX_DAILY_TRADES,
    MAX_RISK_PCT,
    MIN_CONFIDENCE,
    TESTNET_ONLY,
    AUTONOMOUS_MODE,
    AUTONOMOUS_INTERVAL_SECONDS,
    AUTONOMOUS_ALLOW_EXEC,
    VALID_ACTIONS,
    ollama,
)
from agent.models import TradeIdea
from agent.core import TradingAgent

__all__ = [
    "BASE_DIR", "WORKSPACE_DIR", "STATUS_FILE",
    "OLLAMA_HOST", "OLLAMA_MODEL", "OLLAMA_API_KEY",
    "DELTA_BASE_URL", "DELTA_API_KEY", "DELTA_API_SECRET",
    "ACCOUNT_BALANCE", "BALANCE_OVERRIDE",
    "MAX_DAILY_TRADES", "MAX_RISK_PCT", "MIN_CONFIDENCE", "TESTNET_ONLY",
    "AUTONOMOUS_MODE", "AUTONOMOUS_INTERVAL_SECONDS", "AUTONOMOUS_ALLOW_EXEC",
    "VALID_ACTIONS", "ollama",
    "TradeIdea", "TradingAgent",
]

if __name__ == "__main__":
    TradingAgent().chat_loop()