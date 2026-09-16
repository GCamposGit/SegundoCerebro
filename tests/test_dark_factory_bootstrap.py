from __future__ import annotations

import json
import sys
from pathlib import Path

from core.harness.markers import parse_harness_output
from core.harness.runner import resolve_python_command
from core.orchestrator.guard import audit_paths


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_SKILLS = (
    "depurar",
    "entregar",
    "medir",
    "navegar",
    "pacote",
    "revisar",
    "segundo-cerebro-notebook",
)


def test_darkfac_snapshot_is_pinned_and_isolated() -> None:
    lock = json.loads((ROOT / ".factory" / "darkfac.lock.json").read_text(encoding="utf-8"))

    assert lock["source_commit"] == "de6442408427adaaf336a122c6dd7c4dbe2e9311"
    assert lock["installation_mode"] == "vendored_snapshot"
    assert lock["autonomy_level"] == 2
    assert lock["auto_merge"] is False
    assert lock["scheduler"] is False
    assert lock["source_repository"] == "DarkFac"


def test_snapshot_has_no_symlink_to_sibling_checkout() -> None:
    for relativo in (".agents", "core", ".factory"):
        caminho = ROOT / relativo
        assert caminho.exists()
        assert not caminho.is_symlink()
        assert "dev\\DarkFac" not in str(caminho.resolve())
        assert "dev/DarkFac" not in str(caminho.resolve())


def test_product_skills_were_not_replaced() -> None:
    for nome in PRODUCT_SKILLS:
        assert (ROOT / ".claude" / "skills" / nome / "SKILL.md").is_file(), nome
    agentes = sorted(
        path.name for path in (ROOT / ".agents" / "skills").iterdir() if path.is_dir()
    )
    assert agentes[0] == "00-continuous-self-improvement"
    assert "16-visual-asset-studio" in agentes
    assert len(agentes) == 17


def test_empty_harness_output_is_not_a_pass() -> None:
    result = parse_harness_output([])

    assert result["valid"] is False
    assert result["is_empty"] is True


def test_guard_detects_project_governance_paths() -> None:
    violations = audit_paths(["MISSION.md", "src/segundocerebro/config.py"])

    assert violations == ["MISSION.md"]


def test_harness_quick_has_at_least_one_step_and_full_suite_is_separate() -> None:
    config = json.loads((ROOT / "harness.config.json").read_text(encoding="utf-8"))
    quick = [step for step in config["steps"] if step.get("quick") is True]
    full = [step for step in config["steps"] if not step.get("quick")]

    assert quick
    assert any("test_dark_factory_bootstrap.py" in step["cmd"] for step in quick)
    assert any("tests/ eval/" in step["cmd"] for step in full)


def test_harness_reuses_the_interpreter_that_started_it() -> None:
    command = resolve_python_command("python -m pytest")

    assert command == f'"{sys.executable}" -m pytest'
