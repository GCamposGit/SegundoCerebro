"""O protocolo, e não as funções por trás dele — o caminho que o leigo executa.

`test_mcp.py` chama `servidor.call_tool(...)` direto. Isso prova o contrato de
retorno e é cego para tudo o que existe **entre** o cliente e essas funções:

- o **handshake**, cujo modo de falha é "servidor não conecta" — a mensagem que
  não diz nada sobre a causa, e que este repositório já produziu duas vezes
  (`PYTHONPATH=src` a partir de `C:\\Windows\\system32`, e o `.exe` que o `PATH`
  não alcança);
- o **esquema JSON** de cada ferramenta, que é o que o cliente lê para saber como
  chamar. Um parâmetro renomeado passa em todo teste que chama a função por
  palavra-chave e quebra no cliente;
- o **cano de bytes**. `mcp/registrar.py` fixa `PYTHONIOENCODING=utf-8` porque sem
  isso o Windows entrega cp1252 no stdio e um acento no caminho de um documento
  corrompe o fluxo do protocolo. Nenhum teste defendia esse comentário;
- **qual caminho de recuperação a ferramenta executa** — a classe do `F4-P.0`, em
  que o eval media `search` e o cliente executava `buscar_chunks`, por uma fase
  inteira, sem que nada ficasse vermelho;
- os **nomes dos campos da SDK**. Este arquivo nasceu escrito em `isError` e
  `serverInfo`, que é como a especificação do protocolo os mostra, e a SDK
  instalada expõe `is_error` e `server_info`. Nenhuma chamada de função notaria;
- e o **doc que o usuário lê**, que dizia "duas ferramentas" e "`neighbors`
  continua hipótese" enquanto a `neighbors` já respondia no `.mcp.json` dele.

Duas conversas, as duas na suíte padrão e as duas **sem carregar modelo**:

1. **o processo que o registro manda lançar** (`py -m segundocerebro.mcp.server`),
   com `main()`, argparse e `config.toml` de verdade. O modelo é preguiçoso de
   propósito, então handshake e `tools/list` respondem sem ele — que é
   exatamente o pedaço onde mora o "não conecta";
2. **`tests/servidor_falso.py`**, que serve um índice minúsculo com embedder
   falso, para chamar as três ferramentas por cima do cano de verdade.

**Uma conversa por servidor, e as afirmações depois.** A primeira versão subia um
processo por teste e custava 107 s — caro numa suíte de 987. Além de mais rápido,
é mais fiel: o leigo abre **uma** sessão e faz várias chamadas nela, e o que
sobrevive entre chamadas é parte do que se quer provar.

O que este arquivo **não** faz é medir recuperação: o corpus é de cinco trechos e
não diz nada sobre ranking. Ele mede contrato de transporte.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from segundocerebro.config import Base
from segundocerebro.mcp.registrar import AMBIENTE, entrada_de

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "tests" / "servidor_falso.py"

FERRAMENTAS = {"search", "read_note", "neighbors"}
"""A superfície inteira, declarada aqui de novo e de propósito.

`test_mcp.py` já afirma isto sobre o objeto servidor; aqui a afirmação é sobre o
que **chega ao cliente**. Ferramenta nova sem entrar nesta lista reprova, e é a
forma de o invariante 2 — nada que gere texto — ser conferido no lugar onde o
cliente a veria aparecer.
"""

PROIBIDAS = {"answer", "summarize", "explain", "responder", "resumir", "gerar", "chat"}

TIMEOUT = 90.0
"""Servidor morto tem de virar erro de teste, não suíte pendurada.

