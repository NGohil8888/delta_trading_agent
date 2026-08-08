"""
agent/autonomy.py -- AutonomyMixin: heartbeat, self-diagnosis, failure
recovery, and the autonomous scan-and-propose cycle.

Hard rule enforced by construction: nothing in this module calls
_confirm_pending. Proactive research/journaling is unattended by design;
placing a real order is not, and stays gated on an explicit human
confirmation in agent/trading.py no matter how this loop is configured.
"""
import json
import time
from typing import Any, Dict, List, Optional

from agent import config
from agent.models import TradeIdea


class AutonomyMixin:
    def heartbeat(self) -> Dict[str, Any]:
        """Lightweight self-check the autonomous loop runs every cycle.
        Appends a line to workspace/logs/heartbeat.log and, if it spots a
        NEW distinct problem, records it in workspace/notes/lessons_learned.md
        so both the agent and you can see what's been tried."""
        snapshot = self._delta_account_snapshot()
        line = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "delta_connected": snapshot["connected"],
            "delta_detail": snapshot["detail"],
            "ollama_configured": bool(config.OLLAMA_API_KEY),
            "daily_trades": self.daily_trades,
        }
        log_path = config.WORKSPACE_DIR / "logs" / "heartbeat.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._state_lock:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")

        if not snapshot["connected"]:
            self._note_lesson(f"Delta not connected: {snapshot['detail']}")
        return line

    def _note_lesson(self, message: str) -> None:
        """Append a deduplicated line to workspace/notes/lessons_learned.md.
        Only the FIRST time a given message is seen this process -- this
        file is meant to stay a list of distinct issues/fixes, not a
        repeated spam log (that's what heartbeat.log and agent_journal.md
        already do)."""
        if not hasattr(self, "_seen_lessons"):
            self._seen_lessons: set = set()
        if message in self._seen_lessons:
            return
        self._seen_lessons.add(message)
        path = config.WORKSPACE_DIR / "notes" / "lessons_learned.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._state_lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"- [{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

    def run_forever(self, interval_seconds: Optional[int] = None, iterations: Optional[int] = None) -> None:
        """The autonomous heartbeat loop. Intended to run in a background
        daemon thread (see dashboard.py). Each cycle: check in, and if
        Delta is reachable, run the existing scan-and-propose cycle. Never
        calls _confirm_pending -- this loop can find and journal work, it
        cannot trade without you.
        """
        interval = interval_seconds or config.AUTONOMOUS_INTERVAL_SECONDS
        count = 0
        while iterations is None or count < iterations:
            try:
                hb = self.heartbeat()
                if hb["delta_connected"]:
                    self.autonomous_cycle()
                else:
                    self.log_event(f"[autonomous] Skipped cycle -- Delta not connected: {hb['delta_detail']}", "WARN")
            except Exception as exc:
                self.handle_failure("autonomous heartbeat loop", exc)
            count += 1
            if iterations is None or count < iterations:
                time.sleep(interval)

    def handle_failure(self, context: str, error: Exception) -> None:
        self.failure_count += 1
        message = f"Failure in {context}: {error}"
        self.log_event(message, "ERROR")
        self.write_agent_state("recovering", f"Recovery triggered for {context}.")

        if self.failure_count >= 2 and not self._recovery_in_progress:
            self._recovery_in_progress = True
            self.log_event("Recovery triggered: restarting scan cycle after repeated failures.", "SYSTEM")
            try:
                self.autonomous_cycle()
            finally:
                self._recovery_in_progress = False
                self.failure_count = 0

    def autonomous_cycle(self) -> Optional[TradeIdea]:
        self.log_event("Starting autonomous scan for market opportunities.", "SYSTEM")
        self.write_agent_state("scanning", "Scanning multiple instruments for opportunities.")
        try:
            products = self.fetch_products()
        except Exception as exc:
            self.handle_failure("market scan", exc)
            return None

        if not products:
            self.log_event("No products available for scanning.", "WARN")
            self.write_agent_state("idle", "No products available for scanning.")
            return None

        symbols = [p.get("symbol") or p.get("id") or p.get("name") or "unknown" for p in products[:10]]
        ideas: List[TradeIdea] = []
        for symbol in symbols:
            try:
                idea = self.propose_trade(symbol) or self.fallback_trade_idea(symbol)
            except Exception as exc:
                self.handle_failure(f"trade idea generation for {symbol}", exc)
                continue
            if idea:
                ideas.append(idea)

        if not ideas:
            self.log_event("No actionable trade ideas were found in this scan.", "INFO")
            self.write_agent_state("idle", "No actionable ideas found in this scan.")
            return None

        top_idea = max(ideas, key=lambda item: item.confidence)
        self.add_note(
            "autonomous_scan",
            f"Top candidate: {top_idea.symbol}\n\nConfidence: {top_idea.confidence}\n\nRationale: {top_idea.rationale}",
        )
        self.log_event(f"Prepared a candidate idea for {top_idea.symbol} with confidence {top_idea.confidence}.", "TRADE")
        self.write_agent_state("monitoring", f"Top candidate: {top_idea.symbol}", ideas=ideas)
        print(f"Autonomous scan candidate: {top_idea.symbol} ({top_idea.side})")
        return top_idea

    def run_autonomous_loop(self, iterations: int = 3, interval_seconds: int = 10) -> None:
        for index in range(iterations):
            print(f"\nAutonomous cycle {index + 1}/{iterations}")
            self.autonomous_cycle()
            if index < iterations - 1:
                time.sleep(interval_seconds)
        self.write_agent_state("idle", "Autonomous scan loop completed.")