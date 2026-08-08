"""
agent/core.py -- TradingAgent: composes every mixin into the one class
dashboard.py and the CLI actually construct and use.

Mixin order matters only for MRO tie-breaking (there are no real method
name collisions here); grouped by dependency roughly bottom-up: state and
file I/O first (everything else logs / writes through them), then the
Delta API client, then market/trading logic built on top of it, then LLM
glue, then autonomy, which uses all of the above.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from agent import config
from agent.models import TradeIdea
from agent.state_store import StateMixin
from agent.workspace_tools import WorkspaceMixin
from agent.delta_client import DeltaMixin
from agent.market import MarketMixin
from agent.trading import TradingMixin
from agent.llm_chat import LLMMixin
from agent.autonomy import AutonomyMixin
from agent.docs_fetch import DocsMixin


class TradingAgent(
    StateMixin,
    WorkspaceMixin,
    DeltaMixin,
    MarketMixin,
    TradingMixin,
    LLMMixin,
    AutonomyMixin,
    DocsMixin,
):
    def __init__(self):
        self.history: List[Dict[str, Any]] = []
        self.daily_trades = 0
        # Tracks the UTC date the daily counter was last reset, so a process
        # that lives across midnight starts the new day back at zero.
        self._last_reset_date: str = date.today().isoformat()
        self.session_notes = []
        self.client = None
        self.failure_count = 0
        self._recovery_in_progress = False
        self.pending_trade: Optional[TradeIdea] = None
        if config.ollama is not None and config.OLLAMA_API_KEY:
            self.client = config.ollama.Client(
                host=config.OLLAMA_HOST,
                headers={"Authorization": f"Bearer {config.OLLAMA_API_KEY}"}
            )
        self._ensure_workspace_dirs()
        # Restore the daily counter from real history instead of
        # hardcoding 0 -- without this, restarting the process silently
        # reset the daily trade limit, and a fresh session had no way to
        # answer "have you ever taken a trade" correctly.
        try:
            self.daily_trades = self._trade_history_summary()["executed_today"]
        except Exception:
            pass  # workspace/ideas_history.json missing or unreadable -- start at 0, don't crash startup

    def _ensure_workspace_dirs(self):
        for subdir in ["notes", "research", "logs", "strategies"]:
            (config.WORKSPACE_DIR / subdir).mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # CLI
    # ------------------------------------------------------------------
    def chat_loop(self):
        print("Trading agent ready. Type 'scan', 'idea BTCUSD', 'status', 'note <title>', 'file <name>', "
              "'debug', 'docs', 'protect SYMBOL SIDE STOP TARGET', 'ls [subdir]', 'read <path>', 'rm <path>', "
              "'run <path.py>', or any question.")
        while True:
            user = input("\nYou> ").strip()
            if user.lower() in {"quit", "exit"}:
                break

            if user.lower() == "debug":
                import diagnostics
                diagnostics.run_diagnostics(verbose=True)
                continue

            if user.lower() == "docs":
                result = self.fetch_delta_docs_snapshot()
                print(result["detail"])
                continue

            if user.lower().startswith("protect "):
                # protect SYMBOL SIDE STOP TARGET
                parts = user.split()
                if len(parts) != 5:
                    print("Usage: protect SYMBOL SIDE STOP_LOSS TAKE_PROFIT   (e.g. protect BTCUSD buy 62495.13 64388.92)")
                    continue
                _, symbol, side, stop_s, tp_s = parts
                try:
                    code, res = self.attach_bracket_to_position(symbol, side.lower(), float(stop_s), float(tp_s))
                    print(f"HTTP {code}: {res}")
                except Exception as exc:
                    print(f"Error: {exc}")
                continue

            if user.lower().startswith("note "):
                title = user.split(" ", 1)[1].strip()
                path = self.add_note(title, f"Auto-generated note for {title}.")
                print(f"Note saved to {path}")
                continue

            if user.lower().startswith("file "):
                filename = user.split(" ", 1)[1].strip()
                path = self.create_workspace_file(filename, f"# {filename}\n\nCreated by trading agent.\n")
                print(f"File created at {path}")
                continue

            if user.lower() == "ls" or user.lower().startswith("ls "):
                parts = user.split(" ", 1)
                subdir = parts[1].strip() if len(parts) > 1 else ""
                try:
                    for f in self.list_workspace_files(subdir):
                        print(f"  {f}")
                except ValueError as exc:
                    print(f"Error: {exc}")
                continue

            if user.lower().startswith("read "):
                path = user.split(" ", 1)[1].strip()
                try:
                    print(self.read_workspace_file(path))
                except (ValueError, FileNotFoundError) as exc:
                    print(f"Error: {exc}")
                continue

            if user.lower().startswith("rm "):
                path = user.split(" ", 1)[1].strip()
                try:
                    print("Deleted." if self.delete_workspace_file(path) else "No such file.")
                except ValueError as exc:
                    print(f"Error: {exc}")
                continue

            if user.lower().startswith("run "):
                path = user.split(" ", 1)[1].strip()
                print(self.run_workspace_script(path))
                continue

            if user.lower() == "auto":
                self.run_autonomous_loop(iterations=3, interval_seconds=10)
                continue

            self.log_event(user, "USER")
            result = self.agent_respond(user)
            # Symmetric with dashboard.py's /api/chat route: log both sides
            # of every exchange. Without this, CLI usage (`python engine.py`)
            # was invisible in status.json/journal/audit.log -- only actions
            # dispatched to specific handlers (propose_trade, scan, etc.)
            # left any trace; a plain conversational exchange left none.
            self.log_event(result.get("reply", ""), "AGENT")
            print(f"Agent> {result.get('reply')}")