Folgado porque na primeira execução o `lancedb` cria o diretório do índice e o
antivírus do Windows às vezes cobra por isso; nenhuma destas conversas carrega
modelo, então 90 s é teto, não expectativa.
"""


def _cwd_neutro(tmp: Path) -> str:
    """Diretório que não é a raiz do projeto.

    O Claude Desktop nasce em `C:\\Windows\\system32`. Subir o servidor de dentro
    do repositório esconde exatamente a classe de falha que o registro absoluto
    existe para evitar.
    """
    system32 = Path(os.environ.get("SystemRoot", "")) / "system32"
    return str(system32 if system32.is_dir() else tmp)


def _ambiente() -> dict[str, str]:
    """O ambiente que o registro declara, com `PYTHONPATH` absoluto.

    `AMBIENTE` vem de `mcp/registrar.py` em vez de ser reescrito aqui: se alguém
    tirar o `PYTHONIOENCODING` de lá, é este teste que cai.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(AMBIENTE)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO), str(REPO / "src")])
    return env


def conversar(params: StdioServerParameters, roteiro) -> Any:  # noqa: ANN001
    """Sobe o servidor, faz o handshake, roda o roteiro e desliga."""

    async def _falar() -> Any:
        async with (
            stdio_client(params) as (ler, escrever),
            ClientSession(ler, escrever, read_timeout_seconds=TIMEOUT) as sessao,
        ):
            inicio = await sessao.initialize()
            return await roteiro(sessao, inicio)

    return asyncio.run(_falar())


def carga(resultado) -> dict[str, Any]:  # noqa: ANN001
    """O que o cliente lê — e os dois caminhos por onde ele pode ler.

    Cliente antigo lê `content[0].text`; cliente novo lê `structured_content`. Os
    dois têm de dizer a mesma coisa, senão o comportamento depende da versão do
    cliente que o usuário instalou.
    """
    assert not resultado.is_error, resultado
    do_texto = json.loads(resultado.content[0].text)
    assert do_texto == resultado.structured_content
    return do_texto


def _id_do_topo(resultado) -> str:  # noqa: ANN001
    """O id do primeiro trecho, ou um id impossível quando a busca não deu nada.

    Tolerante de propósito. A fixture faz as chamadas e **não** as confere: quem
    confere é cada teste, sobre o resultado cru. Se `carga` fosse chamada aqui, um
    `search` quebrado derrubaria a fixture e levaria os outros cinco testes com
    ela — seis erros no lugar de uma falha, e nenhum deles apontando o defeito.
    """
    if resultado.is_error or not resultado.structured_content:
        return "a-busca-falhou#0"
    trechos = resultado.structured_content.get("trechos") or []
    return trechos[0]["id"] if trechos else "a-busca-veio-vazia#0"


# --- 1. o processo que o registro manda lançar -------------------------------

CONFIG = """
[[base]]
id = "trabalho"
nome = "Acme Holding"
descricao = "Contratos, propostas e atas da Acme Holding"
indice = "indice"
"""


