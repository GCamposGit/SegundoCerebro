"""`J.b1`: o id público sobrevive ao que o acervo faz com os arquivos.

Duas classes de defeito, e as duas foram medidas no acervo corporativo antes de
virarem teste (`docs/plano-pacote-j.md` §3.2 e §3.3):

- **Identidade por caminho, num acervo que move arquivo.** O pacote J promete
  workflow *"repetível semana após semana com resultado idêntico"*. Um id que
  muda quando alguém arrasta a pasta quebra isso sem erro nenhum — o agente
  simplesmente não acha mais o documento da semana passada.
- **Preferência por ordem de indexação.** 223 de 2.127 caminhos (10,5%) são
  byte-idênticos a outro, e até aqui "o principal" era o primeiro `ok` que o
  SQLite entregasse. Isso é aleatoriedade com cara de determinismo, e o teste que
  a pega é o que indexa **os mesmos arquivos em duas ordens** e exige a mesma
  resposta.
"""

from __future__ import annotations

import pytest

from segundocerebro.acesso import identidade, registro
from segundocerebro.index.store import Store

HASH_A = "a" * 64
HASH_B = "b1c2d3e4f5a6" + "0" * 52


def registrar(store: Store, path: str, sha256: str, mtime: float, status: str = "ok") -> None:
    store.registrar_documento(
        path=path,
        raiz="acervo",
        tamanho=10,
        mtime=mtime,
        sha256=sha256,
        status=status,
        n_chunks=1 if status == "ok" else 0,
        model_id="falso:8",
        chunker="v1",
        parser="p1",
    )
    store.commit()


# --- o id ---------------------------------------------------------------------


def test_id_e_prefixo_do_hash_e_sobrevive_a_renomear_e_mover(store: Store) -> None:
    """Mesmo conteúdo em outro caminho: mesmo id. É a razão de ele existir."""
    registrar(store, "Projetos/Plano.docx", HASH_B, 100.0)
    antes = registro.documento_de_caminho(store, "Projetos/Plano.docx")
    assert antes is not None
    assert antes.doc_id == HASH_B[: identidade.TAMANHO_DOC_ID]

    store.esquecer_documento("Projetos/Plano.docx")
    registrar(store, "Arquivo Morto/2024/Plano - Copia.docx", HASH_B, 100.0)
    depois = registro.documento_de_caminho(store, "Arquivo Morto/2024/Plano - Copia.docx")

    assert depois is not None
    assert depois.doc_id == antes.doc_id, "renomear e mover não muda o conteúdo, logo não muda o id"


def test_conteudo_diferente_muda_o_id(store: Store) -> None:
    registrar(store, "a.docx", HASH_A, 1.0)
    registrar(store, "b.docx", HASH_B, 1.0)
    a = registro.documento_de_caminho(store, "a.docx")
    b = registro.documento_de_caminho(store, "b.docx")
    assert a is not None and b is not None
    assert a.doc_id != b.doc_id


def test_documento_sem_hash_declara_por_que_nao_tem_id(store: Store) -> None:
    """Campo vazio é o silêncio que este repositório já pagou caro.

    1,3% do acervo (29 de 2.156) não tem `sha256`, e é por construção: o portão
    de leitura recusa placeholder de nuvem **antes** de abrir, porque abrir
    dispara download. Hashear todo mundo seria baixar o acervo.
    """
    registrar(store, "Nuvem/Contrato.pdf", "", 1.0, status="sem_parser")
    doc = registro.documento_de_caminho(store, "Nuvem/Contrato.pdf")

    assert doc is not None
    assert doc.doc_id == ""
    assert doc.sem_id, "id ausente sem motivo é o campo vazio que ninguém investiga"
    assert "formato" in doc.sem_id


def test_id_curto_demais_ou_nao_hexadecimal_nao_vira_id() -> None:
    assert identidade.doc_id_de("abc") is None
    assert identidade.doc_id_de("zzzzzzzzzzzz") is None
    assert identidade.doc_id_de("") is None


# --- a preferência entre caminhos ---------------------------------------------


