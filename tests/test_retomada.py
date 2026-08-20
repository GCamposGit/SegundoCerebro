"""Retomada automática — o que ela retoma e, principalmente, o que ela não toca.

Uma indexação de 39 h atravessa reinício, hibernação e queda de energia. O risco
não é deixar de retomar: é retomar em cima de um indexador vivo, que duplica cada
vetor sem levantar erro.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from segundocerebro.config import Base
from segundocerebro.index.indexer import NOME_DA_TRAVA
from segundocerebro.index.progresso import NOME, caminho_de
from segundocerebro.index.retomada import INACABADOS, linha_da_tarefa, main, pendente


def base_com_progresso(tmp_path: Path, status: str, **extra) -> Base:  # noqa: ANN003
    indice = tmp_path / "indice"
    indice.mkdir(exist_ok=True)
    dados = {"status": status, "documentos": {"feitos": 40, "totais": 100},
             "restante": "2 h", **extra}
    caminho_de(indice).write_text(json.dumps(dados), encoding="utf-8")
    return Base(id="x", indice=indice)


@pytest.mark.parametrize("status", sorted(INACABADOS))
def test_run_inacabado_e_pendente(tmp_path: Path, status: str) -> None:
    """`indexando` num arquivo em repouso é o mais informativo: morreu sem encerrar."""
    assert pendente(base_com_progresso(tmp_path, status)) is not None


def test_run_concluido_nao_e_pendente(tmp_path: Path) -> None:
    assert pendente(base_com_progresso(tmp_path, "concluida")) is None


def test_base_sem_progresso_nao_e_pendente(tmp_path: Path) -> None:
    """Nunca indexada não é o mesmo que interrompida."""
    indice = tmp_path / "vazio"
    indice.mkdir()
    assert pendente(Base(id="x", indice=indice)) is None


def test_base_com_indexador_vivo_nao_e_pendente(tmp_path: Path) -> None:
    """O caso que importa: retomar em cima de um run vivo duplica cada vetor.

    O SQLite em WAL tolera a concorrência, o LanceDB não — medido uma vez como
    13.458 vetores para 7.214 chunks, sem nada levantar erro.
    """
    base = base_com_progresso(tmp_path, "indexando")
    trava = base.indice / NOME_DA_TRAVA
    import psutil

    trava.write_text(f"{os.getpid()},{psutil.Process().create_time():.3f}", encoding="utf-8")

    assert pendente(base) is None


def test_trava_orfa_nao_impede_retomada(tmp_path: Path) -> None:
    """Queda de energia deixa trava para trás; ela não pode ser sentença perpétua."""
    base = base_com_progresso(tmp_path, "indexando")
    (base.indice / NOME_DA_TRAVA).write_text("999999,1.000", encoding="utf-8")

    assert pendente(base) is not None


def test_progresso_ilegivel_nao_e_pendente(tmp_path: Path) -> None:
    indice = tmp_path / "indice"
    indice.mkdir()
    (indice / NOME).write_text("{truncado", encoding="utf-8")
    assert pendente(Base(id="x", indice=indice)) is None


# --- a linha de comando -------------------------------------------------------


def test_listar_nao_indexa_nada(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "config.toml").write_text(
        '[[base]]\nid = "x"\nindice = "indice"\n', encoding="utf-8"
    )
    base_com_progresso(tmp_path, "interrompida")
    chamadas = []
    monkeypatch.setattr(
        "segundocerebro.index.retomada.subprocess.run",
        lambda *a, **k: chamadas.append(a) or type("R", (), {"returncode": 0})(),
    )

    assert main(["--config", str(tmp_path / "config.toml"), "--listar"]) == 0
    assert chamadas == [], "--listar não dispara indexador"


def test_sem_nada_a_retomar_sai_com_sucesso(tmp_path: Path) -> None:
    """Roda a cada logon: erro no caso normal treina o usuário a ignorar o aviso."""
    (tmp_path / "config.toml").write_text(
        '[[base]]\nid = "x"\nindice = "indice"\n', encoding="utf-8"
    )
    base_com_progresso(tmp_path, "concluida")

    assert main(["--config", str(tmp_path / "config.toml")]) == 0


def test_retoma_chamando_o_indexador(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.toml").write_text(
        '[[base]]\nid = "x"\nindice = "indice"\n', encoding="utf-8"
    )
    base_com_progresso(tmp_path, "indexando")
    comandos = []

    def falso(comando, **k):  # noqa: ANN001, ANN003, ANN202
        comandos.append(comando)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("segundocerebro.index.retomada.subprocess.run", falso)
    assert main(["--config", str(tmp_path / "config.toml"), "--perfil", "leve"]) == 0

    assert len(comandos) == 1
    assert "--base" in comandos[0] and "x" in comandos[0]
    assert comandos[0][-2:] == ["--perfil", "leve"], "retoma em esforço leve por padrão"


def test_config_invalida_falha_claro(tmp_path: Path) -> None:
    ruim = tmp_path / "config.toml"
    ruim.write_text('[[base]]\nid = "Maiúscula"\n', encoding="utf-8")
    assert main(["--config", str(ruim)]) == 2


def test_linha_da_tarefa_entra_na_pasta_do_projeto() -> None:
    """A tarefa nasce em system32; `PYTHONPATH=src` relativo não vale nada de lá."""
    linha = linha_da_tarefa(Path(r"C:\Projeto"))

    assert "cd /d" in linha and r"C:\Projeto" in linha
    assert r"PYTHONPATH=C:\Projeto\src" in linha
    assert "segundocerebro.index.retomada" in linha


def test_linha_da_tarefa_leva_o_provider_de_quem_instalou(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem isto a retomada no logon cai na CPU neste desktop."""
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    linha = linha_da_tarefa(Path(r"C:\Projeto"))
    assert "SEGUNDOCEREBRO_PROVIDER=cuda" in linha
