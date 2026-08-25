"""Todo parser registrado é exercitado pelo corpus — e a lista sai do produto.

`parsers.supported_extensions()` é o que o indexador consulta para decidir se
sabe ler um arquivo. Se o corpus sintético não tem nenhum documento de uma dessas
extensões, aquele parser **nunca roda** numa medição, e o primeiro a descobrir
que ele quebrou é o usuário.

Medido em 25/08/2026, antes deste pacote: o gerador emitia 9 formatos e o produto
registrava 17. Nove parsers cegos, entre eles o `.msg` — que é **3,5% do acervo
real** e o formato de email que existe lá, enquanto o corpus usava `.eml`, que lá
é 0%.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.census import caminho_estendido
from segundocerebro.ingest.document import ParseStatus
from segundocerebro.ingest.parsers import supported_extensions
from segundocerebro.ingest.reader import parse_file

from eval.gerador.__main__ import gerar
from eval.gerador.formatos import SO_HOSTIL


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destino = tmp_path_factory.mktemp("formatos")
    gerar(42, 4, destino, sem_docx=False)
    return destino / "corpus"


def _extensoes_no_corpus(corpus: Path) -> set[str]:
    from segundocerebro.census import Census, Config, RootSpec, iter_files

    cfg = Config(roots=(RootSpec(name="fmt", path=corpus),))
    return {Path(a.path).suffix.lower() for a in iter_files(cfg.roots[0], cfg, Census())}


def test_todo_parser_registrado_tem_documento_no_corpus(corpus: Path) -> None:
    """A cobertura sai de `supported_extensions()`, não de uma lista escrita à mão.

    Parser novo sem fixture reprova aqui, e quem registrou o parser descobre no
    mesmo dia — em vez de o corpus ficar cego por uma fase inteira.
    """
    registradas = {e.lower() for e in supported_extensions()}
    presentes = _extensoes_no_corpus(corpus)

    faltando = registradas - presentes
    assert not faltando, (
        f"parser sem documento no corpus: {sorted(faltando)}. Acrescente a fixture em "
        f"`eval/gerador/formatos.py`, ou declare em `SO_HOSTIL` com o motivo escrito."
    )


def test_a_lista_de_lacunas_declaradas_nao_cresce_por_conveniencia() -> None:
    """`SO_HOSTIL` é para o que não se consegue gerar, não para o que dá trabalho.

    Hoje tem um item, e ele tem motivo medido: `.xls` válido exige BIFF, o `xlrd`
    recusa CFB inventado (`XLRDError: Expected BOF record`) e escrever BIFF pediria
    o `xlwt`, que não é dependência do projeto. O `.xls` aparece no corpus nas
    duas formas **hostis**, que são as que o `F4-L` persegue.
    """
    assert SO_HOSTIL == {".xls"}, (
        f"a lista de lacunas mudou para {sorted(SO_HOSTIL)} — cada item precisa do "
        f"motivo escrito no módulo, e a lacuna declarada é a única que não vira dívida"
    )
    assert SO_HOSTIL <= {e.lower() for e in supported_extensions()}


def test_cada_formato_devolve_o_identificador_plantado(corpus: Path) -> None:
    """Gerar o arquivo não basta: o parser do produto tem de achar o conteúdo.

    É a lição de medir com o instrumento real. Um `.pptm` que o `python-pptx`
    escreve e o nosso parser não lê seria cobertura de mentira — o corpus diria
    ter o formato e a medição não veria nada dentro.
    """
    pasta = corpus / "11. Formatos"
    conferidos = 0
    for arquivo in sorted(pasta.iterdir()):
        if not arquivo.is_file():
            continue
        resultado = parse_file(str(arquivo), retries=0)
        assert resultado.status is ParseStatus.OK, f"{arquivo.name}: {resultado.status.value}"
        texto = "\n".join(b.text for b in resultado.doc.blocks)
        assert "CT-FT-" in texto, f"{arquivo.name}: o identificador plantado não voltou"
        conferidos += 1

    assert conferidos == len(supported_extensions()) - len(SO_HOSTIL), conferidos


def test_o_msg_e_container_ole_de_verdade(corpus: Path) -> None:
    """`.msg` é 3,5% do acervo real e o corpus não tinha nenhum.

    O container é escrito byte a byte a partir da especificação
    (`eval/gerador/cfb.py`) e lido pelo `olefile`, que é implementação
    independente. Isso é o oposto de um mock: arquivo errado, `olefile` reclama.
    """
    import olefile

    msgs = list((corpus / "11. Formatos").glob("*.msg"))
    assert msgs, "nenhum .msg no corpus"
    assert olefile.isOleFile(str(msgs[0])), "não é um container OLE válido"


def test_o_legado_ole_tem_fixture_mesmo_sendo_pacote_do_desktop(corpus: Path) -> None:
    """`.doc` e `.ppt` no corpus — o `F4-L` ganha material contra o que medir.

    O pacote é do desktop (`docs/colaboracao.md` §1) e os parsers não foram
    tocados. O que o notebook entrega é a fixture: até aqui o `F4-L` estava aberto
    **sem nenhum arquivo legado** contra o qual rodar.
    """
    pasta = corpus / "11. Formatos"
    assert list(pasta.glob("*.doc")), "sem .doc no corpus"
    assert list(pasta.glob("*.ppt")), "sem .ppt no corpus"


def test_o_xls_so_existe_em_forma_hostil(corpus: Path) -> None:
    """A lacuna declarada, conferida: nenhum `.xls` do corpus é lido com sucesso.

    Se um dia alguém gerar BIFF de verdade, este teste reprova — e reprovar é o
    certo, porque aí `SO_HOSTIL` está desatualizado.
    """
    for arquivo in corpus.rglob("*.xls"):
        resultado = parse_file(caminho_estendido(arquivo), retries=0)
        if resultado.status is ParseStatus.OK:
            texto = "\n".join(b.text for b in resultado.doc.blocks)
            assert "CT-FT-" not in texto, (
                f"{arquivo.name} é um .xls válido com conteúdo plantado — "
                f"tirar `.xls` de SO_HOSTIL"
            )
