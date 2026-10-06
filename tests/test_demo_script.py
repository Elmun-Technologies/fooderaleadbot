"""The offline preview script must keep working: the README tells people to run it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo_run.py"


def run(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


class TestDemoScript:
    def test_the_exhibitor_preview_renders_both_languages(self) -> None:
        out = run()
        assert "Savol 1/" in out and "Вопрос 1/" in out
        assert "SALES_GROUP_ID" in out
        assert "Score: 100/100" in out  # the sample answers are a perfect exhibitor
        assert "Chirchik Juice Plant" in out

    def test_questions_do_not_leak_catalog_keys_or_placeholders(self) -> None:
        out = run("--lang", "uz")
        for leaked in ("{field}", "q.", "hint.", "opt."):
            assert leaked not in out, leaked

    def test_the_visitor_preview_skips_the_scoring(self) -> None:
        out = run("--intent", "visitor", "--lang", "ru")
        assert "Score:" not in out, "visitors are never scored, not even in the preview"
        assert "Стенд" not in out, "the stand block does not exist for visitors"
        assert "Связь с индустрией" not in out, "the industry question is gone"
        assert "no score, no stand data" in out

    def test_the_exhibitor_preview_never_asks_for_links_any_more(self) -> None:
        out = run("--lang", "uz")
        assert "sayt" not in out.lower(), "the website / Instagram question is gone"
        assert "Instagram" not in out
        assert "Savol 1/9" in out

    def test_arguments_are_accepted(self) -> None:
        assert "── scoring (ru)" in run("--lang", "ru")
        assert "── scoring (uz)" in run("--lang", "uz")
        # pricing / partner are legacy answers: they are no longer advertised, not even here
        assert "--intent" in run("--help") and "pricing" not in run("--help")
