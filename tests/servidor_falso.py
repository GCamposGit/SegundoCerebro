"""O servidor MCP como processo de verdade, sem carregar modelo.

É o outro lado de `test_protocolo_mcp.py`: aquele arquivo é o cliente, este é o
servidor que ele sobe. Existe como script separado, e não como fixture, porque o
que se quer provar só existe **entre** dois processos — o enquadramento JSON-RPC,
o esquema que o cliente lê para saber como chamar, e o cano de bytes do Windows.
Fixture em memória não tem cano.

    py tests/servidor_falso.py --indice <dir> [--base <id>]

O índice é montado aqui dentro, no diretório recebido: o teste passa um
`tmp_path` vazio e não sabe o que tem dentro. Assim existe **um** lugar que
descreve o acervo de teste do protocolo, em vez de um lado montando e o outro
afirmando sobre o que o primeiro montou.

**Nenhum modelo é carregado.** O embedder é o `EmbedderFalso` de
`tests/test_index.py` — o mesmo que o resto da suíte usa, de propósito: uma
segunda cópia dele divergiria, e a divergência apareceria como "o protocolo
devolve outra coisa", que é justamente o defeito que a suíte de protocolo existe
para pegar.
"""

from __future__ import annotations

import argparse
import sys
from hashlib import sha256
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for caminho in (str(RAIZ), str(RAIZ / "src")):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

from segundocerebro.config import Base  # noqa: E402
from segundocerebro.index.store import Store  # noqa: E402
from segundocerebro.mcp.server import Recursos, construir  # noqa: E402
from segundocerebro.retrieve.grafo import construir as construir_grafo  # noqa: E402
from segundocerebro.retrieve.hybrid import BuscaHibrida  # noqa: E402
from tests.falsos import DIM, EmbedderFalso, chunk  # noqa: E402
from segundocerebro.ingest.canonico import renderizar  # noqa: E402
from segundocerebro.ingest.document import Block, ParsedDoc  # noqa: E402
from segundocerebro.ingest.parse_store import Chave, ParseStore  # noqa: E402
from segundocerebro.ingest.parsers import parser_version_for  # noqa: E402

POLITICA = "Política de IA/PO-ACME-007 — política 📄.docx"
"""Acento, travessão e um caractere fora do cp1252, no **caminho**.

Não é capricho: `mcp/registrar.py` fixa `PYTHONIOENCODING=utf-8` porque sem isso
o Windows entrega cp1252 no stdio e um acento no caminho de um documento corrompe
o fluxo do protocolo. Um corpus de teste só com ASCII deixa esse comentário sem
nada que o defenda — e a procedência, que é o invariante 5, é justamente o campo
que carrega o caminho.
"""

PLANO = "Planos/plano de ação.md"
NORMA = "Normas/gestão de IA.md"

BASE_DE_TESTE = {
    "nome": "Acme Holding",
    "descricao": "Contratos, propostas e atas da Acme Holding",
}
"""Vocabulário fictício, o mesmo de `test_mcp.py`. A descrição entra porque ela é
o único sinal pelo qual o cliente escolhe entre duas bases (`ARCHITECTURE.md` §2),
e o teste de protocolo confere que ela chega até lá."""

TRECHOS = [
    (
        "politica#0",
        POLITICA,
        0,
        "A política de governança de inteligência artificial da Acme Holding.",
        ("Política de IA", "Escopo"),
    ),
    (
        "politica#1",
        POLITICA,
        1,
        "O uso aceitável exige revisão humana de toda decisão automatizada.",
        ("Política de IA", "Uso aceitável"),
    ),
    (
        "politica#2",
        POLITICA,
        2,
        "A revisão do contrato de fornecimento cabe ao jurídico.",
        ("Política de IA", "Contratos"),
    ),
    ("plano#0", PLANO, 0, "Meta do plano de ação: certificação ISO 42001 até 2027.", ("Plano",)),
    ("norma#0", NORMA, 0, "A ISO 42001 define o sistema de gestão de IA.", ("Norma",)),
]


def canonico_de(path: str):
    return renderizar(ParsedDoc(path, tuple(
        Block(trilha, texto) for _id, p, _ord, texto, trilha in TRECHOS if p == path
    )))


def montar_indice(diretorio: Path) -> Store:
    """Índice minúsculo com o que as três ferramentas precisam para responder.

    Três trechos no mesmo documento (para `read_note` ter vizinho e para o
    contexto do `search` ter o que anexar) e um par plano/norma ligado só pelo
    identificador citado nos dois (para `neighbors` ter aresta).
    """
    emb = EmbedderFalso()
    store = Store(diretorio, DIM)
    chunks = [chunk(i, p, o, t, trilha) for i, p, o, t, trilha in TRECHOS]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), 0.0, emb.model_id)

    for path in (POLITICA, PLANO, NORMA):
        canonico = canonico_de(path)
        sha = sha256(canonico.markdown.encode()).hexdigest()
        parser = parser_version_for(Path(path).suffix)
        ParseStore(diretorio).gravar(Chave(sha, parser), canonico)
        store.registrar_documento(
            path=path,
            raiz="r",
            tamanho=1,
            mtime=0.0,
            status="ok",
            sha256=sha, parser=parser,
            n_chunks=sum(1 for c in chunks if c.doc_path == path),
            model_id=emb.model_id,
        )
    store.commit()
    construir_grafo(store)
    return store


class BuscaSoPeloCaminhoEntregue(BuscaHibrida):
    """`search` explode de propósito — o cliente MCP tem de passar por `buscar_chunks`.

    É a classe de defeito do `F4-P.0` posta como armadilha em vez de como
    relatório: o eval media `search` e o cliente executava `buscar_chunks`, e
    ninguém soube por uma fase inteira. Enquanto este servidor responde, a
    ferramenta `search` do MCP **não** está caindo no ranqueador de documento; no
    dia em que cair, o teste de protocolo fica vermelho no mesmo commit.
    """

    def search(self, consulta: str, k: int) -> list:
        raise AssertionError(
            "a ferramenta MCP `search` chamou BuscaHibrida.search — o caminho "
            "entregue ao cliente é buscar_chunks (F4-P.0)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="servidor_falso")
    parser.add_argument("--indice", type=Path, required=True)
    parser.add_argument("--base", help="id da base, para nome, título e instruções")
    args = parser.parse_args(argv)

    store = montar_indice(args.indice)
    base = Base(id=args.base, indice=args.indice, **BASE_DE_TESTE) if args.base else None

    emb = EmbedderFalso()
    busca = (
        BuscaSoPeloCaminhoEntregue.de_base(store, emb, base)
        if base is not None
        else BuscaSoPeloCaminhoEntregue(store, emb)
    )
    recursos = Recursos(indice=args.indice, modelo="falso", threads=1, base=base)
    recursos._store = store
    recursos._busca = busca

    construir(recursos).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
