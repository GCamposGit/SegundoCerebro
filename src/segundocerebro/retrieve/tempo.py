"""Conversão e interpretação de filtros temporais (`R6.3`).

Interpreta datas nos formatos ISO (`YYYY`, `YYYY-MM`, `YYYY-MM-DD` ou ISO 8601
completo) e converte em timestamps UNIX UTC (`float`) para filtragem por `mtime`.

Invariantes:
- `depois_de` mapeia para o início inclusivo do período especificado.
- `antes_de` mapeia para o final inclusivo do período especificado (ex: '2023' cobre até 31/12/2023 23:59:59).
- Entradas inválidas ou vazias retornam `None` com segurança (sem estourar exceção).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

PADRAO_ANO = re.compile(r"^\s*(\d{4})\s*$")
PADRAO_ANO_MES = re.compile(r"^\s*(\d{4})-(\d{1,2})\s*$")
PADRAO_DATA = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")


def _inicio_do_ano(ano: int) -> float:
    return datetime(ano, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()


def _fim_do_ano(ano: int) -> float:
    return (datetime(ano + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc) - timedelta(microseconds=1)).timestamp()


def _inicio_do_mes(ano: int, mes: int) -> float:
    return datetime(ano, mes, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()


def _fim_do_mes(ano: int, mes: int) -> float:
    if mes == 12:
        prox = datetime(ano + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        prox = datetime(ano, mes + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return (prox - timedelta(microseconds=1)).timestamp()


def _inicio_do_dia(ano: int, mes: int, dia: int) -> float:
    return datetime(ano, mes, dia, 0, 0, 0, tzinfo=timezone.utc).timestamp()


def _fim_do_dia(ano: int, mes: int, dia: int) -> float:
    return (datetime(ano, mes, dia, 0, 0, 0, tzinfo=timezone.utc) + timedelta(days=1, microseconds=-1)).timestamp()


def _interpretar_inicio(texto: str) -> float | None:
    bruto = (texto or "").strip()
    if not bruto:
        return None
    try:
        m = PADRAO_ANO.match(bruto)
        if m:
            return _inicio_do_ano(int(m.group(1)))
        m = PADRAO_ANO_MES.match(bruto)
        if m:
            return _inicio_do_mes(int(m.group(1)), int(m.group(2)))
        m = PADRAO_DATA.match(bruto)
        if m:
            return _inicio_do_dia(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        dt = datetime.fromisoformat(bruto)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError):
        return None


def _interpretar_fim(texto: str) -> float | None:
    bruto = (texto or "").strip()
    if not bruto:
        return None
    try:
        m = PADRAO_ANO.match(bruto)
        if m:
            return _fim_do_ano(int(m.group(1)))
        m = PADRAO_ANO_MES.match(bruto)
        if m:
            return _fim_do_mes(int(m.group(1)), int(m.group(2)))
        m = PADRAO_DATA.match(bruto)
        if m:
            return _fim_do_dia(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        dt = datetime.fromisoformat(bruto)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError):
        return None


def converter_limites_temporais(
    depois_de: str = "", antes_de: str = ""
) -> tuple[float | None, float | None]:
    """Converte strings ISO em limites temporais [min_mtime, max_mtime]."""
    min_ts = _interpretar_inicio(depois_de) if depois_de else None
    max_ts = _interpretar_fim(antes_de) if antes_de else None
    return min_ts, max_ts
