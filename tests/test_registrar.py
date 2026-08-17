"""Geração do `.mcp.json` por base.

O que se guarda aqui é sobretudo o que **não** pode acontecer: apagar a
configuração de outro servidor MCP do usuário para escrever a nossa.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from segundocerebro.config import BASE_UNICA, Base
from segundocerebro.mcp.registrar import CHAVE, entrada_de, main, mesclar, trecho


def escrever_config(tmp_path, texto: str):  # noqa: ANN001, ANN201
    caminho = tmp_path / "config.toml"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


DUAS_BASES = """
[[base]]
id = "pessoal"
indice = "ip"
[[base]]
id = "trabalho"
indice = "it"
"""


def test_entrada_aponta_a_base():
    entrada = entrada_de(Base(id="trabalho"))
    assert entrada["args"] == ["-m", "segundocerebro.mcp.server", "--base", "trabalho"]
    assert entrada["env"]["PYTHONIOENCODING"] == "utf-8", "sem isto o stdio quebra com acento"


def test_base_unica_mantem_o_nome_historico():
    """Quem já registrou `segundocerebro` não precisa reconfigurar o cliente."""
    assert list(trecho([Base(id=BASE_UNICA)])[CHAVE]) == ["segundocerebro"]


def test_base_sintetizada_nao_cita_o_id_no_registro(tmp_path, capsys, monkeypatch):
    """`padrao` é id sintético: some quando o usuário escrever o config dele.

    Um registro que o cite quebraria nesse dia. Sem a flag, o servidor resolve a
    base única e falha com a mensagem certa quando deixar de ser única.
    """
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    (tmp_path / "census.toml").write_text("[[roots]]\npath = 'C:\\\\Docs'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main([]) == 0

    entrada = json.loads(capsys.readouterr().out)[CHAVE]["segundocerebro"]
    assert entrada["args"] == ["-m", "segundocerebro.mcp.server"]
    assert "--base" not in entrada["args"]


def test_cada_base_vira_um_servidor():
    nomes = trecho([Base(id="pessoal"), Base(id="trabalho")])[CHAVE]
    assert set(nomes) == {"segundocerebro-pessoal", "segundocerebro-trabalho"}


def test_mesclar_preserva_servidores_de_terceiros():
    """O `.mcp.json` do usuário costuma ter outros servidores dentro."""
    existente = {CHAVE: {"github": {"command": "gh-mcp"}}, "outra_chave": 1}

    mesclado, acrescentados, trocados = mesclar(existente, trecho([Base(id="trabalho")]))

    assert mesclado[CHAVE]["github"] == {"command": "gh-mcp"}
    assert mesclado["outra_chave"] == 1
    assert acrescentados == ["segundocerebro-trabalho"] and trocados == []


def test_mesclar_relata_o_que_trocou():
    existente = {CHAVE: {"segundocerebro-trabalho": {"command": "antigo"}}}
    _, acrescentados, trocados = mesclar(existente, trecho([Base(id="trabalho")]))
    assert trocados == ["segundocerebro-trabalho"] and acrescentados == []


def test_mesclar_e_idempotente():
    novo = trecho([Base(id="trabalho")])
    uma_vez, _, _ = mesclar({}, novo)
    duas_vezes, acrescentados, trocados = mesclar(uma_vez, novo)
    assert uma_vez == duas_vezes and not acrescentados and not trocados


def test_cliente_fora_do_projeto_recebe_caminho_absoluto(tmp_path, capsys, monkeypatch):
    """O bloqueador real do segundo cliente, e o pior tipo de falha.

    O Claude Desktop nasce em `C:\\Windows\\system32`. Ali `PYTHONPATH=src` não
    aponta para nada, e o servidor sobe com `ModuleNotFoundError` — que o cliente
    mostra como "servidor não conecta", silencioso quanto à causa.
    """
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)

    assert main(["--config", str(cfg), "--base", "pessoal", "--cliente", "claude-desktop"]) == 0

    entrada = json.loads(capsys.readouterr().out)[CHAVE]["segundocerebro-pessoal"]
    assert Path(entrada["env"]["PYTHONPATH"]).is_absolute()
    assert "cwd" in entrada, "índice e dourado podem ser relativos ao config"
    assert Path(entrada["cwd"]).is_absolute()
    assert any(a.endswith("config.toml") for a in entrada["args"]), "--config absoluto"


def test_claude_code_continua_relativo(tmp_path, capsys, monkeypatch):
    """Ele abre na pasta do projeto — caminho absoluto ali só engessaria o repo."""
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)

    main(["--config", str(cfg), "--base", "pessoal", "--cliente", "claude-code"])

    entrada = json.loads(capsys.readouterr().out)[CHAVE]["segundocerebro-pessoal"]
    assert entrada["env"]["PYTHONPATH"] == "src"
    assert "cwd" not in entrada


def test_cli_imprime_sem_gravar(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)

    assert main(["--config", str(cfg), "--base", "pessoal"]) == 0

    saida = json.loads(capsys.readouterr().out)
    assert list(saida[CHAVE]) == ["segundocerebro-pessoal"]
    assert not (tmp_path / ".mcp.json").exists()


def test_cli_grava_mesclando(tmp_path, monkeypatch):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    alvo = tmp_path / ".mcp.json"
    alvo.write_text(json.dumps({CHAVE: {"github": {"command": "gh-mcp"}}}), encoding="utf-8")

    assert main(["--config", str(cfg), "--todas", "--out", str(alvo)]) == 0

    escrito = json.loads(alvo.read_text(encoding="utf-8"))
    assert set(escrito[CHAVE]) == {"github", "segundocerebro-pessoal", "segundocerebro-trabalho"}


def test_cli_recusa_json_invalido_em_vez_de_sobrescrever(tmp_path, monkeypatch):
    """Arquivo ilegível é motivo para parar, não para recomeçar do zero."""
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    alvo = tmp_path / ".mcp.json"
    alvo.write_text("{isto não é json", encoding="utf-8")

    assert main(["--config", str(cfg), "--todas", "--out", str(alvo)]) == 2
    assert alvo.read_text(encoding="utf-8") == "{isto não é json"


def test_cli_exige_escolha_com_duas_bases(tmp_path, monkeypatch):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    assert main(["--config", str(cfg)]) == 2


@pytest.mark.parametrize("base_id", ["pessoal", "trabalho"])
def test_o_json_gerado_e_valido_e_completo(tmp_path, capsys, monkeypatch, base_id):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    main(["--config", str(cfg), "--base", base_id])

    entrada = json.loads(capsys.readouterr().out)[CHAVE][f"segundocerebro-{base_id}"]
    assert entrada["command"] == "py"
    assert base_id in entrada["args"]
