"""Validação de identidade de entrada na indexação — recusa de colisões de caminho relativo.

FND-01a (revisão de fundamentos de 04/09/2026, P0 de integridade).
Impede que caminhos relativos duplicados em múltiplas raízes ou conflitos
com raízes já registradas no Store sobrescrevam documentos silenciosamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import ErroDeConfig

if TYPE_CHECKING:
    from collections.abc import Sequence
    from ..census import FileEntry, RootSpec
    from .store import Store


class ColisaoDeCaminho(ErroDeConfig):
    """Recusa da passada de indexação devido a colisão de caminhos relativos entre raízes."""

    def __init__(self, mensagem: str, conflitos: Sequence[ConflitoDeCaminho] | None = None) -> None:
        super().__init__(mensagem)
        self.conflitos = tuple(conflitos or ())


@dataclass(frozen=True)
class ConflitoDeCaminho:
    """Representa uma colisão de caminho relativo detectada na pré-enumeração."""

    caminho_rel: str
    raizes: tuple[str, ...]
    origem: str  # "passada" (intra-censo) ou "indice" (inter-passada contra Store)
    detalhe: str = ""


def _rotulo_raiz(root: RootSpec, todos: Sequence[RootSpec]) -> str:
    """Nome da raiz para exibição; inclui o caminho se houver nomes repetidos."""
    nomes = [r.name for r in todos]
    if nomes.count(root.name) > 1:
        return f"{root.name} ({root.path})"
    return root.name


def formatar_mensagem_colisao(conflitos: Sequence[ConflitoDeCaminho]) -> str:
    """Mensagem de erro acionável nomeando raízes, caminho e mitigação."""
    if not conflitos:
        return "nenhuma colisão de caminho detectada"

    primeiro = conflitos[0]
    raizes_formatadas = ", ".join(repr(r) for r in primeiro.raizes)

    if primeiro.origem == "indice":
        raiz_atual = repr(primeiro.raizes[0])
        raiz_indice = repr(primeiro.raizes[1])
        base_msg = (
            f"recusando indexar por colisão de caminho: '{primeiro.caminho_rel}' na raiz {raiz_atual} "
            f"colide com a raiz {raiz_indice} já registrada no índice"
        )
    else:
        base_msg = (
            f"recusando indexar por colisão de caminho: '{primeiro.caminho_rel}' aparece "
            f"em múltiplas raízes configuradas ({raizes_formatadas})"
        )

    if len(conflitos) > 1:
        base_msg += f" (e mais {len(conflitos) - 1} arquivo(s) em conflito)"

    mitigacao = (
        ". Cada base de dados aceita caminhos relativos únicos; "
        "separe as pastas em bases distintas no config.toml para evitar sobrescrita acidental."
    )
    return base_msg + mitigacao


def _colisoes_na_passada(
    enumerados: Sequence[tuple[RootSpec, Sequence[FileEntry]]],
    todas_raizes: Sequence[RootSpec],
) -> list[ConflitoDeCaminho]:
    """Detecta caminhos relativos duplicados entre raízes na mesma passada."""
    ocorrencias: dict[str, list[RootSpec]] = {}
    for root, arquivos in enumerados:
        vistos_nesta_raiz: set[str] = set()
        for arquivo in arquivos:
            rel = arquivo.rel
            if rel in vistos_nesta_raiz:
                continue
            vistos_nesta_raiz.add(rel)
            ocorrencias.setdefault(rel, []).append(root)

    conflitos: list[ConflitoDeCaminho] = []
    for rel, roots in ocorrencias.items():
        if len(roots) > 1:
            rotulos = tuple(_rotulo_raiz(r, todas_raizes) for r in roots)
            conflitos.append(
                ConflitoDeCaminho(
                    caminho_rel=rel,
                    raizes=rotulos,
                    origem="passada",
                    detalhe=f"caminho relativo '{rel}' encontrado em {len(roots)} raízes distintas",
                )
            )
    return conflitos


def _colisoes_no_indice(
    enumerados: Sequence[tuple[RootSpec, Sequence[FileEntry]]],
    store: Store,
    todas_raizes: Sequence[RootSpec],
    caminhos_ignorados: set[str],
    prefixo: str | None = None,
) -> list[ConflitoDeCaminho]:
    """Detecta se arquivos da passada colidem com raízes gravadas anteriormente no Store."""
    try:
        if prefixo:
            cur = store.con.execute(
                "SELECT path, raiz FROM documentos WHERE path LIKE ? || '%'",
                (prefixo,),
            )
        else:
            cur = store.con.execute("SELECT path, raiz FROM documentos")
        registrados = {str(row["path"]): str(row["raiz"]) for row in cur}
    except Exception:  # noqa: BLE001 — tabela documentos pode ainda não existir em banco novo
        return []

    if not registrados:
        return []

    conflitos: list[ConflitoDeCaminho] = []
    vistos_conflito = set(caminhos_ignorados)
    for root, arquivos in enumerados:
        rotulo_atual = _rotulo_raiz(root, todas_raizes)
        for arquivo in arquivos:
            rel = arquivo.rel
            if rel in vistos_conflito:
                continue
            raiz_gravada = registrados.get(rel)
            if raiz_gravada is not None and raiz_gravada != root.name:
                conflitos.append(
                    ConflitoDeCaminho(
                        caminho_rel=rel,
                        raizes=(rotulo_atual, raiz_gravada),
                        origem="indice",
                        detalhe=(
                            f"caminho relativo '{rel}' na raiz '{root.name}' "
                            f"colide com raiz '{raiz_gravada}' pré-existente no Store"
                        ),
                    )
                )
                vistos_conflito.add(rel)
    return conflitos


def detectar_colisoes(
    enumerados: Sequence[tuple[RootSpec, Sequence[FileEntry]]],
    store: Store | None = None,
    *,
    prefixo: str | None = None,
) -> list[ConflitoDeCaminho]:
    """Detecta se há caminhos relativos duplicados entre raízes ou contra o índice existente."""
    todas_raizes = [root for root, _ in enumerados]
    conflitos = _colisoes_na_passada(enumerados, todas_raizes)
    if store is not None:
        ignorados = {c.caminho_rel for c in conflitos}
        conflitos.extend(
            _colisoes_no_indice(enumerados, store, todas_raizes, ignorados, prefixo=prefixo)
        )
    return conflitos


def conferir_colisoes(
    enumerados: Sequence[tuple[RootSpec, Sequence[FileEntry]]],
    store: Store | None = None,
    *,
    prefixo: str | None = None,
    execucao: int | None = None,
) -> None:
    """Valida colisões de caminhos; encerra a execução como recusada e levanta ColisaoDeCaminho."""
    colisoes = detectar_colisoes(enumerados, store, prefixo=prefixo)
    if not colisoes:
        return
    if store is not None and execucao is not None:
        store.encerrar_execucao(execucao, 0, 0, "recusada")
    raise ColisaoDeCaminho(formatar_mensagem_colisao(colisoes), conflitos=colisoes)