DUPLICATAS = {
    "Contratos/2026/Acordo.pdf": 500.0,
    "Backup/Acordo.pdf": 100.0,
    "Compartilhado/Acordo.pdf": 300.0,
}


@pytest.mark.parametrize("ordem", [list(DUPLICATAS), sorted(DUPLICATAS, reverse=True)])
def test_o_preferido_nao_depende_da_ordem_de_indexacao(tmp_path, ordem) -> None:  # noqa: ANN001
    """A classe: workflow que devolve outro documento porque a passada foi outra.

    Duas ordens de inserção, o mesmo conteúdo, e a resposta tem de ser a mesma.
    Sem isto, `path_ok_por_sha256` devolve o primeiro `ok` que o SQLite entregar.
    """
    s = Store(tmp_path / f"i{len(ordem)}{ordem[0][0]}", 8)
    try:
        for path in ordem:
            registrar(s, path, HASH_B, DUPLICATAS[path])
        doc = registro.resolver(s, identidade.interpretar(HASH_B[:12]))
        assert doc is not None
        assert doc.caminho == "Contratos/2026/Acordo.pdf", "o mais recente representa a família"
        assert set(doc.caminhos) == set(DUPLICATAS)
        assert doc.duplicado
    finally:
        s.fechar()


def test_a_preferencia_e_a_mesma_de_familias(store: Store) -> None:
    """Uma noção de "o principal" no produto, não duas.

    `familias.por_vigencia` decide por número de versão declarado antes da data,
    e o caso `g045` é a razão: `_v0.xlsx` é de janeiro de 2026 e `_v1.xlsx` de
    setembro de 2025, porque reabrir arquivo renova `mtime` sem criar versão. Se
    a identidade tivesse regra própria, o mesmo acervo teria dois "principais".
    """
    registrar(store, "Planilhas/Custos_v0.xlsx", HASH_A, 900.0)
    registrar(store, "Planilhas/Custos_v1.xlsx", HASH_A, 100.0)
    doc = registro.resolver(store, identidade.interpretar(HASH_A[:12]))
    assert doc is not None
    assert doc.caminho.endswith("_v1.xlsx"), "número declarado vence a data — como no g045"


# --- a URI --------------------------------------------------------------------


def test_caminho_e_uri_resolvem_para_o_mesmo_documento(store: Store) -> None:
    registrar(store, "Projetos/Plano.docx", HASH_B, 100.0)
    por_caminho = registro.resolver(store, identidade.interpretar("Projetos/Plano.docx"))
    por_id = registro.resolver(store, identidade.interpretar(HASH_B[:12]))
    por_uri = registro.resolver(
        store, identidade.interpretar(identidade.montar_uri("corp", HASH_B[:12]))
    )

    assert por_caminho == por_id == por_uri
    assert por_uri is not None


def test_uri_de_outra_base_e_erro_e_nunca_um_seletor() -> None:
    """Invariante 7: isolamento entre bases é físico, não filtro.

    A URI nomeia a base **dentro do endereço**, e uma tool que a tratasse como
    parâmetro reintroduziria "base como filtro de metadado" pela porta dos
    fundos. Aqui o nome só confere.
    """
    ref = identidade.interpretar(identidade.montar_uri("pessoal", HASH_B[:12]))
    assert identidade.conferir_base(ref, "corporativa")
    assert identidade.conferir_base(ref, "pessoal") == ""
    assert identidade.conferir_base(identidade.interpretar(HASH_B[:12]), "corporativa") == ""


def test_uri_malformada_diz_o_que_esperava() -> None:
    for texto in ["sc://", "sc://corp", "sc://corp/", "sc://corp/nao-e-hex"]:
        ref = identidade.interpretar(texto)
        assert ref.erro, f"{texto!r} devia ser recusado"
        assert not ref.valida


def test_barra_invertida_e_barra_sao_a_mesma_pasta() -> None:
    assert registro.normalizar_prefixo("a\\b") == registro.normalizar_prefixo("a/b/") == "a/b/"
    assert registro.normalizar_prefixo(".") == registro.normalizar_prefixo("") == ""