@pytest.fixture(scope="module")
def do_produto(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Uma instalação como a do usuário, e o que o handshake dela devolve.

    O índice fica **vazio**, com o `registro.db` de pé. É o suficiente: `main()`
    recusa índice inexistente, e handshake e `tools/list` não consultam nada — que
    é justamente a propriedade que permite ao modelo ser preguiçoso.

    O comando sai de `entrada_de`, que é o que se escreve no cliente. Derivar
    daqui em vez de repetir a string é o que amarra as duas pontas: no dia em que
    o registro passar a emitir o console script — que nesta máquina o `PATH` não
    alcança —, é este teste que cai, e não o usuário.
    """
    from segundocerebro.index.store import Store

    from tests.falsos import DIM

    raiz = tmp_path_factory.mktemp("instalacao")
    Store(raiz / "indice", DIM).fechar()
    (raiz / "config.toml").write_text(CONFIG, encoding="utf-8")

    entrada = entrada_de(Base(id="trabalho", indice=raiz / "indice"))
    params = StdioServerParameters(
        command=sys.executable,
        args=[*entrada["args"], "--config", str(raiz / "config.toml")],
        env=_ambiente(),
        cwd=_cwd_neutro(raiz),
    )

    async def roteiro(sessao, inicio):  # noqa: ANN001
        return {
            "inicio": inicio,
            "ferramentas": {f.name: f for f in (await sessao.list_tools()).tools},
        }

    return conversar(params, roteiro)


def test_o_servidor_do_produto_conecta_de_um_cwd_neutro(do_produto: dict[str, Any]) -> None:
    """O handshake, que é onde mora o "servidor não conecta".

    Sem modelo: o `e5-large` leva ~80 s e é aberto na primeira consulta. Se algum
    dia alguém abrir o índice na construção, esta conversa passa a levar minutos —
    e é bom que doa aqui, porque no cliente isso aparece como não conectar.
    """
    inicio = do_produto["inicio"]

    assert inicio.server_info.name == "segundocerebro-trabalho"
    assert inicio.server_info.title == "Acme Holding"


def test_as_instrucoes_da_base_chegam_ao_cliente(do_produto: dict[str, Any]) -> None:
    """Com duas bases no mesmo cliente, a descrição é o único sinal de roteamento.

    `ARCHITECTURE.md` §2. `test_mcp.py` confere que ela entra em
    `servidor.instructions`; aqui se confere que ela atravessa o handshake, que é
    o lugar onde o modelo a lê.
    """
    instrucoes = do_produto["inicio"].instructions or ""

    assert "Contratos, propostas e atas da Acme Holding." in instrucoes
    assert "não gera texto" in instrucoes


def test_o_cliente_ve_exatamente_as_tres_ferramentas(do_produto: dict[str, Any]) -> None:
    """Invariante 2 conferido onde ele importa: no que o cliente enxerga.

    Uma ferramenta que gerasse texto reintroduziria custo por consulta e amarraria
    o projeto a um fornecedor — e ela só é perigosa quando aparece na sessão do
    agente, que é aqui.
    """
    ferramentas = do_produto["ferramentas"]

    assert set(ferramentas) == FERRAMENTAS
    assert not (set(ferramentas) & PROIBIDAS)
    for nome, f in ferramentas.items():
        assert f.description and len(f.description) > 60, nome


def test_o_esquema_diz_ao_cliente_como_chamar(do_produto: dict[str, Any]) -> None:
    """O esquema é a interface de verdade.

    Renomear `consulta` para `query` passa em todo teste que chama a função por
    palavra-chave e faz o cliente errar a chamada — que ele mostra como a
    ferramenta estar quebrada, não como parâmetro trocado.
    """
    esquemas = {nome: f.input_schema for nome, f in do_produto["ferramentas"].items()}

    assert esquemas["search"]["required"] == ["consulta"]
    assert set(esquemas["search"]["properties"]) == {"consulta", "k", "contexto"}
    assert esquemas["read_note"]["required"] == ["id"]
    assert set(esquemas["read_note"]["properties"]) == {"id", "janela"}
    assert esquemas["neighbors"]["required"] == ["arquivo"]
    assert set(esquemas["neighbors"]["properties"]) == {"arquivo", "limite"}


# --- 2. as três ferramentas por cima do cano de verdade ----------------------


@pytest.fixture(scope="module")
def do_servidor_falso(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Uma sessão de cliente contra o índice falso, com as chamadas dela.

    Várias chamadas na mesma sessão, e não uma sessão por chamada: é o que o
    cliente faz, e é o único jeito de provar que o `id` que uma ferramenta
    devolveu a outra aceita — invariante 3, multi-hop é do cliente, então a
    superfície tem de ser componível.
    """
    from tests.servidor_falso import PLANO

    raiz = tmp_path_factory.mktemp("falso")
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(DRIVER), "--indice", str(raiz / "indice"), "--base", "trabalho"],
        env=_ambiente(),
        cwd=_cwd_neutro(raiz),
    )

    async def roteiro(sessao, inicio):  # noqa: ANN001, ARG001
        alvo = await sessao.call_tool("search", {"consulta": "uso aceitável", "k": 1})
        id_do_alvo = _id_do_topo(alvo)
        return {
            "procedencia": await sessao.call_tool(
                "search", {"consulta": "revisão humana", "k": 3}
            ),
            "governanca": await sessao.call_tool("search", {"consulta": "governança", "k": 5}),
            "id_do_alvo": id_do_alvo,
            "lido": await sessao.call_tool("read_note", {"id": id_do_alvo, "janela": 1}),
            "vizinhos": await sessao.call_tool("neighbors", {"arquivo": PLANO}),
            "consulta_vazia": await sessao.call_tool("search", {"consulta": "   "}),
            "iso": await sessao.call_tool("search", {"consulta": "certificação ISO 42001", "k": 3}),
        }

    return conversar(params, roteiro)


