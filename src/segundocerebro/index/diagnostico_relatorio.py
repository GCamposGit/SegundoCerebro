"""Representação e higienização do relatório operacional FND-08a."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

Severidade = Literal["ok", "aviso", "erro"]
StatusGeral = Literal["saudavel", "atencao", "inoperante"]


@dataclass(frozen=True)
class ItemDiagnostico:
    """Causa operacional, evidência e próxima ação."""

    codigo: str
    severidade: Severidade
    mensagem: str
    acao: str
    escopo: str = "base"
    evidencia: dict[str, Any] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "severidade": self.severidade,
            "mensagem": self.mensagem,
            "acao": self.acao,
            "escopo": self.escopo,
            "evidencia": self.evidencia,
        }


@dataclass
class RelatorioDiagnostico:
    """Resultado estruturado da inspeção de uma base."""

    base: str
    status_geral: StatusGeral
    itens: list[ItemDiagnostico] = field(default_factory=list)
    profundo: bool = False
    duracao_ms: float = 0.0

    def para_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "status_geral": self.status_geral,
            "profundo": self.profundo,
            "duracao_ms": round(self.duracao_ms, 2),
            "itens": [item.para_dict() for item in self.itens],
        }

    def formatar_texto(self) -> str:
        status = {
            "saudavel": "✅ SAUDÁVEL",
            "atencao": "⚠️ ATENÇÃO",
            "inoperante": "❌ INOPERANTE",
        }
        icones = {"ok": "✓", "aviso": "⚠", "erro": "✗"}
        linhas = [
            f"Diagnóstico da base '{self.base}': {status[self.status_geral]} "
            f"({self.duracao_ms:.1f} ms)",
            "-" * 60,
        ]
        for item in self.itens:
            linhas.append(f"  {icones[item.severidade]} [{item.codigo}] {item.mensagem}")
            if item.severidade != "ok" and item.acao:
                linhas.append(f"     Ação: {item.acao}")
        return "\n".join(linhas)

    def exportar_suporte(self) -> str:
        dados = _higienizar(self.para_dict())
        assert isinstance(dados, dict)
        dados["base"] = "<BASE>"
        return json.dumps(dados, indent=2, ensure_ascii=False)


_CHAVE_SENSIVEL = re.compile(
    r"(?:query|consulta|conte[uú]do|content|texto|token|senha|password|secret|authorization)",
    re.IGNORECASE,
)
_CAMINHO_USUARIO = re.compile(
    r"(?i)[a-z]:[\\/]Users[\\/][^\\/]+(?:[\\/][^\"',;\s]+)*"
    r"|/(?:home|Users)/[^/\s]+(?:/[^\"',;\s]+)*"
)
_CAMINHO_LOCAL = re.compile(
    r"(?i)(?:[a-z]:[\\/]|\\\\)[^\"',;\s]+"
    r"|/(?:var|tmp|etc|opt|usr)/[^\"',;\s]+"
)
_SEGREDO = re.compile(
    r"(?i)(?:bearer\s+\S+|sk-[a-z0-9_-]{8,}|"
    r"(?:api[_-]?key|token)\s*[=:]\s*\S+)"
)


def _higienizar(valor: Any, chave: str = "") -> Any:
    if _CHAVE_SENSIVEL.search(chave):
        return "<REMOVIDO>"
    if isinstance(valor, Mapping):
        return {str(k): _higienizar(v, str(k)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_higienizar(v) for v in valor]
    if isinstance(valor, tuple):
        return tuple(_higienizar(v) for v in valor)
    if isinstance(valor, str):
        texto = _SEGREDO.sub("<SEGREDO>", valor)
        texto = _CAMINHO_USUARIO.sub("<DIR_USUARIO>", texto)
        return _CAMINHO_LOCAL.sub("<CAMINHO_LOCAL>", texto)
    return valor


def item(
    codigo: str,
    severidade: Severidade,
    mensagem: str,
    acao: str = "",
    *,
    escopo: str,
    evidencia: dict[str, Any] | None = None,
) -> ItemDiagnostico:
    return ItemDiagnostico(
        codigo=codigo,
        severidade=severidade,
        mensagem=mensagem,
        acao=acao,
        escopo=escopo,
        evidencia=evidencia or {},
    )
