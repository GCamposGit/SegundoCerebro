"""Superfície MCP do Segundo Cérebro — duas ferramentas, nenhuma que gere texto.

    py -m segundocerebro.mcp.server --indice index

O servidor **recupera e devolve procedência**. Quem gera texto é o cliente, e é
por isso que o custo marginal por consulta é zero: embedding e busca rodam
localmente, sem nenhuma chamada a API paga. Ver as invariantes em
`ARCHITECTURE.md`; as duas que mais restringem este arquivo:

- **Nada de `answer`, `summarize` ou `explain`.** Uma ferramenta que gerasse
  texto reintroduziria custo por consulta e amarraria o projeto a um fornecedor.
- **Multi-hop é do cliente.** Estas ferramentas são primitivas componíveis; o
  laço de agente é quem compõe. Não há orquestrador de recuperação aqui.

Duas ferramentas, e não as cinco do ROADMAP, porque `search` e `read_note` já
fecham o laço — "onde está X" e "me mostra o que tem em volta". `neighbors`,
`list_recent` e `glossary` são hipóteses sobre o que será preciso, e o uso real
responde isso melhor que o palpite.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from ..config import ErroDeConfig, carregar
from ..index.embeddings import Embedder
from ..index.store import Store
from ..logger import get_logger
from ..retrieve.hybrid import BuscaHibrida

log = get_logger("mcp.server")

REPO = Path(__file__).resolve().parent.parent.parent.parent
K_PADRAO = 8
K_MAX = 50
JANELA_PADRAO = 1
JANELA_MAX = 5

CONTEXTO_PADRAO = 1
CONTEXTO_MAX = 3
"""Vizinhos anexados a cada acerto do `search`.

Ligado por padrão em 1, e o motivo é o caso "a resposta estava no parágrafo
seguinte": o chunker corta por estrutura, e estrutura não coincide com
raciocínio. Um trecho termina no meio de uma enumeração e a linha que responde
fica no seguinte.

O teto é baixo porque o custo é do cliente: cada vizinho ocupa contexto dele, e
`read_note` continua existindo para quem quiser ler mais em volta de um trecho
específico. Um por lado paga o caso comum; três é o limite de quem sabe o que
está pedindo."""


@dataclass
class Recursos:
    """Store e embedder, abertos na primeira consulta e não na importação.

    O `e5-large` leva ~80 s para carregar. Carregar no import estoura o handshake
    do cliente MCP, que desiste antes de o servidor responder à inicialização —
    e o modo de falha é "servidor não conecta", que não diz nada sobre a causa.
    """

    indice: Path
    modelo: str
    threads: int
    base: Any | None = None
    """`config.Base`, quando o servidor sobe a partir de `config.toml`.

    Opcional para que o servidor continue construível com três valores soltos —
    é o que os testes usam, e é o que mantém esta camada independente do formato
    de configuração.
    """
    _busca: BuscaHibrida | None = None
    _store: Store | None = None

    @property
    def busca(self) -> BuscaHibrida:
        if self._busca is None:
            log.info("abrindo índice %s com %s", self.indice, self.modelo)
            embedder = Embedder(self.modelo, threads=self.threads)
            self._store = Store(self.indice, embedder.dim)
            self._busca = (
                BuscaHibrida.de_base(self._store, embedder, self.base)
                if self.base is not None
                else BuscaHibrida(self._store, embedder)
            )
        return self._busca

    @property
    def store(self) -> Store:
        self.busca  # garante a abertura
        assert self._store is not None
        return self._store


def _procedencia(chunk) -> dict[str, Any]:  # noqa: ANN001
    """O que todo retorno carrega: identidade estável e de onde veio.

    `id` é estável entre reindexações porque deriva do caminho, da trilha de
    headings e do ordinal — não de rowid. É o que permite ao cliente pedir
    `read_note` do que a busca devolveu.
    """
    return {
        "id": chunk.id if hasattr(chunk, "id") else chunk.chunk_id,
        "arquivo": chunk.path,
        "secao": chunk.trilha or "",
        "onde": chunk.locator or "",
    }


INSTRUCOES_PADRAO = (
    "Recupera trechos da base de conhecimento pessoal e corporativa do usuário "
    "(PDF, DOCX, XLSX, PPTX, Markdown). Use `search` para localizar trechos "
    "relevantes e `read_note` para ler o contexto em volta de um trecho. "
    "Todo retorno traz arquivo e seção — cite a procedência ao responder. "
    "O servidor não gera texto: ele devolve o que está escrito nos documentos."
)

SOBRE_A_BASE = (
    " Esta base cobre: {descricao} Use-a quando a pergunta for sobre esse acervo."
)
"""Acrescentado à instrução quando a base declara descrição.

