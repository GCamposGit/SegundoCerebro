"""HTTP em loopback: token, Host e o handshake que o cliente realmente faz.

O stdio já tem `test_protocolo_mcp.py`. Aqui o cano é outro: sem Bearer a
resposta é 401, Host de fora é 421, e com o token o cliente lista as mesmas
ferramentas. Nada disto abre o índice real nem carrega modelo.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from segundocerebro.mcp import http_local
from segundocerebro.mcp.http_local import (
    SessaoHttp,
    gravar_sessao,
    ler_sessao,
    normalizar_host,
    token_confere,
)
from segundocerebro.mcp.server import Recursos, construir, main

FERRAMENTAS = {
    "search",
    "read_note",
    "neighbors",
    "list_folder",
    "outline",
    "get_document",
    "pack_folder",
    "overview",
}
"""A mesma superfície de `test_protocolo_mcp.py`, repetida de propósito.

Um arquivo de teste não importa outro (`Q17`). As duas listas divergirem é o
que faz a ferramenta nova aparecer num cano e faltar no outro.
"""

PROIBIDAS = {"answer", "summarize", "explain", "responder", "resumir", "gerar", "chat"}

REPO = Path(__file__).resolve().parents[1]
TOKEN = "token-de-teste-http"
CONFIG = """
[[base]]
id = "trabalho"
nome = "Acme Holding"
descricao = "Contratos, propostas e atas da Acme Holding"
indice = "indice"
"""


def test_bearer_em_tempo_constante_rejeita_quase() -> None:
    assert token_confere(f"Bearer {TOKEN}", TOKEN)
    assert token_confere(f"bearer {TOKEN}", TOKEN)
    assert not token_confere(f"Bearer {TOKEN}x", TOKEN)
    assert not token_confere(f"Bearer {TOKEN[:-1]}", TOKEN)
    assert not token_confere("Bearer", TOKEN)
    assert not token_confere("", TOKEN)
    assert not token_confere(f"Basic {TOKEN}", TOKEN)
    assert not token_confere("Bearer ", "")


def test_host_publico_rejeita_curinga_e_caminho() -> None:
    assert normalizar_host("Notebook.Tailnet.ts.net.") == "notebook.tailnet.ts.net"
    assert normalizar_host("localhost") == "localhost"
    assert normalizar_host("*") is None
    assert normalizar_host("evil.example/mcp") is None
    assert normalizar_host("a..b") is None
    assert normalizar_host("") is None


def test_sessao_guarda_url_sem_token_e_sem_indice(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("x", encoding="utf-8")
    sessao: SessaoHttp = {
        "porta": 18788,
        "token": TOKEN,
        "url": "http://127.0.0.1:18788/mcp",
        "hosts": ["notebook.tailnet.ts.net"],
        "url_tailscale": "https://notebook.tailnet.ts.net/mcp",
    }
    gravar_sessao(config, sessao)
    texto = (tmp_path / ".mcp-http.json").read_text(encoding="utf-8")
    assert TOKEN not in sessao["url"]
    assert str(tmp_path) not in texto
    assert ler_sessao(config) == sessao
    (tmp_path / ".mcp-http.json").write_text("{", encoding="utf-8")
    assert ler_sessao(config) is None


def test_a_sessao_http_nao_vai_para_o_git() -> None:
    texto = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "\n.mcp-http.json\n" in texto


def test_token_vazio_e_host_curinga_recusam(tmp_path: Path) -> None:
    servidor = construir(Recursos(indice=tmp_path, modelo="e5-large", threads=1))
    config = tmp_path / "config.toml"
    assert (
        http_local.correr(
            servidor, porta=9, token="", hosts=[], config=config, indice=tmp_path
        )
        == 2
    )
    porta = _porta_livre()
    assert (
        http_local.correr(
            servidor, porta=porta, token=TOKEN, hosts=["*"], config=config, indice=tmp_path
        )
        == 2
    )
    assert not (tmp_path / ".mcp-http.json").exists()


def test_nome_tailscale_le_o_dns_desta_maquina(monkeypatch) -> None:
    class _Resultado:
        returncode = 0
        stdout = json.dumps(
            {"Self": {"DNSName": "Notebook.Tailnet.ts.net."}, "Peer": {"x": {"DNSName": "outro"}}}
        )

    monkeypatch.setattr(http_local.shutil, "which", lambda nome: "tailscale")
    monkeypatch.setattr(http_local.subprocess, "run", lambda *args, **kwargs: _Resultado())
    assert http_local.nome_tailscale() == "notebook.tailnet.ts.net"


def test_http_exige_token_recusa_host_estrangeiro_e_completa_o_handshake(tmp_path: Path) -> None:
    from segundocerebro.index.store import Store
    from tests.falsos import DIM

    Store(tmp_path / "indice", DIM).fechar()
    config = tmp_path / "config.toml"
    config.write_text(CONFIG, encoding="utf-8")
    porta = _porta_livre()
    erro = tmp_path / "servidor.log"
    env = {k: v for k, v in os.environ.items() if k != "SEGUNDOCEREBRO_CONFIG"}
    env["PYTHONPATH"] = os.pathsep.join([str(REPO), str(REPO / "src")])
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    saida = erro.open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603 — argv fixo; porta, token e config são do tmp do teste
        [
            sys.executable,
            "-m",
            "segundocerebro.mcp.server",
            "--http",
            "--porta",
            str(porta),
            "--token",
            TOKEN,
            "--config",
            str(config),
            "--base",
            "trabalho",
        ],
        cwd=tmp_path,
        env=env,
        stdout=saida,
        stderr=subprocess.STDOUT,
    )
    try:
        _esperar(porta, proc, erro)
        host = f"127.0.0.1:{porta}"
        assert _status(porta, TOKEN, host) == 200
        assert _status(porta, None, host) == 401
        assert _status(porta, "outro-token", host) == 401
        assert _status(porta, TOKEN, "evil.example") == 421
        locais = _escutando(porta)
        assert locais
        assert all(item.startswith("127.0.0.1:") for item in locais)
        texto = (tmp_path / ".mcp-http.json").read_text(encoding="utf-8")
        assert str(tmp_path / "indice") not in texto
        assert TOKEN not in json.loads(texto)["url"]
        log = erro.read_text(encoding="utf-8", errors="replace")
        assert f"127.0.0.1:{porta}" in log
        assert TOKEN not in log
        inicio, ferramentas = _handshake(porta)
        assert inicio.server_info.name == "segundocerebro-trabalho"
        nomes = {f.name for f in ferramentas.tools}
        assert nomes == FERRAMENTAS
        assert not (nomes & PROIBIDAS)
        assert (
            main(
                [
                    "--http",
                    "--porta",
                    str(porta),
                    "--config",
                    str(config),
                    "--base",
                    "trabalho",
                ]
            )
            == 0
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        saida.close()


def _porta_livre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _status(porta: int, token: str | None, host: str) -> int:
    linhas = ["GET /saude HTTP/1.1", f"Host: {host}", "Connection: close"]
    if token is not None:
        linhas.append(f"Authorization: Bearer {token}")
    mensagem = ("\r\n".join(linhas) + "\r\n\r\n").encode()
    with socket.create_connection(("127.0.0.1", porta), timeout=5) as sock:
        sock.sendall(mensagem)
        dados = b""
        while b"\r\n" not in dados:
            bloco = sock.recv(128)
            if not bloco:
                break
            dados += bloco
    return int(dados.split(b"\r\n", 1)[0].decode().split()[1])


def _esperar(porta: int, proc: subprocess.Popen[str], erro: Path) -> None:
    limite = time.time() + 20
    while time.time() < limite:
        if proc.poll() is not None:
            raise AssertionError(erro.read_text(encoding="utf-8", errors="replace")[-2000:])
        try:
            if _status(porta, TOKEN, f"127.0.0.1:{porta}") == 200:
                return
        except OSError:
            pass
        time.sleep(0.05)
    raise AssertionError(erro.read_text(encoding="utf-8", errors="replace")[-2000:])


def _escutando(porta: int) -> list[str]:
    saida = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True, errors="replace")
    locais: list[str] = []
    for linha in saida.splitlines():
        partes = linha.split()
        if len(partes) < 4 or partes[0] != "TCP":
            continue
        if not partes[1].endswith(f":{porta}"):
            continue
        if "LISTENING" not in linha.upper() and "ESCUTANDO" not in linha.upper():
            continue
        locais.append(partes[1])
    return locais


def _handshake(porta: int):
    url = f"http://127.0.0.1:{porta}/mcp"

    async def _falar():
        async with create_mcp_http_client(headers={"Authorization": f"Bearer {TOKEN}"}) as http:
            async with streamable_http_client(url, http_client=http) as (ler, escrever):
                async with ClientSession(ler, escrever, read_timeout_seconds=20) as sessao:
                    inicio = await sessao.initialize()
                    return inicio, await sessao.list_tools()

    return asyncio.run(_falar())
