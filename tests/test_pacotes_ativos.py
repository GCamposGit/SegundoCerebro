"""FND-12: the active queue is a file, not ROADMAP prose.

Isolated fixtures prove the class: duplicate id, missing dependency, cycle,
delivered without evidence, 'neste PR' as fake merge, overlapping writers,
and a glob that matches nothing. The real queue must load clean.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "scripts" / "verificar_pacotes.py"


def _carregar_helper():
    spec = importlib.util.spec_from_file_location("verificar_pacotes", HELPER)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _toml(corpo: str) -> str:
    return corpo.strip() + "\n"


def _pacote(
    ident: str,
    *,
    estado: str = "proposto",
    dono: str = "notebook",
    paths: str = '["src/segundocerebro/acesso/identidade.py"]',
    deps: str = "[]",
    evidencia: str = '""',
) -> str:
    return f"""
[[pacote]]
id = "{ident}"
estado = "{estado}"
dono = "{dono}"
paths = {paths}
dependencias = {deps}
aceite = "aceite sintetico"
evidencia = {evidencia}
proxima_acao = "seguir"
"""


def test_evidencia_neste_pr_nao_prova_merge() -> None:
    mod = _carregar_helper()
    assert not mod.evidencia_prova_entrega("neste PR")
    assert not mod.evidencia_prova_entrega("entregue neste pr, sem numero")
    assert not mod.evidencia_prova_entrega({"pr": "neste PR"})
    assert mod.evidencia_prova_entrega({"pr": 90, "sha": "3fd8f4a"})
    assert mod.evidencia_prova_entrega("3fd8f4af2dab1884e9b58e3074c575e1d8cfde7d")


def test_id_duplicado_reprova(tmp_path: Path) -> None:
    mod = _carregar_helper()
    texto = _toml(_pacote("FND-X") + _pacote("FND-X", dono="desktop"))
    erros = mod.validar(mod.carregar(texto), tmp_path)
    assert any("duplicado" in e for e in erros)


def test_dependencia_inexistente_reprova(tmp_path: Path) -> None:
    mod = _carregar_helper()
    texto = _toml(_pacote("FND-X", deps='["FND-Z"]'))
    erros = mod.validar(mod.carregar(texto), tmp_path)
    assert any("inexistente" in e for e in erros)


def test_ciclo_reprova(tmp_path: Path) -> None:
    mod = _carregar_helper()
    texto = _toml(
        _pacote("FND-A", deps='["FND-B"]') + _pacote("FND-B", deps='["FND-A"]')
    )
    erros = mod.validar(mod.carregar(texto), tmp_path)
    assert any(e.startswith("ciclo:") for e in erros)


def test_entregue_sem_evidencia_reprova(tmp_path: Path) -> None:
    mod = _carregar_helper()
    texto = _toml(_pacote("FND-X", estado="entregue"))
    erros = mod.validar(mod.carregar(texto), tmp_path)
    assert any("sem evidencia" in e for e in erros)
    texto_ok = _toml(_pacote("FND-X", estado="entregue", evidencia="{ pr = 90 }"))
    assert not mod.validar(mod.carregar(texto_ok), tmp_path)


def test_glob_sem_arquivo_reprova(tmp_path: Path) -> None:
    mod = _carregar_helper()
    texto = _toml(_pacote("FND-X", paths='["src/nao_existe_*.py"]'))
    erros = mod.validar(mod.carregar(texto), tmp_path)
    assert any("glob sem arquivo" in e for e in erros)


def test_arquivo_novo_reservado_nao_e_glob(tmp_path: Path) -> None:
    mod = _carregar_helper()
    texto = _toml(_pacote("FND-X", paths='["src/segundocerebro/index/operacoes.py"]'))
    assert not mod.validar(mod.carregar(texto), tmp_path)


def test_dois_escritores_com_path_sobreposto_reprova(tmp_path: Path) -> None:
    mod = _carregar_helper()
    alvo = tmp_path / "src" / "segundocerebro" / "index"
    alvo.mkdir(parents=True)
    (alvo / "store.py").write_text("# fixture\n", encoding="utf-8")
    relativo = '["src/segundocerebro/index/store.py"]'
    texto = _toml(
        _pacote("FND-A", estado="em_execucao", dono="desktop", paths=relativo)
        + _pacote("FND-B", estado="pronto", dono="notebook", paths=relativo)
    )
    erros = mod.validar(mod.carregar(texto), tmp_path)
    assert any("sobrepostos" in e for e in erros)


def test_bloqueado_pode_reservar_o_mesmo_path(tmp_path: Path) -> None:
    mod = _carregar_helper()
    relativo = '["src/segundocerebro/index/store.py"]'
    texto = _toml(
        _pacote("FND-A", estado="bloqueado", dono="acordo", paths=relativo)
        + _pacote("FND-B", estado="proposto", dono="desktop", paths=relativo)
    )
    assert not mod.validar(mod.carregar(texto), tmp_path)


def test_fila_real_carrega_sem_erro() -> None:
    mod = _carregar_helper()
    erros = mod.validar_arquivo(REPO / "docs" / "pacotes-ativos.toml", REPO)
    assert not erros, erros
    pacotes = mod.carregar((REPO / "docs" / "pacotes-ativos.toml").read_text(encoding="utf-8"))
    ids = {p.id for p in pacotes}
    assert {"FND-01a", "FND-01b", "FND-01b-int", "FND-02a", "FND-02b", "FND-08a", "FND-08b"} <= ids
    por_id = {p.id: p for p in pacotes}
    assert por_id["FND-01b"].estado == "entregue"
    assert por_id["FND-01b"].dono == "notebook"
    assert por_id["FND-01b-int"].estado == "entregue"
    assert por_id["FND-01b-int"].dono == "notebook"
    assert (REPO / "docs" / "fnd-01b-identidade-interna.md").is_file()
    abertos = [p for p in pacotes if p.estado in {"proposto", "pronto", "em_execucao", "bloqueado"}]
    assert any(p.id == "DF-LAP-1" and p.estado == "em_execucao" for p in abertos)
    assert all(p.paths and p.aceite for p in abertos)
    assert por_id["CI-SQLITE-OPEN"].estado == "entregue"
    assert por_id["CI-SQLITE-OPEN"].evidencia["pr"] == 112
    assert por_id["DF-BOOTSTRAP"].estado == "entregue"
    assert por_id["DF-BOOTSTRAP"].evidencia["pr"] == 113
    assert (REPO / "docs" / "volta-manual-nivel-2.md").is_file()
    entregues = [p for p in pacotes if p.estado == "entregue"]
    assert entregues, "dependencias entregues sumiram; 01b/02b ficariam sem evidencia"
    assert all(mod.evidencia_prova_entrega(p.evidencia) for p in entregues)


def test_cli_da_fila_real_sai_zero() -> None:
    proc = subprocess.run(  # noqa: S603 — python deste repo, argv fixo no helper
        [sys.executable, str(HELPER)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "0 erro" in proc.stdout
