"""O que uma passada de indexação relata quando termina.

Saiu de `indexer.py` em 29/08/2026. `Progresso` é lido pelo painel, pelo watcher
e pela suíte, e é a única parte daquele arquivo que atravessa a fronteira do
módulo — separá-la é o que permite importar o resultado sem importar o laço.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .reconciliar import Reconciliacao


class PedidoDeParada(RuntimeError):
    """Cancel or Ctrl+C during embed — the document in flight is not committed."""


@dataclass
class Progresso:
    documentos: int = 0
    pulados: int = 0
    inalterados: int = 0
    indexados: int = 0
    chunks: int = 0
    quarentena: int = 0
    ocr: int = 0
    parse_store_consultas: int = 0
    parse_store_hits: int = 0
    falhas: dict[str, int] = field(default_factory=dict)
    segundos: float = 0.0
    interrompido: bool = False
    reconciliacao: Reconciliacao | None = None
    cobertura: dict[str, int] = field(default_factory=dict)

    def registrar_falha(self, status: str) -> None:
        self.falhas[status] = self.falhas.get(status, 0) + 1

    def registrar_parse_store(self, resultado) -> None:  # noqa: ANN001
        if not resultado.parse_store_consultado:
            return
        self.parse_store_consultas += 1
        self.parse_store_hits += int(resultado.parse_store_hit)

    def resumo(self) -> str:
        partes = [
            f"{self.documentos} documentos vistos",
            f"{self.pulados} já indexados",
            f"{self.inalterados} com conteúdo inalterado",
            f"{self.indexados} processados",
            f"{self.chunks} chunks",
        ]
        if self.ocr:
            partes.append(f"{self.ocr} via OCR")
        if self.parse_store_consultas:
            taxa = 100 * self.parse_store_hits / self.parse_store_consultas
            partes.append(
                f"parse store {taxa:.0f}% ({self.parse_store_hits}/{self.parse_store_consultas})"
            )
        if self.quarentena:
            partes.append(f"{self.quarentena} em quarentena")
        if self.falhas:
            partes.append("falhas: " + ", ".join(f"{k}={v}" for k, v in sorted(self.falhas.items())))
        if self.reconciliacao is not None and (self.reconciliacao.houve_mudanca or self.reconciliacao.recusada):
            partes.append(self.reconciliacao.resumo())
        partes.append(f"{self.segundos:.0f}s")
        return " · ".join(partes)
