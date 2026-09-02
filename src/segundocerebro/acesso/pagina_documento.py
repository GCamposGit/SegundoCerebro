"""Fatias exatas do Markdown canônico; cursor é posição, nunca autorização."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import asdict
from hashlib import sha256
from typing import Any

from ..ingest.canonico import ParseCanonico
from ..ingest.estrutura import VERSAO_ESTRUTURA, citar, contrato, validar
from .original import ErroLeitura

MAX_CHARS = 32_000
CHARS_PADRAO = 8_000
MAX_BLOCOS = 200


def decodificar_cursor(cursor: str | None) -> tuple[str, int] | None:
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 256:
            raise ValueError
        dados = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (not isinstance(dados, list) or len(dados) != 3 or dados[0] != "gd:1"
                or not isinstance(dados[1], str) or len(dados[1]) != 64
                or type(dados[2]) is not int or dados[2] <= 0):
            raise ValueError
        return dados[1], dados[2]
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise ErroLeitura("cursor_invalido", "Cursor inválido. Reinicie a leitura sem cursor.") from None


def _cursor(versao: str, inicio: int) -> str:
    dados = json.dumps(["gd:1", versao, inicio], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(dados).decode("ascii")


def paginar(
    canonico: ParseCanonico, identidade: str, *, cursor: str | None, max_chars: int,
) -> dict[str, Any]:
    """Orçamento em code points Unicode, não bytes, tokens ou tamanho do JSON."""
    if type(max_chars) is not int or max_chars < 1:
        raise ErroLeitura("orcamento_invalido", "max_chars deve ser um inteiro positivo.")
    validar(canonico)
    conteudo = json.dumps(asdict(canonico), ensure_ascii=False, sort_keys=True).encode("utf-8")
    versao = sha256(VERSAO_ESTRUTURA.encode() + b"\x00" + identidade.encode("utf-8")
                    + b"\x00" + conteudo).hexdigest()
    continuacao = decodificar_cursor(cursor)
    inicio = continuacao[1] if continuacao else 0
    total = len(canonico.markdown)
    if continuacao and (continuacao[0] != versao or inicio >= total):
        raise ErroLeitura("cursor_desatualizado", "O documento ou a base mudou. Reinicie sem cursor.")
    fim = min(total, inicio + min(max_chars, MAX_CHARS))
    blocos = [(n, b) for n, b in enumerate(canonico.blocos)
              if b.fim > b.inicio and b.fim > inicio and b.inicio < fim]
    if len(blocos) > MAX_BLOCOS:
        fim = blocos[MAX_BLOCOS][1].inicio
        blocos = blocos[:MAX_BLOCOS]
    saida: dict[str, Any] = {
        "markdown": canonico.markdown[inicio:fim], "inicio": inicio, "fim": fim,
        "total": total, "restante": total - fim, "unidade": "caracteres_unicode",
        "restante_chars": total - fim,
        "completo": fim == total, "versao": versao,
        "estrutura": contrato(),
        "blocos": [citar(b, n) for n, b in blocos],
    }
    if fim < total:
        saida["cursor_proximo"] = _cursor(versao, fim)
    return saida