def test_search_devolve_procedencia_pelo_protocolo(do_servidor_falso: dict[str, Any]) -> None:
    """Invariante 5 medido no caminho entregue, não no caminho de teste."""
    from tests.servidor_falso import POLITICA

    saida = carga(do_servidor_falso["procedencia"])

    assert saida["encontrados"] > 0
    for trecho in saida["trechos"]:
        assert trecho["id"], "invariante 5: id estável"
        assert trecho["arquivo"], "invariante 5: arquivo"
        assert "secao" in trecho and "onde" in trecho
        assert trecho["texto"]
    assert POLITICA in {t["arquivo"] for t in saida["trechos"]}


def test_acento_e_emoji_no_caminho_atravessam_o_cano(do_servidor_falso: dict[str, Any]) -> None:
    """O que o `PYTHONIOENCODING` de `registrar.py` existe para proteger.

    Sem ele o Windows entrega cp1252 no stdio, e o campo que carrega o caminho do
    documento é justamente a procedência. O corpus de teste tem um caminho com
    acento, travessão e um caractere fora do cp1252 para que o comentário lá
    tenha algo que o defenda aqui.
    """
    from tests.servidor_falso import POLITICA

    arquivos = {t["arquivo"] for t in carga(do_servidor_falso["governanca"])["trechos"]}

    assert POLITICA in arquivos, f"o caminho voltou corrompido: {arquivos}"


def test_o_id_de_search_serve_para_read_note_pelo_protocolo(
    do_servidor_falso: dict[str, Any],
) -> None:
    """O laço componível, na mesma sessão — que é como o cliente o usa.

    Multi-hop é do cliente (invariante 3): a superfície só é componível se o id
    que uma ferramenta devolve a outra aceitar, e isso se prova numa conversa,
    não em duas chamadas de função.
    """
    lido = carga(do_servidor_falso["lido"])

    assert lido["id"] == do_servidor_falso["id_do_alvo"]
    assert [t["e_o_pedido"] for t in lido["trechos"]].count(True) == 1
    assert len(lido["trechos"]) > 1, "janela=1 tem de trazer vizinho"


def test_neighbors_devolve_o_porque_pelo_protocolo(do_servidor_falso: dict[str, Any]) -> None:
    """A aresta e o motivo dela, serializados.

    O `porque` é lista de objetos aninhados — a parte do retorno mais exposta a
    erro de serialização, e a única que o cliente não tem como reconstruir.
    """
    from tests.servidor_falso import NORMA

    saida = carga(do_servidor_falso["vizinhos"])

    assert [v["arquivo"] for v in saida["vizinhos"]] == [NORMA]
    porque = saida["vizinhos"][0]["porque"][0]
    assert porque["tipo"] == "norma"
    assert porque["identificador"] == "ISO 42001"
    assert "aviso" not in saida


