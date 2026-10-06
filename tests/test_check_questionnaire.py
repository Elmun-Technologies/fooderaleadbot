"""The pre-deploy questionnaire gate must keep working (it guards the deploy source tree)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_questionnaire.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


class TestDeployCheck:
    def test_the_tree_is_ready_to_deploy(self) -> None:
        result = run()
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ready to deploy" in result.stdout
        assert "✅" in result.stdout

    def test_it_reports_what_it_verified(self) -> None:
        out = run().stdout
        assert "q:intent:stand, q:intent:visitor" in out
        assert "visitor_region" in out
        assert "27–29 oktabr 2026" in out

    def test_help_documents_the_deploy_usage(self) -> None:
        result = run("--help")
        assert result.returncode == 0
        assert "fly deploy" in result.stdout
