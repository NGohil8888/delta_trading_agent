import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import engine
from agent import config


class AgentDocumentationTests(unittest.TestCase):
    def test_record_thought_writes_journal_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch agent.config directly -- the mixins in agent/*.py read
            # config.WORKSPACE_DIR / config.STATUS_FILE at call time via
            # `from agent import config; config.X`, so patching the engine.py
            # facade's static copies would NOT affect real behavior here.
            with patch.object(config, "WORKSPACE_DIR", Path(tmpdir)), \
                 patch.object(config, "STATUS_FILE", Path(tmpdir) / "status.json"):
                agent = engine.TradingAgent()
                agent.record_thought("Test thought for documentation", category="test")

                journal_path = Path(tmpdir) / "notes" / "agent_journal.md"
                self.assertTrue(journal_path.exists())
                content = journal_path.read_text(encoding="utf-8")
                self.assertIn("Test thought for documentation", content)
                self.assertIn("test", content)

    def test_handle_failure_writes_recovery_note_and_restarts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # STATUS_FILE must be patched here too -- handle_failure() calls
            # log_event() and write_agent_state(), both of which write to
            # STATUS_FILE. Without this patch these tests write "Failure in
            # market scan: boom" straight into the real project status.json.
            with patch.object(config, "WORKSPACE_DIR", Path(tmpdir)), \
                 patch.object(config, "STATUS_FILE", Path(tmpdir) / "status.json"):
                agent = engine.TradingAgent()
                agent.failure_count = 2
                with patch.object(agent, "autonomous_cycle", return_value=None) as mock_cycle:
                    agent.handle_failure("market scan", RuntimeError("boom"))

                journal_path = Path(tmpdir) / "notes" / "agent_journal.md"
                self.assertTrue(journal_path.exists())
                content = journal_path.read_text(encoding="utf-8")
                self.assertIn("Recovery triggered", content)
                mock_cycle.assert_called_once()


if __name__ == "__main__":
    unittest.main()