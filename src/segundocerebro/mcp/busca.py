"""Ferramentas MCP de recuperação — busca, vizinhança e grafo (`search`, `read_note`, `neighbors`).

Separado de `mcp/server.py` para respeitar a governança modular de
`tests/test_tamanho_dos_modulos.py`, espelhando a disciplina de `mcp/leitura.py`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp.types import CallToolResult

from ..acesso.registro import LOTE_DE_PARAMETROS
from ..index.store import Store
from ..ingest.parse_cache import canonicos_disponiveis
from ..retrieve.contrato import ChunkAcerto
from .respostas import erro_operacional, sucesso

if TYPE_CHECKING:
    pass

K_PADRAO = 8
K_MAX = 50
JANELA_PADRAO = 1
JANELA_MAX = 5
MAX_VIZINHOS_PADRAO = 5
MAX_VIZINHOS_TETO = 25
CONTEXTO_PADRAO = 1
CONTEXTO_MAX = 3

DESCRICAO_SEARCH = (
    "Busca trechos na base de conhecimento por significado e por termo exato. "
    "Devolve passagens com arquivo, seção e localizador. Boa para perguntas "
    "sobre o conteúdo de documentos, contratos, políticas, propostas e planilhas. "
    "Resultados colapsam versões do mesmo documento: para comparar versões, "
    "leia os ids listados em `anteriores` com `read_note`. "
    "Use pasta para restringir os resultados a uma subpasta específica da base. "
    "Use depois_de e antes_de para filtrar por período (formato ISO YYYY ou YYYY-MM-DD). "
    "Use incluir_versoes_antigas para auditoria da minuta antiga. "
    "Ausência de trecho não autoriza ler o arquivo por fora do índice. "
    "O retorno traz `limitacoes` quando o documento está em digesto, "
    "placeholder de nuvem ou sem texto extraível. Quando houver digesto de "
    "planilha, use `read_spreadsheet_cells` para consultar valores persistidos; "
    "essa leitura não abre o arquivo original."
)

LIMITE_DIGESTO = "Há abas representadas por digesto de valores, não por todas as células."
LIMITE_VAZIO = (
    "O índice não tem texto extraível deste documento. "
    "Isso não autoriza abrir o arquivo por fora."
)
LIMITE_PLACEHOLDER = (
    "O arquivo está só como placeholder de nuvem. "
    "O índice não tem o conteúdo, e abrir o original dispararia download."
)


def _procedencia(chunk: Any) -> dict[str, Any]:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    """Identidade estável e procedência do trecho."""
    return {
        "id": chunk.id if hasattr(chunk, "id") else chunk.chunk_id,
        "arquivo": chunk.path,
        **({"root_id": chunk.root_id} if getattr(chunk, "root_id", "") else {}),
        **({"ocorrencia_id": chunk.ocorrencia_id} if getattr(chunk, "ocorrencia_id", "") else {}),
        "secao": chunk.trilha or "",
        "onde": chunk.locator or "",
    }


def _resumo_item(caminho: str, recursos: Any) -> dict[str, str]:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    """Procedência de versão anterior ou formato alternativo para `read_note`/`neighbors`."""
    data = ""
    busca = getattr(recursos, "busca", None)
    mtime = busca.mtimes.get(caminho) if busca else None
    if mtime:
        try:
            data = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        except (OSError, ValueError):
            data = ""
    chunk_id = ""
    store = getattr(recursos, "store", None)
    if store is not None:
        ids = store.ids_de_chunks(caminho)
        if ids:
            chunk_id = ids[0]
    extensao = caminho.rsplit(".", 1)[-1].lower() if "." in caminho else ""
    return {
        "id": chunk_id,
        "arquivo": caminho,
        "caminho": caminho,
        "data": data,
        "formato": extensao,
    }


def _lotes(itens: Sequence[str], tamanho: int) -> Iterable[Sequence[str]]:
    for inicio in range(0, len(itens), tamanho):
        yield itens[inicio : inicio + tamanho]


def _linhas_por_caminho(store: Store, caminhos: Sequence[str]) -> dict[str, list[dict[str, str]]]:
    """Uma consulta em lote por leva. O status não volta a custar uma ida por trecho."""
    por_caminho: dict[str, list[dict[str, str]]] = {}
    unicos = list(dict.fromkeys(c for c in caminhos if c))
    for lote in _lotes(unicos, LOTE_DE_PARAMETROS):
        marcas = ",".join("?" * len(lote))
        consulta = (
            "SELECT path, root_id, status, sha256, parser FROM documentos "
            f"WHERE path IN ({marcas})"
        )
        for row in store.con.execute(consulta, tuple(lote)):
            por_caminho.setdefault(str(row["path"]), []).append(
                {
                    "path": str(row["path"]),
                    "root_id": str(row["root_id"] or ""),
                    "status": str(row["status"] or ""),
                    "sha256": str(row["sha256"] or ""),
                    "parser": str(row["parser"] or ""),
                }
            )
    return por_caminho


def _linha_do_acerto(
    por_caminho: dict[str, list[dict[str, str]]], acerto: ChunkAcerto
) -> dict[str, str] | None:
    linhas = por_caminho.get(acerto.path, [])
    if acerto.root_id:
        for linha in linhas:
            if linha["root_id"] == acerto.root_id:
                return linha
        return None
    if len(linhas) == 1:
        return linhas[0]
    return None


def _meta_na_chave_atual(
    store: Store,
    linha: dict[str, str],
    cache: dict[tuple[str, str, bool], dict[str, str]],
) -> dict[str, str]:
    sha = linha["sha256"]
    if not sha:
        return {}
    extensao = Path(linha["path"]).suffix.lower()
    ocr = linha["parser"].startswith("ocr:")
    chave = (sha, extensao, ocr)
    if chave not in cache:
        meta: dict[str, str] = {}
        for _chave, canonico in canonicos_disponiveis(store.diretorio, sha, extensao, ocr=ocr):
            meta = {str(k): str(v) for k, v in canonico.meta.items()}
            break
        cache[chave] = meta
    return cache[chave]


def _limitacoes_da_linha(
    store: Store,
    linha: dict[str, str] | None,
    cache: dict[tuple[str, str, bool], dict[str, str]],
) -> list[str]:
    if linha is None:
        return []
    saida: list[str] = []
    if linha["status"] == "vazio":
        saida.append(LIMITE_VAZIO)
    if linha["status"] == "placeholder":
        saida.append(LIMITE_PLACEHOLDER)
    if _meta_na_chave_atual(store, linha, cache).get("abas_em_digesto"):
        saida.append(LIMITE_DIGESTO)
    return saida


def _anexar_limitacoes(
    trechos: list[dict[str, Any]], acertos: Sequence[ChunkAcerto], store: Store
) -> None:
    if not acertos:
        return
    por_caminho = _linhas_por_caminho(store, [a.path for a in acertos])
    cache: dict[tuple[str, str, bool], dict[str, str]] = {}
    for trecho, acerto in zip(trechos, acertos, strict=True):
        msgs = _limitacoes_da_linha(store, _linha_do_acerto(por_caminho, acerto), cache)
        if msgs:
            trecho["limitacoes"] = msgs


def _montar_trechos(acertos: Sequence[ChunkAcerto], recursos: Any) -> list[dict[str, Any]]:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    trechos: list[dict[str, Any]] = []
    for a in acertos:
        item: dict[str, Any] = {
            **_procedencia(a),
            "texto": a.texto,
            "score": round(a.score, 5),
            "achado_por": a.origem or "nome",
            "versoes": a.versoes,
        }
        if a.antes:
            item["antes"] = a.antes
        if a.depois:
            item["depois"] = a.depois
        if a.anteriores:
            item["anteriores"] = [_resumo_item(p, recursos) for p in a.anteriores]
        if a.formatos:
            item["formatos"] = [_resumo_item(p, recursos) for p in a.formatos]
        trechos.append(item)
    store = getattr(recursos, "store", None)
    if store is not None:
        _anexar_limitacoes(trechos, acertos, store)
    return trechos


def _registrar_search(servidor: Any, recursos: Any, limites: Any) -> None:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    k_padrao = limites.k if limites else K_PADRAO
    k_max = limites.k_max if limites else K_MAX
    contexto_padrao = getattr(limites, "contexto", CONTEXTO_PADRAO) if limites else CONTEXTO_PADRAO

    @servidor.tool(description=DESCRICAO_SEARCH)
    def search(
        consulta: str,
        k: int = k_padrao,
        contexto: int = contexto_padrao,
        pasta: str = "",
        incluir_versoes_antigas: bool = False,
        depois_de: str = "",
        antes_de: str = "",
        root_id: str = "",
    ) -> dict[str, Any]:
        """Args:
        consulta: pergunta ou termos em linguagem natural.
        k: quantos trechos devolver (1 a 50).
        contexto: quantos trechos vizinhos anexar a cada acerto (0 a 3).
        pasta: caminho relativo da pasta para filtrar a busca (ex: 'Contratos' ou 'Projetos/X').
        incluir_versoes_antigas: se True, não descarta versões superadas de uma família.
        depois_de: data ISO inicial (ex: '2024' ou '2024-01-01') para restringir a busca.
        antes_de: data ISO final (ex: '2024' ou '2024-12-31') para restringir a busca.
        """
        if not consulta.strip():
            return erro_operacional("consulta vazia", "consulta_vazia", {"trechos": []})
        k = max(1, min(int(k), k_max))
        contexto = max(0, min(int(contexto), CONTEXTO_MAX))

        acertos = recursos.busca.buscar_chunks(
            consulta,
            k=k,
            contexto=contexto,
            pasta=pasta,
            incluir_versoes_antigas=incluir_versoes_antigas,
            depois_de=depois_de,
            antes_de=antes_de,
            root_id=root_id,
        )
        trechos = _montar_trechos(acertos, recursos)
        return sucesso({"consulta": consulta, "encontrados": len(acertos), "trechos": trechos})



def _registrar_read_note(servidor: Any, recursos: Any, limites: Any) -> None:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    janela_padrao = limites.janela if limites else JANELA_PADRAO
    janela_max = limites.janela_max if limites else JANELA_MAX

    @servidor.tool(
        description=(
            "Lê um trecho pelo id devolvido por `search`, junto com os trechos vizinhos "
            "do mesmo documento. Use quando o trecho encontrado parecer cortado ou "
            "quando faltar o contexto em volta."
        )
    )
    def read_note(id: str, janela: int = janela_padrao) -> CallToolResult:
        """Args:
        id: identificador vindo de `search`.
        janela: quantos trechos trazer de cada lado (0 a 5).
        """
        janela = max(0, min(int(janela), janela_max))
        alvo = recursos.store.chunk(id)
        if alvo is None:
            return erro_operacional(f"trecho não encontrado: {id}", "trecho_nao_encontrado", {"id": id, "trechos": []})

        vizinhos = recursos.store.vizinhos(id, janela) if janela else [alvo]
        return sucesso({
            **_procedencia(alvo),
            "documento": alvo.path,
            "trechos": [
                {**_procedencia(c), "texto": c.texto, "e_o_pedido": c.id == id} for c in vizinhos
            ],
        })


def _registrar_neighbors(servidor: Any, recursos: Any) -> None:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    @servidor.tool(
        description=(
            "Documentos ligados a um arquivo por identificador citado em comum — norma "
            "(ISO, NBR), lei, código de contrato ou documento, CNPJ, processo. Use quando "
            "a resposta depender de um documento que a busca por texto não alcança porque "
            "ele não repete as palavras da pergunta: o plano cita a norma, e a norma está "
            "em outra pasta com outro vocabulário. Devolve **por que** cada um está ligado."
        )
    )
    def neighbors(arquivo: str, limite: int = MAX_VIZINHOS_PADRAO) -> CallToolResult:
        """Args:
        arquivo: caminho vindo do campo `arquivo` de `search`.
        limite: quantos documentos ligados devolver (1 a 25).
        """
        from ..retrieve.grafo import vizinhos as andar_no_grafo

        if not arquivo.strip():
            return erro_operacional("arquivo vazio", "arquivo_vazio", {"vizinhos": []})
        limite = max(1, min(int(limite), MAX_VIZINHOS_TETO))

        store = recursos.store
        if not store.paths_com_mencoes():
            return sucesso({
                "arquivo": arquivo,
                "encontrados": 0,
                "vizinhos": [],
                "aviso": (
                    "o grafo derivado desta base está vazio: rode "
                    "`py -m segundocerebro.retrieve.grafo --base <id>` para construí-lo"
                ),
            })

        achados = andar_no_grafo(store, arquivo, limite=limite)
        return sucesso({
            "arquivo": arquivo,
            "encontrados": len(achados),
            "vizinhos": [
                {
                    "arquivo": v.path,
                    "peso": round(v.peso, 5),
                    "porque": [
                        {
                            "tipo": l.tipo,
                            "identificador": l.valor,
                            "citado_em_documentos": l.documentos,
                            **({"id": l.chunk_id} if l.chunk_id else {}),
                        }
                        for l in v.ligacoes
                    ],
                }
                for v in achados
            ],
        })


def registrar(servidor: Any, recursos: Any, limites: Any = None) -> None:  # noqa: ANN401 — fronteira dinâmica ainda sem protocolo
    """Registra as ferramentas de busca e grafo no servidor MCP."""
    _registrar_search(servidor, recursos, limites)
    _registrar_read_note(servidor, recursos, limites)
    _registrar_neighbors(servidor, recursos)
