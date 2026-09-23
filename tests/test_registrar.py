"""Geração do `.mcp.json` por base.

O que se guarda aqui é sobretudo o que **não** pode acontecer: apagar a
configuração de outro servidor MCP do usuário para escrever a nossa.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

from segundocerebro.config import BASE_UNICA, Base, ErroDeConfig, carregar
from segundocerebro.mcp.registrar import (
    CHAVE,
    DESTINOS,
    ativar,
    destino_de,
    entrada_de,
    extra_env_hardware,
    gravar_em,
    main,
    mesclar,
    python_do_projeto,
    trecho,
)


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


def test_destino_expande_variavel_de_ambiente(monkeypatch):
    """`%APPDATA%` literal viraria uma pasta chamada `%APPDATA%` dentro do projeto."""
    monkeypatch.setenv("APPDATA", r"C:\Users\alguem\AppData\Roaming")
    destino = destino_de("claude-desktop")
    assert destino is not None
    assert "%" not in str(destino)
    assert destino.is_absolute() or PureWindowsPath(str(destino)).is_absolute()


def test_percent_expande_mesmo_sem_expandvars(monkeypatch):
    """O POSIX não expande `%VAR%`. O destino do Claude Desktop está escrito assim."""
    monkeypatch.setattr(
        "segundocerebro.mcp.registrar.os.path.expandvars",
        lambda texto: texto,
    )
    monkeypatch.setenv("APPDATA", r"C:\Users\alguem\AppData\Roaming")
    destino = destino_de("claude-desktop")
    assert destino is not None
    assert "%" not in str(destino)


def test_destino_desconhecido_e_none():
    assert destino_de("generico") is None and "generico" not in DESTINOS


def test_instalar_grava_no_lugar_do_cliente(tmp_path, monkeypatch):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "Claude").mkdir()
    cfg = escrever_config(tmp_path, DUAS_BASES)

    assert main(["--config", str(cfg), "--base", "pessoal", "--cliente", "claude-desktop", "--instalar"]) == 0

    escrito = json.loads((tmp_path / "Claude" / "claude_desktop_config.json").read_text(encoding="utf-8"))
    entrada = escrito[CHAVE]["segundocerebro-pessoal"]
    assert Path(entrada["env"]["PYTHONPATH"]).is_absolute(), "cliente fora do projeto precisa de absoluto"


def test_instalar_preserva_as_preferencias_do_cliente(tmp_path, monkeypatch):
    """O `claude_desktop_config.json` real tem chaves que não são de servidor.

    Escrever por cima apagaria as preferências do usuário para registrar o nosso.
    """
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "Claude").mkdir()
    alvo = tmp_path / "Claude" / "claude_desktop_config.json"
    alvo.write_text(json.dumps({"preferences": {"tema": "escuro"}}), encoding="utf-8")
    cfg = escrever_config(tmp_path, DUAS_BASES)

    assert main(["--config", str(cfg), "--base", "pessoal", "--cliente", "claude-desktop", "--instalar"]) == 0

    escrito = json.loads(alvo.read_text(encoding="utf-8"))
    assert escrito["preferences"] == {"tema": "escuro"}
    assert "segundocerebro-pessoal" in escrito[CHAVE]


def test_instalar_recusa_cliente_sem_lugar_conhecido(tmp_path, monkeypatch):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    assert main(["--config", str(cfg), "--base", "pessoal", "--cliente", "generico", "--instalar"]) == 2


def test_instalar_recusa_quando_o_cliente_nao_esta_instalado(tmp_path, monkeypatch):
    """Criar a pasta deixaria um arquivo de configuração órfão, sem ninguém avisar."""
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "vazio"))
    cfg = escrever_config(tmp_path, DUAS_BASES)

    assert main(["--config", str(cfg), "--base", "pessoal", "--cliente", "claude-desktop", "--instalar"]) == 2
    assert not (tmp_path / "vazio").exists()


def test_instalar_e_out_nao_se_combinam(tmp_path, monkeypatch):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    argv = ["--config", str(cfg), "--base", "pessoal", "--instalar", "--out", str(tmp_path / "x.json")]
    assert main(argv) == 2


def test_ativar_liga_a_base_no_mcp_do_projeto(tmp_path, monkeypatch):
    """Indexar e esquecer de registrar deixava o assistente cego da base nova."""
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    conf = carregar(cfg)
    destino = tmp_path / ".mcp.json"
    destino.write_text(json.dumps({CHAVE: {"github": {"command": "gh-mcp"}}}), encoding="utf-8")

    saida = ativar(conf.base("trabalho"), conf=conf, destino=destino)

    assert saida == destino
    escrito = json.loads(destino.read_text(encoding="utf-8"))
    assert set(escrito[CHAVE]) == {"github", "segundocerebro-trabalho"}
    entrada = escrito[CHAVE]["segundocerebro-trabalho"]
    assert entrada["args"] == ["-m", "segundocerebro.mcp.server", "--base", "trabalho"]
    assert entrada["command"].replace("\\", "/").endswith("python.exe") or "python" in entrada["command"]


def test_ativar_e_idempotente(tmp_path, monkeypatch):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    conf = carregar(cfg)
    destino = tmp_path / ".mcp.json"
    ativar(conf.base("trabalho"), conf=conf, destino=destino)
    uma = json.loads(destino.read_text(encoding="utf-8"))
    ativar(conf.base("trabalho"), conf=conf, destino=destino)
    assert json.loads(destino.read_text(encoding="utf-8")) == uma


def test_ativar_herda_cuda_do_servidor_ja_registrado(tmp_path, monkeypatch):
    """A base nova neste desktop tem que nascer com o mesmo provider das outras."""
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    monkeypatch.delenv("SEGUNDOCEREBRO_PROVIDER", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    conf = carregar(cfg)
    destino = tmp_path / ".mcp.json"
    destino.write_text(
        json.dumps({
            CHAVE: {
                "segundocerebro-pessoal": {
                    "command": "py",
                    "args": ["-m", "segundocerebro.mcp.server", "--base", "pessoal"],
                    "env": {"PYTHONPATH": "src", "SEGUNDOCEREBRO_PROVIDER": "cuda"},
                }
            }
        }),
        encoding="utf-8",
    )

    ativar(conf.base("trabalho"), conf=conf, destino=destino)

    trabalho = json.loads(destino.read_text(encoding="utf-8"))[CHAVE]["segundocerebro-trabalho"]
    assert trabalho["env"]["SEGUNDOCEREBRO_PROVIDER"] == "cuda"


def test_extra_env_hardware_prefere_a_variavel(monkeypatch):
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cpu")
    assert extra_env_hardware() == {"SEGUNDOCEREBRO_PROVIDER": "cpu"}


def test_gravar_em_recusa_json_invalido(tmp_path):
    alvo = tmp_path / ".mcp.json"
    alvo.write_text("{isto não é json", encoding="utf-8")
    with pytest.raises(ErroDeConfig, match="não é JSON válido"):
        gravar_em(alvo, [Base(id="trabalho")])
    assert alvo.read_text(encoding="utf-8") == "{isto não é json"


def test_python_do_projeto_aponta_o_venv_quando_existe():
    caminho = python_do_projeto(relativo=True)
    assert "python" in caminho.lower()


REPO = Path(__file__).resolve().parent.parent
CONFIG_REAL = REPO / "config.toml"


@pytest.mark.modelo
@pytest.mark.skipif(not CONFIG_REAL.exists(), reason="config.toml ausente (índice real não configurado)")
def test_bloco_do_claude_desktop_sobe_de_um_cwd_neutro():
    """O critério de saída da F3 em forma de teste: o segundo cliente conecta.

    O que isto guarda não é o JSON, é o **modo de falha**. O Claude Desktop nasce
    em `C:\\Windows\\system32`; um bloco com `PYTHONPATH=src` sobe com
    `ModuleNotFoundError` e o cliente mostra "servidor não conecta", que não diz
    nada sobre a causa. Aqui o servidor sobe do mesmo diretório neutro, faz o
    handshake e responde uma consulta real contra o índice real.

    Marcado `modelo` porque carrega o `e5-large` — fora da suíte padrão.
    """
    import asyncio
    import json as _json
    import os

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    saida = subprocess.run(  # argv fixo, interpretador é `sys.executable`
        [sys.executable, "-m", "segundocerebro.mcp.registrar", "--cliente", "claude-desktop"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO / "src"), "PYTHONIOENCODING": "utf-8"},
        check=True,
    )
    entrada = next(iter(_json.loads(saida.stdout)[CHAVE].values()))
    assert Path(entrada["env"]["PYTHONPATH"]).is_absolute()

    neutro = Path(os.environ["SystemRoot"]) / "system32"
    ambiente = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    ambiente.update(entrada["env"])

    async def conversar() -> tuple[list[str], list[dict]]:
        params = StdioServerParameters(
            command=entrada["command"],
            args=entrada["args"],
            env=ambiente,
            cwd=entrada.get("cwd") or str(neutro),
        )
        async with stdio_client(params) as (ler, escrever), ClientSession(ler, escrever) as sessao:
            await sessao.initialize()
            ferramentas = [f.name for f in (await sessao.list_tools()).tools]
            # Consulta deliberadamente genérica e sem nome próprio. O que este
            # teste prova é o cano — handshake, chamada, procedência —, não
            # ranking: a busca densa devolve `k` candidatos para qualquer
            # consulta não vazia. A versão anterior citava duas empresas reais,
            # que é o vazamento que `test_saneamento.py` existe para impedir.
            consulta = "contrato de prestação de serviços"
            r = await sessao.call_tool("search", {"consulta": consulta, "k": 3})
            carga = _json.loads(r.content[0].text)
            return ferramentas, carga["trechos"]

    ferramentas, trechos = asyncio.run(conversar())

    assert {"search", "read_note"} <= set(ferramentas)
    assert trechos, "handshake passou mas a busca não devolveu nada"
    for t in trechos:
        assert t["arquivo"] and t["id"], "invariante 5: procedência e id em todo retorno"


@pytest.mark.parametrize("base_id", ["pessoal", "trabalho"])
def test_o_json_gerado_e_valido_e_completo(tmp_path, capsys, monkeypatch, base_id):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    main(["--config", str(cfg), "--base", base_id])

    entrada = json.loads(capsys.readouterr().out)[CHAVE][f"segundocerebro-{base_id}"]
    assert entrada["command"] == "py"
    assert base_id in entrada["args"]


def test_python_do_venv_entra_no_comando(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    cfg = escrever_config(tmp_path, DUAS_BASES)
    exe = tmp_path / "python.exe"
    exe.write_text("", encoding="utf-8")
    main(["--config", str(cfg), "--base", "trabalho", "--python", str(exe)])
    entrada = json.loads(capsys.readouterr().out)[CHAVE]["segundocerebro-trabalho"]
    assert entrada["command"] == str(exe)
