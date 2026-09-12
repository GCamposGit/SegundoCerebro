"""Reconcilia o índice com o disco: o que foi apagado e o que foi movido.

O indexador adiciona e atualiza, mas nunca removia. Numa pasta de trabalho viva
— que é a premissa declarada deste acervo — isso acumula documento fantasma:
`search` devolve caminho que não abre, e o trecho fica competindo no ranqueamento
com o arquivo que de fato existe.

Medido em 14/08/2026, depois de uma limpeza de pastas do usuário: **148
documentos fantasma e 7.047 chunks órfãos**, 18% do índice. Dos 148, 66 tinham o
mesmo conteúdo em outro caminho — foram movidos, não apagados.

## A trava que dá sentido ao módulo

Purgar é destrutivo e irreversível sem reindexar. Uma passada interrompida por
hibernação enumera metade do corpus, e purgar sobre isso apagaria a outra
metade. Pior: se o `census.toml` apontar para um disco desconectado, `iter_files`
devolve zero arquivos e a purga ingênua zera o índice inteiro — em silêncio, e
com "sucesso".

Daí três condições, todas necessárias:

1. A enumeração **terminou** — sem interrupção e sem `--limite`.
2. O escopo é explícito: com `prefixo`, só se mexe embaixo dele.
3. A proporção a remover fica abaixo de `LIMITE_SEGURANCA`. Acima disso é
   provável que o problema esteja na configuração, não no disco, e a decisão
   passa a exigir um humano.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..logger import get_logger
from .store import Store

log = get_logger("index.reconciliar")

LIMITE_SEGURANCA = 0.20
"""Fração do escopo que a reconciliação se recusa a remover sozinha.

Não é um número mágico sobre o acervo: é um detector de configuração errada.
Apagar 20% dos documentos de uma vez acontece — a limpeza de 14/08 removeu 8% —
mas passar disso é mais provavelmente raiz errada, unidade desconectada ou
prefixo trocado do que faxina real."""

MINIMO_PARA_TRAVA = 10
"""Abaixo disto a proporção não é evidência de nada, e a trava não se aplica.

Sem este piso, a regra proporcional trava sozinha em índice pequeno: remover 1
documento de 3 é 33%, acima do limite, ainda que 1 documento não possa ser
sintoma de raiz errada. A trava existe para pegar remoção **em massa**, que é o
que configuração errada produz; poucas remoções são faxina por definição."""


@dataclass
class Reconciliacao:
    removidos: list[str] = field(default_factory=list)
    movidos: list[tuple[str, str]] = field(default_factory=list)
    """(caminho antigo, caminho novo) — mesmo sha256 em outro lugar."""
    chunks_removidos: int = 0
    recusada: str = ""
    """Motivo, quando a trava de segurança impediu a purga."""

    @property
    def houve_mudanca(self) -> bool:
        return bool(self.removidos)

    def resumo(self) -> str:
        if self.recusada:
            return f"reconciliação recusada: {self.recusada}"
        if not self.removidos:
            return "índice em dia com o disco"
        partes = [f"{len(self.removidos)} documentos removidos", f"{self.chunks_removidos} chunks"]
        if self.movidos:
            partes.append(f"{len(self.movidos)} deles eram movimentação, não exclusão")
        return " · ".join(partes)


def reconciliar(
    store: Store,
    vistos: set[str],
    *,
    prefixo: str | None = None,
    root_ids: set[str] | None = None,
    completa: bool = True,
    limite_seguranca: float = LIMITE_SEGURANCA,
    forcar: bool = False,
) -> Reconciliacao:
    """Remove do índice o que não existe mais em disco.

    `vistos` são os caminhos que a travessia encontrou nesta passada. `completa`
    diz se ela chegou ao fim — passada interrompida nunca purga, porque a
    ausência de um caminho ali significa "não cheguei lá", não "não existe".
    """
    resultado = Reconciliacao()

    if not completa:
        resultado.recusada = "passada incompleta (interrompida ou com --limite)"
        log.info("reconciliação pulada: %s", resultado.recusada)
        return resultado

    registrados = store.registrados(prefixo, root_ids=root_ids)
    ausentes = [p for p in registrados if p not in vistos]
    if not ausentes:
        return resultado

    fracao = len(ausentes) / max(1, len(registrados))
    if len(ausentes) >= MINIMO_PARA_TRAVA and fracao > limite_seguranca and not forcar:
        resultado.recusada = (
            f"{len(ausentes)} de {len(registrados)} documentos ({fracao:.0%}) sumiram de uma vez, "
            f"acima do limite de {limite_seguranca:.0%}. Isso costuma ser raiz errada, unidade "
            f"desconectada ou prefixo trocado — não faxina. Conferir e, se estiver certo, "
            f"rodar com --forcar-reconciliacao"
        )
        log.error("reconciliação recusada: %s", resultado.recusada)
        return resultado

    # Movido é o mesmo conteúdo em outro caminho. Detectado por sha256, não por
    # nome: nome igual em pasta diferente pode ser coincidência (`Assignment.docx`
    # existe em oito semanas do curso), e conteúdo igual não é.
    por_sha: dict[str, str] = {}
    for caminho in vistos:
        sha = registrados.get(caminho)
        if sha:
            por_sha.setdefault(sha, caminho)

    for chave in sorted(ausentes):
        root_id, separador, caminho = chave.partition("\0")
        if not separador:
            caminho = chave
        sha = registrados.get(chave, "")
        destino = por_sha.get(sha) if sha else None
        if destino:
            _, destino_separador, destino_path = destino.partition("\0")
            resultado.movidos.append(
                (caminho, destino_path if destino_separador else destino)
            )
        resultado.chunks_removidos += store.esquecer_documento(
            caminho,
            root_id=root_id if separador else "",
        )
        resultado.removidos.append(caminho)

    store.commit()
    log.info("%s", resultado.resumo())
    for antigo, novo in resultado.movidos[:20]:
        log.debug("movido: %s -> %s", antigo, novo)
    return resultado
