"""Consulta agregada da base de conhecimento — visão geral para orientação (`R7.1`).

Produz uma visão estruturada e rápida (<200 ms) do acervo a partir do registro
SQLite: contagem de documentos e trechos, período temporal coberto, distribuição
de formatos, principais pastas de primeiro nível, taxa de indexação e status de OCR.

Invariantes deste módulo:
- Read-only e barato: agregação SQL sobre `documentos` e `quarentena`, sem abrir arquivos.
- Nunca expõe caminhos absolutos: apenas pastas relativas e extensões.
- Não gera texto: dados brutos estruturados para consumo por agentes LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..index.store import Store


def _iso_data(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def _extensao(caminho: str) -> str:
    nome = caminho.rsplit("/", 1)[-1]
    if "." in nome:
        return "." + nome.rsplit(".", 1)[-1].lower()
    return "(sem extensão)"


def _pasta_raiz(caminho: str) -> str:
    partes = caminho.split("/")
    if len(partes) > 1:
        return partes[0]
    return "(raiz)"


def _contar_quarentena(store: Store) -> int:
    try:
        cur = store.con.execute("SELECT COUNT(*) as q_total FROM quarentena")
        row = cur.fetchone()
        return int(row["q_total"]) if row else 0
    except Exception:  # noqa: BLE001
        return 0


def _distribuicao_formatos_e_pastas(
    store: Store, total_docs: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contagem_formatos: dict[str, int] = {}
    contagem_pastas: dict[str, int] = {}

    if total_docs > 0:
        for row in store.con.execute("SELECT path FROM documentos"):
            p = row["path"]
            ext = _extensao(p)
            contagem_formatos[ext] = contagem_formatos.get(ext, 0) + 1
            pasta = _pasta_raiz(p)
            contagem_pastas[pasta] = contagem_pastas.get(pasta, 0) + 1

    top_formatos = [
        {"extensao": ext, "documentos": qtd}
        for ext, qtd in sorted(contagem_formatos.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    ]
    top_pastas = [
        {"pasta": pasta, "documentos": qtd}
        for pasta, qtd in sorted(contagem_pastas.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    ]
    return top_formatos, top_pastas


def resumo_base(store: Store, base_id: str = "") -> dict[str, Any]:
    """Gera o resumo estruturado dos documentos presentes no registro."""
    cur = store.con.execute(
        """
        SELECT
            COUNT(*) as total_documentos,
            COALESCE(SUM(n_chunks), 0) as total_chunks,
            MIN(mtime) as min_mtime,
            MAX(mtime) as max_mtime,
            COALESCE(SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END), 0) as ok,
            COALESCE(SUM(CASE WHEN status = 'vazio' THEN 1 ELSE 0 END), 0) as vazio,
            COALESCE(SUM(CASE WHEN status = 'erro' THEN 1 ELSE 0 END), 0) as erro,
            COALESCE(SUM(CASE WHEN digitalizado = 1 THEN 1 ELSE 0 END), 0) as digitalizados,
            COALESCE(SUM(CASE WHEN digitalizado = 1 AND (status != 'ok' OR n_chunks = 0) THEN 1 ELSE 0 END), 0) as ocr_pendente
        FROM documentos
        """
    )
    linha = cur.fetchone()
    total_docs = int(linha["total_documentos"]) if linha else 0
    total_chunks = int(linha["total_chunks"]) if linha else 0
    min_mtime = float(linha["min_mtime"]) if linha and linha["min_mtime"] is not None else None
    max_mtime = float(linha["max_mtime"]) if linha and linha["max_mtime"] is not None else None
    ok = int(linha["ok"]) if linha else 0
    vazio = int(linha["vazio"]) if linha else 0
    erro = int(linha["erro"]) if linha else 0
    digitalizados = int(linha["digitalizados"]) if linha else 0
    ocr_pendente = int(linha["ocr_pendente"]) if linha else 0

    top_formatos, top_pastas = _distribuicao_formatos_e_pastas(store, total_docs)
    taxa = round(ok / total_docs, 4) if total_docs > 0 else 0.0

    return {
        "base": base_id or "",
        "documentos_total": total_docs,
        "chunks_total": total_chunks,
        "periodo": {
            "mais_antigo": _iso_data(min_mtime),
            "mais_recente": _iso_data(max_mtime),
        },
        "status": {
            "indexado": ok,
            "sem_texto": vazio,
            "erro": erro,
            "quarentena": _contar_quarentena(store),
            "taxa_indexacao": taxa,
        },
        "formatos": top_formatos,
        "pastas_raiz": top_pastas,
        "digitalizado": {
            "total": digitalizados,
            "ocr_pendente": ocr_pendente,
        },
    }
