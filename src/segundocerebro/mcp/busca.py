"""Ferramentas MCP de recuperação — busca, vizinhança e grafo (`search`, `read_note`, `neighbors`).

Separado de `mcp/server.py` para respeitar a governança modular de
`tests/test_tamanho_dos_modulos.py`, espelhando a disciplina de `mcp/leitura.py`.
"""

from __future__ import annotations

from typing import Any

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
    "Use pasta para restringir os resultados a uma subpasta específica da base. "
    "Use depois_de e antes_de para filtrar por período (formato ISO YYYY ou YYYY-MM-DD). "
    "Use incluir_versoes_antigas=True para auditoria de minutas e comparação histórica."
)


def _procedencia(chunk: Any) -> dict[str, Any]:
    """Identidade estável e procedência do trecho."""
    return {
        "id": chunk.id if hasattr(chunk, "id") else chunk.chunk_id,
        "arquivo": chunk.path,
        "secao": chunk.trilha or "",
        "onde": chunk.locator or "",
    }


def _registrar_search(servidor: Any, recursos: Any, limites: Any) -> None:
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
            return {"erro": "consulta vazia", "trechos": []}
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
        )
        trechos = []
        for a in acertos:
            item = {
                **_procedencia(a),
                "texto": a.texto,
                "score": round(a.score, 5),
                "achado_por": a.origem or "nome",
            }
            if a.antes:
                item["antes"] = a.antes
            if a.depois:
                item["depois"] = a.depois
            trechos.append(item)
        return {"consulta": consulta, "encontrados": len(acertos), "trechos": trechos}


def _registrar_read_note(servidor: Any, recursos: Any, limites: Any) -> None:
    janela_padrao = limites.janela if limites else JANELA_PADRAO
    janela_max = limites.janela_max if limites else JANELA_MAX

    @servidor.tool(
        description=(
            "Lê um trecho pelo id devolvido por `search`, junto com os trechos vizinhos "
            "do mesmo documento. Use quando o trecho encontrado parecer cortado ou "
            "quando faltar o contexto em volta."
        )
    )
    def read_note(id: str, janela: int = janela_padrao) -> dict[str, Any]:
        """Args:
        id: identificador vindo de `search`.
        janela: quantos trechos trazer de cada lado (0 a 5).
        """
        janela = max(0, min(int(janela), janela_max))
        alvo = recursos.store.chunk(id)
        if alvo is None:
            return {"erro": f"trecho não encontrado: {id}", "trechos": []}

        vizinhos = recursos.store.vizinhos(id, janela) if janela else [alvo]
        return {
            **_procedencia(alvo),
            "documento": alvo.path,
            "trechos": [
                {**_procedencia(c), "texto": c.texto, "e_o_pedido": c.id == id} for c in vizinhos
            ],
        }


def _registrar_neighbors(servidor: Any, recursos: Any) -> None:
    @servidor.tool(
        description=(
            "Documentos ligados a um arquivo por identificador citado em comum — norma "
            "(ISO, NBR), lei, código de contrato ou documento, CNPJ, processo. Use quando "
            "a resposta depender de um documento que a busca por texto não alcança porque "
            "ele não repete as palavras da pergunta: o plano cita a norma, e a norma está "
            "em outra pasta com outro vocabulário. Devolve **por que** cada um está ligado."
        )
    )
    def neighbors(arquivo: str, limite: int = MAX_VIZINHOS_PADRAO) -> dict[str, Any]:
        """Args:
        arquivo: caminho vindo do campo `arquivo` de `search`.
        limite: quantos documentos ligados devolver (1 a 25).
        """
        from ..retrieve.grafo import vizinhos as andar_no_grafo

        if not arquivo.strip():
            return {"erro": "arquivo vazio", "vizinhos": []}
        limite = max(1, min(int(limite), MAX_VIZINHOS_TETO))

        store = recursos.store
        if not store.paths_com_mencoes():
            return {
                "arquivo": arquivo,
                "encontrados": 0,
                "vizinhos": [],
                "aviso": (
                    "o grafo derivado desta base está vazio: rode "
                    "`py -m segundocerebro.retrieve.grafo --base <id>` para construí-lo"
                ),
            }

        achados = andar_no_grafo(store, arquivo, limite=limite)
        return {
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
        }


def registrar(servidor: Any, recursos: Any, limites: Any = None) -> None:
    """Registra as ferramentas de busca e grafo no servidor MCP."""
    _registrar_search(servidor, recursos, limites)
    _registrar_read_note(servidor, recursos, limites)
    _registrar_neighbors(servidor, recursos)
