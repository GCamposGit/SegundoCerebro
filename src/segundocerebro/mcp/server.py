"""Superfície MCP do Segundo Cérebro — sete ferramentas, nenhuma que gere texto.

    py -m segundocerebro.mcp.server --indice index

O servidor **recupera e devolve procedência**. Quem gera texto é o cliente, e é
por isso que o custo marginal por consulta é zero: embedding e busca rodam
localmente, sem nenhuma chamada a API paga. Ver as invariantes em
`ARCHITECTURE.md`; as duas que mais restringem este arquivo:

- **Nada de `answer`, `summarize` ou `explain`.** Uma ferramenta que gerasse
  texto reintroduziria custo por consulta e amarraria o projeto a um fornecedor.
- **Multi-hop é do cliente.** Estas ferramentas são primitivas componíveis; o
  laço de agente é quem compõe. Não há orquestrador de recuperação aqui.

Sete ferramentas, em dois grupos. `search`, `read_note` e `neighbors` servem o
modo **pergunta**, e são as que este arquivo registra. `list_folder`, `outline`,
`get_document` e `pack_folder` servem o modo **leitura** — enumerar, mapear, ler
e empacotar. As duas primeiras entraram em 30/08/2026 pelo `J.c-mapa`; a terceira
em 02/09/2026 pelo `J.c-conteúdo`; `pack_folder` em 02/09/2026 pelo `J.d`. O
registro deste grupo mora em `mcp/leitura.py`, porque `construir` está no teto
de tamanho e superfície nova não empurra função que a tabela só deixa descer.

`list_recent` e `glossary` continuam de fora: são hipóteses que o uso real não
confirmou.

`neighbors` entrou na F4 por um motivo diferente: o traço de uso real mostrou o
limite que ela existe para romper. Dois documentos que só se ligam por um
identificador citado em ambos — um plano de ação que termina em "certificação
ISO 42001" e a norma, em outra pasta — não têm nome, pasta nem vocabulário em
comum. Nenhum ranqueador desta pilha os aproxima, por melhor que seja o peso de
fusão; o que faltava não era precisão, era uma **aresta**. Ver `retrieve/grafo.py`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from ..config import ErroDeConfig, carregar
from ..index.embeddings import MODELOS, Embedder
from ..index.store import Store
from ..logger import get_logger
from ..retrieve.hybrid import BuscaHibrida
from .busca import registrar as registrar_busca
from .leitura import registrar as registrar_leitura
from .overview import registrar as registrar_overview

log = get_logger("mcp.server")

K_PADRAO = 8
K_MAX = 50
JANELA_PADRAO = 1
JANELA_MAX = 5

MAX_VIZINHOS_PADRAO = 5
MAX_VIZINHOS_TETO = 25
"""Quantos documentos ligados o `neighbors` devolve.

Padrão baixo de propósito. O grafo é feito para o caso em que **um** documento
faltava — a norma que o plano cita —, e devolver vinte candidatos transfere ao
cliente o trabalho de filtrar, gastando contexto dele. Quem precisa de mais pede.
"""

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
    """Store na primeira leitura; embedder apenas na primeira busca.

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
            if self._store is None:
                self._store = Store(self.indice, embedder.dim)
            self._busca = (
                BuscaHibrida.de_base(self._store, embedder, self.base)
                if self.base is not None
                else BuscaHibrida(self._store, embedder)
            )
        return self._busca

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = Store(self.indice, MODELOS[self.modelo].dim)
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


def _instrucoes(base) -> str:  # noqa: ANN001
    """A instrução do servidor, com a descrição da base quando ela declara uma.

    Saiu de `construir` em 30/08/2026 para abrir espaço às tools do `J.c-mapa`:
    aquela função está em `FUNCOES_ACIMA_DO_TETO` e a tabela só desce. É também
    a única parte de `construir` com razão de mudar própria — o que o cliente lê
    para escolher **entre bases**, e não o que cada tool faz.
    """
    instrucoes = INSTRUCOES_PADRAO
    descricao = (getattr(base, "descricao", "") or "").strip()
    if descricao:
        if not descricao.endswith((".", "!", "?")):
            descricao += "."
        instrucoes += SOBRE_A_BASE.format(descricao=descricao)
    return instrucoes


def construir(recursos: Recursos) -> MCPServer:
    base = recursos.base
    limites = getattr(base, "busca", None)

    servidor = MCPServer(
        name=base.servidor if base is not None else "segundocerebro",
        title=base.titulo if base is not None else "Segundo Cérebro",
        instructions=_instrucoes(base),
    )
    registrar_busca(servidor, recursos, limites)
    registrar_leitura(servidor, recursos, limites)
    registrar_overview(servidor, recursos)
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