Não é enfeite: com duas bases registradas no mesmo cliente, a `instructions` é o
único sinal pelo qual o modelo escolhe entre elas (`ARCHITECTURE.md` §2). Uma
descrição vaga nas duas transforma o roteamento em sorteio.
"""


def construir(recursos: Recursos) -> MCPServer:
    base = recursos.base
    limites = getattr(base, "busca", None)
    k_padrao = limites.k if limites else K_PADRAO
    k_max = limites.k_max if limites else K_MAX
    janela_padrao = limites.janela if limites else JANELA_PADRAO
    janela_max = limites.janela_max if limites else JANELA_MAX
    contexto_padrao = getattr(limites, "contexto", CONTEXTO_PADRAO) if limites else CONTEXTO_PADRAO

    instrucoes = INSTRUCOES_PADRAO
    descricao = (getattr(base, "descricao", "") or "").strip()
    if descricao:
        if not descricao.endswith((".", "!", "?")):
            descricao += "."
        instrucoes += SOBRE_A_BASE.format(descricao=descricao)

    servidor = MCPServer(
        name=base.servidor if base is not None else "segundocerebro",
        title=base.titulo if base is not None else "Segundo Cérebro",
        instructions=instrucoes,
    )

    @servidor.tool(
        description=(
            "Busca trechos na base de conhecimento por significado e por termo exato. "
            "Devolve passagens com arquivo, seção e localizador. Boa para perguntas "
            "sobre o conteúdo de documentos, contratos, políticas, propostas e planilhas."
        )
    )
    def search(consulta: str, k: int = k_padrao, contexto: int = contexto_padrao) -> dict[str, Any]:
        """Args:
        consulta: pergunta ou termos em linguagem natural.
        k: quantos trechos devolver (1 a 50).
        contexto: quantos trechos vizinhos anexar a cada acerto (0 a 3).
        """
        if not consulta.strip():
            return {"erro": "consulta vazia", "trechos": []}
        k = max(1, min(int(k), k_max))
        contexto = max(0, min(int(contexto), CONTEXTO_MAX))

        acertos = recursos.busca.buscar_chunks(consulta, k, contexto)
        trechos = []
        for a in acertos:
            item = {
                **_procedencia(a),
                "texto": a.texto,
                "score": round(a.score, 5),
                "achado_por": a.origem or "nome",
            }
            # Só aparecem quando existem: campo vazio em todo retorno é ruído que
            # o cliente paga em contexto sem ganhar nada.
            if a.antes:
                item["antes"] = a.antes
            if a.depois:
                item["depois"] = a.depois
            trechos.append(item)
        return {"consulta": consulta, "encontrados": len(acertos), "trechos": trechos}

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

    return servidor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="segundocerebro.mcp.server")
    parser.add_argument("--base", help="qual base servir (ver config.toml)")
    parser.add_argument("--config", type=Path, help="arquivo de configuração")
    parser.add_argument("--indice", type=Path, help="sobrepõe o índice da base")
    parser.add_argument("--modelo", help="sobrepõe o modelo da base")
    parser.add_argument("--threads", type=int, help="sobrepõe as threads da máquina")
    args = parser.parse_args(argv)

    # A flag vence o arquivo, que vence o padrão do código — a ordem declarada
    # em `config.py`. Sem config.toml, a base sintética preserva o que já rodava.
    try:
        cfg = carregar(args.config)
        base = cfg.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    indice = args.indice or base.indice
    if not (indice / "registro.db").exists():
        log.error("índice não encontrado em %s — rodar o indexador primeiro", indice)
        return 2

    threads = args.threads if args.threads is not None else cfg.maquina.threads_efetivos()
    log.info("base '%s' (%s) | índice %s", base.id, base.titulo, indice)

    construir(
        Recursos(
            indice=indice,
            modelo=args.modelo or base.modelo,
            threads=threads,
            base=base,
        )
    ).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
