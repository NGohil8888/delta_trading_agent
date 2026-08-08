"""
agent/docs_fetch.py -- DocsMixin: fetches the live Delta docs page for
human review.

Deliberately NOT an LLM-dispatchable chat action. Feeding freshly-fetched
external web content straight into an LLM that can place real trades is a
genuine prompt-injection surface -- a compromised or edited docs page
could smuggle instructions into the agent's context, and the agent would
have no way to tell the difference between real documentation and an
injected instruction. This exists so a HUMAN can pull the current page,
diff it against KNOWLEDGE.md, and update KNOWLEDGE.md by hand -- the
agent never autonomously absorbs or acts on what's fetched here.

CLI-only: `docs` command in agent/core.py's chat_loop.
"""
from typing import Any, Dict

import requests

DELTA_DOCS_URL = "https://docs.delta.exchange/"


class DocsMixin:
    def fetch_delta_docs_snapshot(self, timeout: int = 20) -> Dict[str, Any]:
        try:
            r = requests.get(
                DELTA_DOCS_URL,
                timeout=timeout,
                headers={"User-Agent": "delta-trading-agent-docs-check/1.0"},
            )
        except Exception as exc:
            return {"ok": False, "detail": f"Could not reach {DELTA_DOCS_URL}: {exc}"}

        if r.status_code != 200:
            return {"ok": False, "detail": f"{DELTA_DOCS_URL} returned HTTP {r.status_code}"}

        path = self.create_workspace_file("research/delta_docs_snapshot.html", r.text)
        self.log_event(f"Fetched live Delta docs snapshot to {path} for human review.", "SYSTEM")
        return {
            "ok": True,
            "path": path,
            "bytes": len(r.text),
            "detail": (
                f"Saved live docs snapshot to {path} ({len(r.text)} bytes). "
                "This is NOT automatically read by the agent or fed into any "
                "chat context -- review it yourself and update KNOWLEDGE.md by "
                "hand if anything changed."
            ),
        }