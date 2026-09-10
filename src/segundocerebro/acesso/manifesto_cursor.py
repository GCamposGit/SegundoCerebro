"""Cursor opaco de list_folder com revisão do manifesto (FND-04).

O inteiro legado continua válido e sem garantia de snapshot. O cursor novo
carrega a revisão da enumeração: inserção, exclusão, rename ou mudança de
status entre páginas recusa a continuação em vez de devolver página incoerente.
"""

from __future__ import annotations

import base64
import binascii
import json
from hashlib import sha256
from .original import ErroLeitura
from .registro import Documento, normalizar_prefixo

CURSOR_MAX = 256


def revisao(
    base: str,
    pasta: str,
    recursivo: bool,
    documentos: list[Documento],
    falhas_censo: int,
) -> str:
    """Impressão estável: raiz, caminho, status e identidade, não caminho absoluto."""
    corpo = {
        "base": base,
        "pasta": normalizar_prefixo(pasta),
        "recursivo": bool(recursivo),
        "ordem": "caminho,raiz",
        "censo_falhas": int(falhas_censo),
        "docs": [
            (d.raiz, d.caminho, d.status, d.sha256, d.mtime, d.tamanho)
            for d in documentos
        ],
    }
    texto = json.dumps(corpo, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(texto.encode("utf-8")).hexdigest()


def emitir(revisao_atual: str, posicao: int) -> str:
    dados = json.dumps(["lf:1", revisao_atual, posicao], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(dados).decode("ascii")


def _opaco(cursor: str) -> tuple[int, str]:
    try:
        if not 1 <= len(cursor) <= CURSOR_MAX:
            raise ValueError
        dados = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(dados, list)
            or len(dados) != 3
            or dados[0] != "lf:1"
            or not isinstance(dados[1], str)
            or len(dados[1]) != 64
            or type(dados[2]) is not int
            or dados[2] < 0
        ):
            raise ValueError
        return dados[2], dados[1]
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        raise ErroLeitura(
            "cursor_invalido",
            "Cursor inválido. Reinicie o list_folder sem cursor.",
        ) from None


def interpretar(cursor: object) -> tuple[int, str | None]:
    """Posição e revisão esperada. Revisão None = legado, sem conferência."""
    if cursor is None:
        return 0, None
    if type(cursor) is int:
        if cursor < 0:
            raise ErroLeitura("cursor_invalido", "Cursor inválido. Reinicie o list_folder sem cursor.")
        return cursor, None
    if type(cursor) is str:
        if cursor in {"", "0"}:
            return 0, None
        if cursor.isdigit():
            return int(cursor), None
        return _opaco(cursor)
    raise ErroLeitura("cursor_invalido", "Cursor inválido. Reinicie o list_folder sem cursor.")


def conferir(esperada: str | None, atual: str) -> None:
    if esperada is not None and esperada != atual:
        raise ErroLeitura(
            "cursor_desatualizado",
            "A pasta mudou desde a página anterior. Reinicie o list_folder sem cursor.",
        )


def flag_opaco(valor: object) -> bool:
    if type(valor) is not bool:
        raise ErroLeitura("cursor_invalido", "cursor_opaco deve ser true ou false.")
    return valor
