"""As consultas de leitura da camada de acesso — enumerar e mapear, não ranquear.

Por que não em `index/store.py`: aquele módulo está na escada de
`tests/test_tamanho_dos_modulos.py`, cuja tabela **só desce**, e estas consultas
têm razão de mudar própria — a superfície de leitura do pacote J, não o laço de
indexação. Elas recebem o `Store` aberto e usam a conexão dele; a fronteira é a
mesma que `retrieve/` já tem com o registro.

Nada aqui ranqueia. Enumeração é estável e neutra por decisão do pacote J
(anti-recomendação 6): relevância é trabalho do `search`, e misturar as duas
torna o manifesto não-reprodutível — que é exatamente o que um workflow agêntico
semanal não pode ter.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..index.store import Store
from ..index.ocorrencia import CaminhoAmbiguo
from ..retrieve.familias import por_vigencia
from .identidade import Referencia, doc_id_de, faixa_de_prefixo, motivo_sem_id, preferido

CAMPOS = (
    "path, raiz, tamanho, mtime, sha256, status, n_chunks, parser, indexado_em, "
    "familia_real, digitalizado, paginas"
)

LOTE_DE_PARAMETROS = 500
"""Quantos valores cabem num `IN (...)` antes de a consulta ser quebrada em duas.

O SQLite tem teto de parâmetros por statement — 999 nas bibliotecas antigas, e a
build que roda aqui não é escolha nossa. Uma consulta em lote sobre uma pasta de
2.156 documentos estoura esse teto com `too many SQL variables`, e o defeito é
invisível no índice de quatro trechos da suíte: é o **inverso** do N+1 deste
repositório, onde a forma do acesso era a mesma e só o N mudava. Aqui a forma
está certa e só o N quebra, o que dá no mesmo — o teste tem de ter N grande.
"""


def _em_lotes(itens: Sequence[str], tamanho: int = LOTE_DE_PARAMETROS) -> Iterable[Sequence[str]]:
    for inicio in range(0, len(itens), tamanho):
        yield itens[inicio : inicio + tamanho]


@dataclass(frozen=True)
class Documento:
    """Um documento do registro, já com identidade pública resolvida."""

    caminho: str
    """O caminho preferido — `identidade.preferido` decide entre os N do mesmo conteúdo."""
    caminhos: tuple[str, ...] = ()
    """Todos os caminhos com este conteúdo, da versão vigente para a mais antiga."""
    doc_id: str = ""
    sem_id: str = ""
    """Por que não há `doc_id`, em português. Preenchido só quando `doc_id` é vazio."""
    sha256: str = ""
    raiz: str = ""
    tamanho: int = 0
    mtime: float = 0.0
    status: str = ""
    n_chunks: int = 0
    parser: str = ""
    indexado_em: str = ""
    familia_real: str = ""
    digitalizado: bool = False
    paginas: int = 0
    root_id: str = ""
    ocorrencia_id: str = ""

    @property
    def duplicado(self) -> bool:
        return len(self.caminhos) > 1


@dataclass(frozen=True)
class Secao:
    """Um trecho do mapa de um documento: onde está, quanto ocupa, por onde ler."""

    trilha: str
    onde: str = ""
    chars: int = 0
    trechos: int = 0
    primeiro_id: str = ""
    ordinal: int = 0


@dataclass
class Pasta:
    """O que o registro sabe de uma pasta, antes de virar manifesto."""

    prefixo: str
    documentos: list[Documento] = field(default_factory=list)
    quarentena: dict[str, str] = field(default_factory=dict)


def _linha_para_documento(linha, caminhos: Sequence[str]) -> Documento:  # noqa: ANN001
    sha = str(linha["sha256"] or "")
    doc_id = doc_id_de(sha)
    return Documento(
        caminho=str(linha["path"]),
        caminhos=tuple(caminhos) or (str(linha["path"]),),
        doc_id=doc_id or "",
        sem_id="" if doc_id else motivo_sem_id(str(linha["status"] or "")),
        sha256=sha,
        raiz=str(linha["raiz"] or ""),
        tamanho=int(linha["tamanho"] or 0),
        mtime=float(linha["mtime"] or 0.0),
        status=str(linha["status"] or ""),
        n_chunks=int(linha["n_chunks"] or 0),
        parser=str(linha["parser"] or ""),
        indexado_em=str(linha["indexado_em"] or ""),
        familia_real=str(linha["familia_real"] or ""),
        digitalizado=bool(linha["digitalizado"]),
        paginas=int(linha["paginas"] or 0),
        root_id=(str(linha["root_id"] or "") if "root_id" in linha.keys() else str(linha["raiz"] or "")),
        ocorrencia_id=(str(linha["ocorrencia_id"] or "") if "ocorrencia_id" in linha.keys() else ""),
    )


def _campos(store: Store) -> str:
    if store._usa_ocorrencia():
        return (
            "path, root_id, ocorrencia_id, raiz, tamanho, mtime, sha256, status, n_chunks, parser, indexado_em, "
            "familia_real, digitalizado, paginas"
        )
    return CAMPOS


def _linhas_doc_id(store: Store, doc_id: str, root_id: str = "") -> list:
    inicio, fim = faixa_de_prefixo(doc_id)
    sql = f"SELECT {_campos(store)} FROM documentos WHERE sha256 >= ? AND sha256 < ?"
    params: list[object] = [inicio, fim]
    if root_id and store._usa_ocorrencia():
        sql += " AND root_id = ?"
        params.append(root_id)
    return list(store.con.execute(sql, params))


def caminhos_de_doc_id(store: Store, doc_id: str) -> list[str]:
    """Todos os caminhos cujo conteúdo tem este id, em ordem de vigência.

    A consulta é por **faixa** de prefixo, não por `LIKE`, para usar
    `idx_documentos_sha256` sem depender de PRAGMA — ver
    `identidade.faixa_de_prefixo`.
    """
    if not doc_id:
        return []
    linhas = _linhas_doc_id(store, doc_id)
    if not linhas:
        return []
    mtimes = {
        f"{str(l['root_id'])}\0{str(l['path'])}" if "root_id" in l.keys() else str(l["path"]): float(l["mtime"] or 0.0)
        for l in linhas
    }
    return [chave.split("\0", 1)[-1] for chave in por_vigencia(sorted(mtimes), mtimes)]


def irmaos_de_conteudo(store: Store, sha256: str) -> list[str]:
    """Os caminhos byte-idênticos a este, em ordem de vigência. 10,5% do acervo."""
    if not sha256:
        return []
    linhas = store.con.execute(
        "SELECT path, mtime FROM documentos WHERE sha256 = ?", (sha256,)
    ).fetchall()
    mtimes = {
        f"{str(l['root_id'])}\0{str(l['path'])}" if "root_id" in l.keys() else str(l["path"]): float(l["mtime"] or 0.0)
        for l in linhas
    }
    ordenados = por_vigencia(sorted(mtimes), mtimes) if len(mtimes) > 1 else list(mtimes)
    return [chave.split("\0", 1)[-1] for chave in ordenados]


def documento_de_caminho(
    store: Store, caminho: str, *, root_id: str = "", ocorrencia_id: str = ""
) -> Documento | None:
    campos = _campos(store)
    if store._usa_ocorrencia():
        if ocorrencia_id:
            linhas = store.con.execute(
                f"SELECT {campos} FROM documentos WHERE ocorrencia_id = ?", (ocorrencia_id,)
            ).fetchall()
        elif root_id:
            linhas = store.con.execute(
                f"SELECT {campos} FROM documentos WHERE root_id = ? AND path = ?",
                (root_id, caminho),
            ).fetchall()
        else:
            linhas = store.con.execute(
                f"SELECT {campos} FROM documentos WHERE path = ? ORDER BY root_id", (caminho,)
            ).fetchall()
            if len(linhas) > 1:
                raise CaminhoAmbiguo(
                    f"o caminho relativo '{caminho}' existe em mais de uma raiz; "
                    "informe root_id ou use o id/URI"
                )
    else:
        linhas = store.con.execute(
            f"SELECT {campos} FROM documentos WHERE path = ?", (caminho,)
        ).fetchall()
    if not linhas:
        return None
    linha = linhas[0]
    return _linha_para_documento(linha, irmaos_de_conteudo(store, str(linha["sha256"] or "")))


def resolver(store: Store, referencia: Referencia) -> Documento | None:
    """`Referencia` → documento, por id ou por caminho, com o preferido decidido.

    Um id que resolve para N caminhos devolve **um** documento — o preferido —
    com os outros em `caminhos`. Devolver N deixaria o cliente escolhendo por
    conta própria, que é a aleatoriedade que o `J.b1` existe para fechar.
    """
    if referencia.doc_id:
        linhas = _linhas_doc_id(store, referencia.doc_id, referencia.root_id)
        if not linhas:
            return None
        chaves = [
            f"{str(l['root_id'])}\0{str(l['path'])}" if "root_id" in l.keys() else str(l["path"])
            for l in linhas
        ]
        mtimes = {chave: float(linhas[i]["mtime"] or 0.0) for i, chave in enumerate(chaves)}
        escolhido = preferido(chaves, mtimes)
        linha = next(l for i, l in enumerate(linhas) if chaves[i] == escolhido)
        caminhos = [chave.split("\0", 1)[-1] for chave in por_vigencia(sorted(chaves), mtimes)]
        return _linha_para_documento(linha, caminhos)
    if referencia.caminho:
        return documento_de_caminho(store, referencia.caminho, root_id=referencia.root_id)
    return None


def _mtimes(store: Store, caminhos: Sequence[str]) -> dict[str, float]:
    saida: dict[str, float] = {}
    for lote in _em_lotes(caminhos):
        marcas = ",".join("?" * len(lote))
        linhas = store.con.execute(
            f"SELECT path, mtime FROM documentos WHERE path IN ({marcas})", tuple(lote)
        )
        saida.update({str(l["path"]): float(l["mtime"] or 0.0) for l in linhas})
    return saida


def estrutura_de(
    store: Store, caminho: str, *, root_id: str = "", ocorrencia_id: str = ""
) -> list[Secao]:
    """O mapa do documento: uma entrada por trilha de headings, na ordem do texto.

    Sai de `chunks.trilha` + `chunks.locator` + `ordinal`, que já estão indexados
    por `path` — nenhum byte do documento é lido e nenhum parser roda. É a razão
    de `outline` não esperar o parse store (`docs/plano-pacote-j.md` §3.5).

    Trechos consecutivos da mesma trilha viram **uma** seção: o chunker corta por
    orçamento dentro de uma seção, e devolver os cortes exporia a régua do
    chunker como se fosse a estrutura do documento.

    `chars` é caractere, não token, e o nome do campo diz isso. O tokenizador
    real vive no encoder, e carregá-lo aqui trocaria uma tool de mapa barata por
    uma que custa 80 s na primeira chamada. Número que circula sem unidade vira
    três números — foi o que aconteceu com a cobertura do dourado.
    """
    if store._usa_ocorrencia() and (root_id or ocorrencia_id):
        from ..index.ocorrencia import id_de

        chave = ocorrencia_id or id_de(root_id, caminho)
        linhas = store.con.execute(
            "SELECT id, ordinal, trilha, locator, chars FROM chunks "
            "WHERE ocorrencia_id = ? ORDER BY ordinal", (chave,)
        ).fetchall()
        # Low-level Store callers from before FND-01b have chunks owned by the
        # path itself. Keep those snapshots readable without weakening the
        # scoped lookup for real occurrence-owned rows.
        if not linhas:
            compat = store.con.execute(
                "SELECT 1 FROM chunks WHERE path = ? "
                "AND (ocorrencia_id = '' OR ocorrencia_id = path) LIMIT 1",
                (caminho,),
            ).fetchone()
            if compat:
                linhas = store.con.execute(
                    "SELECT id, ordinal, trilha, locator, chars FROM chunks "
                    "WHERE path = ? ORDER BY ordinal", (caminho,)
                ).fetchall()
    else:
        linhas = store.con.execute(
            "SELECT id, ordinal, trilha, locator, chars FROM chunks WHERE path = ? ORDER BY ordinal",
            (caminho,),
        ).fetchall()

    secoes: list[Secao] = []
    for linha in linhas:
        trilha = str(linha["trilha"] or "")
        onde = str(linha["locator"] or "")
        if secoes and secoes[-1].trilha == trilha:
            anterior = secoes[-1]
            secoes[-1] = Secao(
                trilha=trilha,
                onde=anterior.onde or onde,
                chars=anterior.chars + int(linha["chars"] or 0),
                trechos=anterior.trechos + 1,
                primeiro_id=anterior.primeiro_id,
                ordinal=anterior.ordinal,
            )
            continue
        secoes.append(
            Secao(
                trilha=trilha,
                onde=onde,
                chars=int(linha["chars"] or 0),
                trechos=1,
                primeiro_id=str(linha["id"]),
                ordinal=int(linha["ordinal"] or 0),
            )
        )
    return secoes


def normalizar_prefixo(pasta: str) -> str:
    """Barra invertida, barra sobrando e `.` são a mesma pasta. Vazio é a raiz."""
    limpo = (pasta or "").replace("\\", "/").strip().strip("/")
    return "" if limpo in {"", "."} else limpo + "/"


def _sob(caminho: str, prefixo: str, recursivo: bool) -> bool:
    if prefixo and not caminho.startswith(prefixo):
        return False
    resto = caminho[len(prefixo) :]
    return recursivo or "/" not in resto


def esta_na_pasta(caminho: str, pasta: str, *, recursivo: bool = False) -> bool:
    """O caminho relativo pertence à pasta pedida pela tool de manifesto?"""
    return _sob(caminho, normalizar_prefixo(pasta), recursivo)


def documentos_da_pasta(store: Store, pasta: str, *, recursivo: bool = False) -> list[Documento]:
    """Todo documento do registro sob esta pasta, em ordem de caminho.

    Ordem por caminho e não por relevância: enumeração é neutra (anti-recomendação
    6 do pacote J). Ordem estável é o que deixa o agente paginar por cursor e
    saber que a página seguinte continua de onde a anterior parou.
    """
    prefixo = normalizar_prefixo(pasta)
    if prefixo:
        # "/" é 0x2F e "0" é 0x30: todo caminho sob a pasta cai nesta faixa, e a
        # faixa usa a chave primária em vez de varrer a tabela.
        linhas = store.con.execute(
            f"SELECT {_campos(store)} FROM documentos WHERE path >= ? AND path < ? ORDER BY path, raiz",
            (prefixo, prefixo[:-1] + "0"),
        ).fetchall()
    else:
        linhas = store.con.execute(f"SELECT {_campos(store)} FROM documentos ORDER BY path, raiz").fetchall()

    escolhidas = [l for l in linhas if _sob(str(l["path"]), prefixo, recursivo)]
    irmaos = _irmaos_em_lote(store, [str(l["sha256"] or "") for l in escolhidas])
    return [
        _linha_para_documento(l, irmaos.get(str(l["sha256"] or ""), [str(l["path"])]))
        for l in escolhidas
    ]


def _irmaos_em_lote(store: Store, hashes: Iterable[str]) -> dict[str, list[str]]:
    """Uma consulta para todos os hashes de uma vez, nunca uma por documento.

    Recebe os hashes da **pasta inteira** e devolve, para cada um, todos os
    caminhos do índice que carregam aquele conteúdo — inclusive os de fora da
    pasta. É por isso que `mesmo_conteudo_em` de um item pode citar caminho que o
    manifesto não lista: o irmão está em outro lugar do acervo, e omiti-lo faria o
    agente achar que o documento é único.

    A lição do N+1 deste repositório: a **forma** do acesso é a mesma no índice
    de quatro trechos da suíte e no acervo de 2.156 documentos, e só o N muda.
    Um manifesto de 200 itens faria 200 idas ao SQLite sem isto.
    """
    presentes = sorted({h for h in hashes if h})
    por_hash: dict[str, dict[str, float]] = {}
    for lote in _em_lotes(presentes):
        marcas = ",".join("?" * len(lote))
        linhas = store.con.execute(
            f"SELECT path, sha256, mtime FROM documentos WHERE sha256 IN ({marcas})",
            tuple(lote),
        ).fetchall()
        for linha in linhas:
            por_hash.setdefault(str(linha["sha256"]), {})[str(linha["path"])] = float(
                linha["mtime"] or 0.0
            )
    return {h: por_vigencia(sorted(m), m) for h, m in por_hash.items()}


def texto_por_documento(
    store: Store,
    caminhos: Sequence[str],
    *,
    documentos: Sequence[Documento] | None = None,
) -> dict[str, tuple[int, int]]:
    """`caminho -> (chars, trechos)`, numa consulta só para a página inteira.

    `chars` é o texto **indexado**, que é o que o agente vai receber se pedir o
    documento — não o tamanho do arquivo em disco, que para um PDF de scan não
    diz nada sobre quanto contexto ele custa.
    """
    saida: dict[str, tuple[int, int]] = {}
    if documentos and store._usa_ocorrencia():
        chaves = [doc.ocorrencia_id or doc.caminho for doc in documentos]
        for lote in _em_lotes(chaves):
            marcas = ",".join("?" * len(lote))
            linhas = store.con.execute(
                "SELECT ocorrencia_id, SUM(chars) AS chars, COUNT(*) AS trechos "
                f"FROM chunks WHERE ocorrencia_id IN ({marcas}) GROUP BY ocorrencia_id",
                tuple(lote),
            )
            saida.update({
                str(l["ocorrencia_id"]): (int(l["chars"] or 0), int(l["trechos"] or 0))
                for l in linhas
            })
        faltantes = [
            doc for doc in documentos if (doc.ocorrencia_id or doc.caminho) not in saida
        ]
        for lote in _em_lotes([doc.caminho for doc in faltantes]):
            marcas = ",".join("?" * len(lote))
            linhas = store.con.execute(
                "SELECT path, SUM(chars) AS chars, COUNT(*) AS trechos FROM chunks "
                "WHERE path IN (" + marcas + ") "
                "AND (ocorrencia_id = '' OR ocorrencia_id = path) GROUP BY path",
                tuple(lote),
            )
            por_caminho = {
                str(l["path"]): (int(l["chars"] or 0), int(l["trechos"] or 0))
                for l in linhas
            }
            for doc in faltantes:
                medida = por_caminho.get(doc.caminho)
                if medida is not None:
                    saida[doc.ocorrencia_id or doc.caminho] = medida
        return saida
    for lote in _em_lotes(caminhos):
        marcas = ",".join("?" * len(lote))
        linhas = store.con.execute(
            f"SELECT path, SUM(chars) AS chars, COUNT(*) AS trechos FROM chunks "
            f"WHERE path IN ({marcas}) GROUP BY path",
            tuple(lote),
        )
        saida.update(
            {str(l["path"]): (int(l["chars"] or 0), int(l["trechos"] or 0)) for l in linhas}
        )
    return saida


def quarentena_da_pasta(store: Store, pasta: str, *, recursivo: bool = False) -> dict[str, str]:
    """`caminho -> motivo`, para o manifesto reportar status em vez de erro cru.

    Um documento em quarentena **existe** para o agente: ele está no acervo e não
    foi lido. Omiti-lo do manifesto seria a truncagem silenciosa outra vez —
    quem lista uma pasta e recebe 8 de 9 arquivos não tem como saber do nono.
    """
    prefixo = normalizar_prefixo(pasta)
    return {
        item.path: item.motivo
        for item in store.listar_quarentena()
        if _sob(item.path, prefixo, recursivo)
    }


def mencoes_de_caminhos(
    store: Store, caminhos: Sequence[str],
) -> dict[str, list[tuple[str, str]]]:
    """`path -> [(tipo, valor), ...]` em lote, nunca uma consulta por documento.

    O export do vault precisa das menções de todos os canônicos de uma pasta
    para materializar wikilinks. A forma N+1 já custou neste repositório: no
    índice de teste o N some e o defeito só aparece no acervo real.
    """
    saida: dict[str, list[tuple[str, str]]] = {c: [] for c in caminhos}
    presentes = [c for c in caminhos if c]
    for lote in _em_lotes(presentes):
        marcas = ",".join("?" * len(lote))
        linhas = store.con.execute(
            f"SELECT path, tipo, valor FROM mencoes WHERE path IN ({marcas}) "
            "ORDER BY path, tipo, valor",
            tuple(lote),
        )
        for linha in linhas:
            saida.setdefault(str(linha["path"]), []).append(
                (str(linha["tipo"]), str(linha["valor"]))
            )
    return saida