# --- o custo ------------------------------------------------------------------


def test_o_indice_de_sha256_existe(store: Store) -> None:
    """Sem ele, resolver id é varredura de tabela — o N+1 com outro nome.

    A guarda é sobre o índice existir no esquema, não sobre o plano de consulta:
    o SQLite pode escolher não usá-lo num banco de três linhas, e assertar sobre
    a escolha do planejador seria assertar sobre a janela, não sobre o produto.
    """
    indices = {
        r["name"]
        for r in store.con.execute("PRAGMA index_list(documentos)")  # type: ignore[index]
    }
    assert "idx_documentos_sha256" in indices


class _ConContada:
    """Envelope que conta `execute()` e o tamanho de cada lista de parâmetros."""

    def __init__(self, con) -> None:  # noqa: ANN001
        self._con = con
        self.total = 0
        self.maior_lote = 0

    def execute(self, sql, *args, **kwargs):  # noqa: ANN001, ANN201
        self.total += 1
        if args and isinstance(args[0], (tuple, list)):
            self.maior_lote = max(self.maior_lote, len(args[0]))
        return self._con.execute(sql, *args, **kwargs)

    def __getattr__(self, nome: str):  # noqa: ANN204
        return getattr(self._con, nome)


TETO_DE_CONSULTAS = 4
"""Quantas idas ao SQLite listar uma pasta pode custar, **independente do N**.

O N+1 deste repositório custou 350 consultas por busca e era invisível no índice
de quatro trechos: a forma do acesso é a mesma, só o N muda. Aqui a forma é
"uma consulta para os documentos, uma para os irmãos de conteúdo", e este teste
guarda a forma listando 30 documentos — se alguém resolver irmão por documento,
o número vira 31.
"""


def test_listar_pasta_nao_custa_uma_consulta_por_documento(store: Store) -> None:
    for i in range(30):
        registrar(store, f"Pasta/doc{i:02d}.docx", f"{i:064x}", float(i))

    store.con = _ConContada(store.con)
    try:
        docs = registro.documentos_da_pasta(store, "Pasta")
        gastas = store.con.total
    finally:
        store.con = store.con._con

    assert len(docs) == 30
    assert gastas <= TETO_DE_CONSULTAS, (
        f"{gastas} idas ao SQLite para listar 30 documentos (teto {TETO_DE_CONSULTAS}). "
        "Alguma leitura virou uma por item — use `_irmaos_em_lote`."
    )


def test_nenhuma_consulta_manda_mais_parametros_do_que_o_sqlite_aceita(store: Store) -> None:
    """`IN (...)` sem lote estoura no acervo real e passa na suíte — se a suíte for pequena.

    O SQLite tem teto de parâmetros por statement (999 nas bibliotecas antigas), e
    a build que roda na máquina do usuário não é escolha nossa. Uma pasta de 2.156
    documentos derrubaria a tool com `too many SQL variables`.

    A guarda **não** é "listar 1.100 documentos e ver se explode": num SQLite com
    teto de 32.766 isso passaria por acidente, que é o modo de falha das provas
    deste repositório. O que se afirma aqui é sobre o produto — nenhuma consulta
    da camada envia mais que `LOTE_DE_PARAMETROS` valores —, e essa afirmação não
    depende da build.
    """
    for i in range(registro.LOTE_DE_PARAMETROS * 2 + 7):
        registrar(store, f"Grande/doc{i:05d}.docx", f"{i:064x}", float(i))

    store.con = _ConContada(store.con)
    try:
        docs = registro.documentos_da_pasta(store, "Grande")
        registro.texto_por_documento(store, [d.caminho for d in docs])
        maior = store.con.maior_lote
    finally:
        store.con = store.con._con

    assert len(docs) == registro.LOTE_DE_PARAMETROS * 2 + 7
    assert maior <= registro.LOTE_DE_PARAMETROS, (
        f"uma consulta mandou {maior} parâmetros de uma vez. Passe por `_em_lotes` — "
        "o teto do SQLite é da build, não nosso."
    )