def test_erro_de_ferramenta_chega_como_dado_e_nao_como_falha_de_protocolo(
    do_servidor_falso: dict[str, Any],
) -> None:
    """Consulta vazia é resposta, não exceção.

    Se virasse erro de JSON-RPC, o cliente mostraria "a ferramenta falhou" e o
    modelo não teria com que se corrigir. O erro tem de ser conteúdo legível.
    """
    resultado = do_servidor_falso["consulta_vazia"]

    assert not resultado.is_error
    assert carga(resultado) == {"erro": "consulta vazia", "trechos": []}


# --- 3. qual caminho de recuperação a ferramenta executa ---------------------


def test_a_ferramenta_search_nao_passa_pelo_ranqueador_de_documento(
    do_servidor_falso: dict[str, Any],
) -> None:
    """A classe do `F4-P.0` como armadilha armada, não como relatório.

    O servidor de teste serve com uma `BuscaHibrida` cujo `search` — o ranqueador
    de **documento** — explode. Se a ferramenta MCP `search` cair nele, a chamada
    volta como erro e este teste fica vermelho no mesmo commit. Foi a divergência
    que passou uma fase inteira sem nada quebrar.
    """
    resultado = do_servidor_falso["iso"]

    assert not resultado.is_error, "a ferramenta caiu no ranqueador de documento"
    assert carga(resultado)["trechos"]


# --- 4. o que o usuário lê contra o que o servidor serve ---------------------

DOC = REPO / "docs" / "usar-o-mcp.md"
NUMERAIS = {1: "ferramenta", 2: "duas ferramentas", 3: "três ferramentas"}
"""Como o título da seção conta as ferramentas. Só os casos que podem existir."""


def _secao_das_ferramentas() -> str:
    texto = DOC.read_text(encoding="utf-8")
    inicio = re.search(r"^## As .*ferramentas?\s*$", texto, re.MULTILINE)
    assert inicio, "a seção que descreve as ferramentas mudou de título"
    resto = texto[inicio.end() :]
    fim = re.search(r"^## ", resto, re.MULTILINE)
    return inicio.group(0) + (resto[: fim.start()] if fim else resto)


def test_o_doc_do_usuario_descreve_exatamente_as_ferramentas_que_existem() -> None:
    """A `neighbors` esteve um mês no servidor e cinco dias fora deste doc.

    O doc dizia "duas ferramentas" e "`neighbors` continua hipótese" enquanto ela
    já respondia no `.mcp.json` do usuário. Documentação que descreve uma
    superfície menor que a real é o pior tipo de erro de doc: parece conservadora
    e faz o leigo não usar o que ele já tem instalado.

    A classe é "doc de usuário afirma superfície que o código não tem"
    (regra 12), e o que a fecha é este teste: ferramenta nova sem entrar no doc
    reprova, e nome no doc que não é ferramenta também.
    """
    secao = _secao_das_ferramentas()
    documentadas = set(re.findall(r"\*\*`(\w+)\(", secao))

    assert documentadas == FERRAMENTAS, (
        f"o doc descreve {sorted(documentadas)} e o servidor serve {sorted(FERRAMENTAS)}"
    )
    assert NUMERAIS[len(FERRAMENTAS)] in secao.splitlines()[0].lower()


def test_a_armadilha_do_caminho_esta_armada(tmp_path: Path) -> None:
    """Guarda da guarda: uma armadilha que virou no-op é pior que nenhuma.

    Sem isto, o teste acima continuaria verde no dia em que alguém trocasse a
    classe do servidor de teste pela `BuscaHibrida` normal — e passaria a provar
    nada, silenciosamente.
    """
    from segundocerebro.index.store import Store

    from tests.servidor_falso import BuscaSoPeloCaminhoEntregue
    from tests.falsos import DIM, EmbedderFalso

    store = Store(tmp_path / "i", DIM)
    busca = BuscaSoPeloCaminhoEntregue(store, EmbedderFalso())
    try:
        with pytest.raises(AssertionError, match="buscar_chunks"):
            busca.search("qualquer", 3)
    finally:
        store.fechar()
