"""HTTP local do MCP: um processo em loopback, com token, para vários agentes.

O stdio continua o padrão — cada cliente sobe e derruba o próprio processo.
`--http` deixa um só escutando em ``127.0.0.1``. Outra máquina entra por um
proxy que já está na tailnet (Tailscale Serve); este módulo não abre porta
pública e não fala com a OpenAI.

23/09/2026. O painel já trata loopback como insuficiente para trecho de
documento. Este endpoint devolve o mesmo tipo de conteúdo, então o Bearer é
obrigatório: não há modo sem token e não há bind fora de ``127.0.0.1``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..logger import get_logger

log = get_logger("mcp.http")

HOST = "127.0.0.1"
"""Único endereço de escuta. Tailscale Serve faz o proxy até aqui."""

PORTA_PADRAO = 18788
"""Ao lado do painel (18787), para os dois serviços locais não disputarem a porta."""

CAMINHO = "/mcp"
SAUDE = "/saude"
SESSAO = ".mcp-http.json"
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


class SessaoHttp(TypedDict):
    porta: int
    token: str
    url: str
    hosts: list[str]
    url_tailscale: str


def gerar_token() -> str:
    import secrets

    return secrets.token_urlsafe(32)


def token_confere(cabecalho: str, token: str) -> bool:
    """Bearer em tempo constante. Token vazio nunca confere."""
    esquema, separador, apresentado = cabecalho.partition(" ")
    if esquema.lower() != "bearer" or not separador or not token:
        return False
    apresentado = apresentado.strip()
    if not apresentado:
        return False
    return hmac.compare_digest(
        hashlib.sha256(apresentado.encode()).digest(),
        hashlib.sha256(token.encode()).digest(),
    )


def normalizar_host(nome: str) -> str | None:
    """Hostname aceito no cabeçalho Host. Recusa vazio, curinga e caminho."""
    limpo = nome.strip().rstrip(".").lower()
    if not limpo or len(limpo) > 253 or not _HOST.fullmatch(limpo):
        return None
    return limpo


def seguranca(hosts: list[str]) -> TransportSecuritySettings:
    """DNS rebinding: só loopback e os nomes públicos informados."""
    permitidos = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origens = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    for nome in hosts:
        permitidos.append(nome)
        permitidos.append(f"{nome}:*")
        origens.append(f"https://{nome}")
        origens.append(f"https://{nome}:*")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=permitidos,
        allowed_origins=origens,
    )


def caminho_da_sessao(config: Path) -> Path:
    return Path(config).expanduser().resolve().parent / SESSAO


def ler_sessao(config: Path | None) -> SessaoHttp | None:
    if config is None:
        return None
    try:
        dados = json.loads(caminho_da_sessao(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(dados, dict):
        return None
    porta, token = dados.get("porta"), dados.get("token")
    hosts = dados.get("hosts") or []
    if not isinstance(porta, int) or not isinstance(token, str) or not token:
        return None
    if not isinstance(hosts, list) or not all(isinstance(item, str) for item in hosts):
        return None
    url = dados.get("url")
    if not isinstance(url, str) or not url:
        url = f"http://{HOST}:{porta}{CAMINHO}"
    tailscale = dados.get("url_tailscale")
    if not isinstance(tailscale, str):
        tailscale = ""
    return {
        "porta": porta,
        "token": token,
        "url": url,
        "hosts": hosts,
        "url_tailscale": tailscale,
    }


def gravar_sessao(config: Path, sessao: SessaoHttp) -> None:
    alvo = caminho_da_sessao(config)
    payload = {
        "porta": sessao["porta"],
        "token": sessao["token"],
        "url": sessao["url"],
        "hosts": sessao["hosts"],
        "url_tailscale": sessao["url_tailscale"],
    }
    tmp = alvo.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(alvo)


def url_local(porta: int) -> str:
    return f"http://{HOST}:{porta}{CAMINHO}"


def url_da_tailscale(nome: str) -> str:
    return f"https://{nome}{CAMINHO}"


def nome_tailscale() -> str | None:
    """DNSName desta máquina na tailnet, se o cliente Tailscale responder."""
    exe = shutil.which("tailscale")
    if not exe:
        return None
    try:
        bruto = subprocess.run(  # noqa: S603 — argv fixo; o único variável é o executável do PATH
            [exe, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if bruto.returncode != 0 or not bruto.stdout:
        return None
    try:
        dados = json.loads(bruto.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(dados, dict):
        return None
    proprio = dados.get("Self")
    if not isinstance(proprio, dict):
        return None
    dns = proprio.get("DNSName")
    if not isinstance(dns, str):
        return None
    return normalizar_host(dns)


def sondar(porta: int, token: str, timeout: float = 0.4) -> int | None:
    """Status de ``/saude``, ou None se nada escuta."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request as UrlRequest
    from urllib.request import urlopen

    pedido = UrlRequest(
        f"http://{HOST}:{porta}{SAUDE}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urlopen(pedido, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200))
    except HTTPError as erro:
        return int(erro.code)
    except (URLError, TimeoutError, OSError):
        return None


def registrar_saude(servidor: MCPServer) -> None:
    @servidor.custom_route(SAUDE, methods=["GET"], include_in_schema=False)
    async def saude(_pedido: Request) -> JSONResponse:
        return JSONResponse({"ok": True})


class _PortaLocal:
    """Bearer e Host em toda rota HTTP. Lifespan passa direto."""

    def __init__(self, app: ASGIApp, token: str, ajustes: TransportSecuritySettings) -> None:
        self._app = app
        self._token = token
        self._rede = TransportSecurityMiddleware(ajustes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        pedido = Request(scope, receive)
        erro = await self._rede.validate_request(pedido, is_post=scope.get("method") == "POST")
        if erro is not None:
            await erro(scope, receive, send)
            return
        cabecalho = Headers(scope=scope).get("authorization", "")
        if not token_confere(cabecalho, self._token):
            recusa = PlainTextResponse(
                "token inválido",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await recusa(scope, receive, send)
            return
        await self._app(scope, receive, send)


def aplicacao(servidor: MCPServer, token: str, hosts: list[str]) -> ASGIApp:
    registrar_saude(servidor)
    bruto = servidor.streamable_http_app(
        streamable_http_path=CAMINHO,
        host=HOST,
        transport_security=seguranca(hosts),
    )
    return _PortaLocal(bruto, token, seguranca(hosts))


def _juntar_hosts(salvos: list[str], pedidos: list[str], detectado: str | None) -> tuple[list[str], str | None]:
    saida: list[str] = []
    for bruto in [*salvos, *([detectado] if detectado else [])]:
        nome = normalizar_host(bruto) if bruto else None
        if nome and nome not in saida:
            saida.append(nome)
    for bruto in pedidos:
        nome = normalizar_host(bruto)
        if nome is None:
            return [], bruto
        if nome not in saida:
            saida.append(nome)
    return saida, None


def _credenciais(
    porta: int | None,
    token: str | None,
    sessao: SessaoHttp | None,
) -> tuple[int, str] | str:
    porta_final = PORTA_PADRAO if porta is None else porta
    if not 1 <= porta_final <= 65535:
        return "porta fora de 1–65535"
    if token is not None:
        if not token:
            return "token vazio"
        return porta_final, token
    if sessao is not None and sessao["porta"] == porta_final:
        return porta_final, sessao["token"]
    return porta_final, gerar_token()


def _ancora(config: Path | None, indice: Path) -> Path:
    """Arquivo cuja pasta guarda ``.mcp-http.json``. O nome em si não é lido."""
    if config is not None:
        return Path(config).expanduser().resolve()
    return Path(indice).expanduser().resolve().parent / "config.toml"


def correr(
    servidor: MCPServer,
    *,
    porta: int | None,
    token: str | None,
    hosts: list[str],
    config: Path | None,
    indice: Path,
) -> int:
    """Sobe o HTTP, ou sai 0 se esta porta já responde com o mesmo token."""
    ancora = _ancora(config, indice)
    sessao = ler_sessao(ancora)
    credenciais = _credenciais(porta, token, sessao)
    if isinstance(credenciais, str):
        log.error("%s", credenciais)
        return 2
    porta_final, token_final = credenciais
    estado = sondar(porta_final, token_final)
    if estado == 200:
        log.info("MCP HTTP já responde em %s", url_local(porta_final))
        return 0
    if estado is not None:
        log.error("a porta %s está ocupada (HTTP %s) e não aceitou este token", porta_final, estado)
        return 2
    detectado = nome_tailscale()
    salvos = sessao["hosts"] if sessao is not None else []
    nomes, recusado = _juntar_hosts(salvos, hosts, detectado)
    if recusado is not None:
        log.error("host recusado: %s", recusado)
        return 2
    url = url_local(porta_final)
    tailscale = url_da_tailscale(detectado) if detectado else ""
    gravar_sessao(
        ancora,
        {"porta": porta_final, "token": token_final, "url": url, "hosts": nomes, "url_tailscale": tailscale},
    )
    if nomes:
        log.info("Host adicional aceito: %s", ", ".join(nomes))
    log.info("MCP HTTP em %s", url)
    return _servir(aplicacao(servidor, token_final, nomes), porta_final)


def _servir(app: ASGIApp, porta: int) -> int:
    import uvicorn

    try:
        uvicorn.run(app, host=HOST, port=porta, log_level="warning")
    except OSError as erro:
        log.error("não foi possível escutar em %s:%s (%s)", HOST, porta, erro)
        return 2
    return 0
