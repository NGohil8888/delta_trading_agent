"""
agent/workspace_tools.py -- WorkspaceMixin: the agent's file toolkit.

Every method here is hard-scoped to workspace/ via _safe_workspace_path,
enforced by code (path resolution + containment check), not convention.
This is what makes "the agent can create/read/delete files freely" safe:
the boundary is workspace/, full stop -- it never touches engine.py,
dashboard.py, .env, AGENTS.md, README.md, or the test files, because it
has no tool capable of reaching them.
"""
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from agent import config


class WorkspaceMixin:
    def _safe_workspace_path(self, relative_path: str) -> Path:
        """Resolve relative_path against workspace/ and refuse anything
        that would escape it -- absolute paths, '..' traversal, symlinks
        pointing outside.
        """
        if not relative_path or not isinstance(relative_path, str):
            raise ValueError("A relative workspace path is required.")
        candidate = (config.WORKSPACE_DIR / relative_path).resolve()
        workspace_root = config.WORKSPACE_DIR.resolve()
        if candidate != workspace_root and workspace_root not in candidate.parents:
            raise ValueError(f"Refusing path outside workspace/: {relative_path!r}")
        return candidate

    def create_workspace_file(self, filename: str, content: str) -> str:
        target = self._safe_workspace_path(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def read_workspace_file(self, filename: str) -> str:
        target = self._safe_workspace_path(filename)
        if not target.is_file():
            raise FileNotFoundError(f"No such workspace file: {filename}")
        return target.read_text(encoding="utf-8")

    def list_workspace_files(self, subdir: str = "") -> List[str]:
        root = self._safe_workspace_path(subdir) if subdir else config.WORKSPACE_DIR
        if not root.exists():
            return []
        return sorted(str(p.relative_to(config.WORKSPACE_DIR)) for p in root.rglob("*") if p.is_file())

    def delete_workspace_file(self, filename: str) -> bool:
        target = self._safe_workspace_path(filename)
        if not target.is_file():
            return False
        target.unlink()
        self.log_event(f"Deleted workspace file: {filename}", "SYSTEM")
        return True

    def run_workspace_script(self, filename: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute a .py file that lives under workspace/.

        IMPORTANT: this does NOT sandbox what the script can do. A process
        spawned this way has the same OS-level permissions as the rest of
        this app -- filesystem access outside workspace/, network access,
        everything -- regardless of where the .py file itself sits.
        Keeping the file under workspace/ constrains where the FILE lives,
        not what the CODE can do once it's running. Gated behind
        AUTONOMOUS_ALLOW_EXEC=true in .env (default false).
        """
        if not config.AUTONOMOUS_ALLOW_EXEC:
            return {"ok": False, "detail": "AUTONOMOUS_ALLOW_EXEC is false in .env -- script execution is disabled."}
        target = self._safe_workspace_path(filename)
        if not target.is_file() or target.suffix != ".py":
            return {"ok": False, "detail": f"Not a runnable .py file under workspace/: {filename}"}
        try:
            proc = subprocess.run(
                [sys.executable, str(target)],
                cwd=str(config.WORKSPACE_DIR),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            result = {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
        except subprocess.TimeoutExpired:
            result = {"ok": False, "detail": f"Script timed out after {timeout}s."}
        except Exception as exc:
            result = {"ok": False, "detail": f"Execution failed: {exc}"}
        self.log_event(f"Ran workspace script {filename}: ok={result.get('ok')}", "SYSTEM")
        return result

    def add_note(self, title: str, content: str) -> str:
        slug = title.lower().strip().replace(" ", "_") or "note"
        filename = f"notes/{slug}.md"
        return self.create_workspace_file(filename, f"# {title}\n\n{content}\n")

    def create_strategy_file(self, title: str, content: str) -> str:
        slug = title.lower().strip().replace(" ", "_") or "strategy"
        filename = f"strategies/{slug}.md"
        return self.create_workspace_file(filename, f"# {title}\n\n{content}\n")