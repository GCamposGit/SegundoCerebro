"""`J.a`: o parse store, e as quatro classes que ele não pode ter.

1. **Cache que serve parse velho depois de o parser mudar.** Inclui o motor
   externo: LibreOffice e OCR saem do nosso controle, e um upgrade de sistema não
   commita nada — a regra de PR que a especificação propõe como mitigação **não
   dispara**. Se a versão do motor não está na chave, o cache serve o parse de
   antes do upgrade para sempre, e o sintoma é conteúdo desatualizado servido com
   confiança.
2. **Divergência silenciosa entre a renderização e a estrutura.** O offset aponta
   para o meio de outra frase e a citação sai errada sem erro nenhum. Fechada por
   property test de reconstrução, chamando o **produto** e não uma cópia da regra
   dentro do teste.
3. **Cache que muda o resultado.** Store quente e store frio têm de produzir o
   mesmo canônico, byte a byte.
4. **GC que apaga o que está em uso.** Censo vazio quase sempre significa "o
   censo não rodou", e obedecer apagaria o store inteiro em silêncio — a mesma
   classe de `docs/duas-falhas-silenciosas.md`, onde menos arquivo é justamente o
   que se pediu.
"""

from __future__ import annotations

import random
import zlib
from pathlib import Path

import pytest

from segundocerebro.ingest import parse_store as ps
from segundocerebro.ingest.canonico import renderizar
from segundocerebro.ingest.document import Block, BlockKind, ParsedDoc

SHA = "a1b2c3" + "0" * 58
OUTRO_SHA = "f9e8d7" + "0" * 58


def documento(n_blocos: int = 4, semente: int = 7) -> ParsedDoc:
    """Um `ParsedDoc` variado: trilhas que entram, saem e repetem."""
    sorteio = random.Random(semente)
    trilhas = [
        (),
        ("Política de IA",),
        ("Política de IA", "Escopo"),
        ("Política de IA", "Escopo", "Exceções"),
        ("Política de IA", "Prazos"),
        ("Anexo", "Tabela", "Coluna", "Detalhe", "Subdetalhe", "Nível 6", "Nível 7"),
    ]
    blocos = []
    for i in range(n_blocos):
        trilha = trilhas[sorteio.randrange(len(trilhas))]
        blocos.append(
            Block(
                heading_path=trilha,
                text=f"Parágrafo {i} com acento, quebra\ninterna e ## cerquilha literal.",
                locator=f"p. {i // 2 + 1}",
                kind=BlockKind.TABLE if i % 3 == 0 else BlockKind.TEXT,
            )
        )
    return ParsedDoc(name="doc.docx", blocks=tuple(blocos), meta={"formato": "docx", "b": "1"})


# --- a renderização canônica --------------------------------------------------


@pytest.mark.parametrize("semente", range(12))
def test_todo_bloco_recorta_o_proprio_texto_no_markdown(semente: int) -> None:
    """O invariante do `J.b2`, sobre documento sorteado e não sobre um exemplo.

    A prova chama `canonico.texto_de`, que é o **produto**. Prova que copia a
    guarda prova a cópia: três provas desta base já tinham a mesma cegueira da
    guarda que conferiam, porque saíram da mesma cabeça no mesmo dia.
    """
    doc = documento(n_blocos=1 + semente, semente=semente)
    canonico = renderizar(doc)

    assert len(canonico.blocos) == len(doc.blocks)
    for bloco, original in zip(canonico.blocos, doc.blocks):
        assert canonico.texto_de(bloco) == original.text
        assert bloco.chars == len(original.text)


def test_reconstruir_devolve_os_blocos_de_origem() -> None:
    from segundocerebro.ingest.canonico import reconstruir

    doc = documento(9, semente=3)
    voltou = reconstruir(renderizar(doc))

    assert [b.text for b in voltou] == [b.text for b in doc.blocks]
    assert [b.heading_path for b in voltou] == [b.heading_path for b in doc.blocks]
    assert [b.locator for b in voltou] == [b.locator for b in doc.blocks]


def test_a_renderizacao_e_deterministica_e_nao_carrega_relogio() -> None:
    doc = documento(6, semente=5)
    a, b = renderizar(doc), renderizar(doc)

    assert a.markdown == b.markdown
    assert a.blocos == b.blocos
    assert "2026" not in a.markdown, "data de geração no artefato quebra a byte-identidade"


def test_heading_nunca_passa_de_seis_cerquilhas() -> None:
    """`#######` não é heading em Markdown nenhum, e a trilha real chega a sete."""
    doc = ParsedDoc(
        name="fundo.xlsx",
        blocks=(Block(heading_path=tuple(f"n{i}" for i in range(9)), text="fundo"),),
    )
    for linha in renderizar(doc).markdown.splitlines():
        if linha.startswith("#"):
            assert len(linha) - len(linha.lstrip("#")) <= 6, linha


def test_a_trilha_e_emitida_por_diferenca_e_nao_repetida() -> None:
    doc = ParsedDoc(
        name="x.docx",
        blocks=(
            Block(heading_path=("A", "B"), text="um"),
            Block(heading_path=("A", "B"), text="dois"),
        ),
    )
    assert renderizar(doc).markdown.count("## B") == 1


# --- a chave ------------------------------------------------------------------


def test_a_chave_separa_rota_parser_e_motor() -> None:
    base = ps.Chave(sha256=SHA, parser="pdf:2", rota=ps.ROTA_NATIVA)
    digests = {
        base.digest(),
        ps.Chave(sha256=OUTRO_SHA, parser="pdf:2").digest(),
        ps.Chave(sha256=SHA, parser="pdf:3").digest(),
        ps.Chave(sha256=SHA, parser="pdf:2", rota=ps.ROTA_OCR).digest(),
        ps.Chave(sha256=SHA, parser="pdf:2", motor="soffice:1:2").digest(),
    }
    assert len(digests) == 5, "duas condições diferentes com o mesmo digest é cache errado"


def test_upgrade_do_motor_externo_invalida_a_entrada(tmp_path: Path) -> None:
    """A classe 1, e a única que a especificação sub-declarava.

    Ninguém commita um upgrade de LibreOffice, então a regra de PR não dispara. Se
    o motor não estiver na chave, o cache serve o parse velho para sempre.
    """
    store = ps.ParseStore(tmp_path / "indice")
    antes = ps.Chave(sha256=SHA, parser="doc:1", rota=ps.ROTA_LIBREOFFICE, motor="soffice:100:1")
    depois = ps.Chave(sha256=SHA, parser="doc:1", rota=ps.ROTA_LIBREOFFICE, motor="soffice:200:2")

    store.gravar(antes, renderizar(documento(2)))

    assert store.obter(antes) is not None
    assert store.obter(depois) is None, "motor novo tem de dar miss, não servir o parse velho"


def test_a_versao_da_renderizacao_entra_na_chave(monkeypatch: pytest.MonkeyPatch) -> None:
    """Melhorar a renderização não pode deixar o cache servindo a antiga.

    Duas afirmações, e a primeira é a que quase passou por acidente: o store tem
    de usar **a** versão do módulo que renderiza, não uma constante própria que
    envelhece em paralelo. `from ... import X` liga o nome uma vez, então patchar
    `canonico.X` não alcança o store — e um teste que só patchasse lá passaria
    verde sobre um store que ignora a versão.
    """
    from segundocerebro.ingest import canonico

    assert ps.VERSAO_CANONICA == canonico.VERSAO_CANONICA

    chave = ps.Chave(sha256=SHA, parser="pdf:2")
    antes = chave.digest()
    monkeypatch.setattr(ps, "VERSAO_CANONICA", "canonico:99")
    assert chave.digest() != antes


def test_parse_sem_hash_nao_ganha_entrada(tmp_path: Path) -> None:
    """Chave incompleta gravaria entrada que nenhum `obter` acha — lixo silencioso.

    1,3% do acervo não tem `sha256`, por construção: o portão de leitura recusa
    placeholder de nuvem antes de abrir.
    """
    store = ps.ParseStore(tmp_path / "indice")
    assert store.gravar(ps.Chave(sha256="", parser="pdf:2"), renderizar(documento(1))) is None
    assert store.obter(ps.Chave(sha256="", parser="pdf:2")) is None
    assert store.estatisticas()["entradas"] == 0


# --- o disco ------------------------------------------------------------------


def test_ida_e_volta_pelo_disco_preserva_tudo(tmp_path: Path) -> None:
    store = ps.ParseStore(tmp_path / "indice")
    chave = ps.Chave(sha256=SHA, parser="docx:2")
    original = renderizar(documento(7, semente=11))

    store.gravar(chave, original)
    lido = store.obter(chave)

    assert lido is not None
    assert lido.markdown == original.markdown
    assert lido.blocos == original.blocos
    assert lido.meta == original.meta


def test_gravar_duas_vezes_produz_o_mesmo_byte(tmp_path: Path) -> None:
    """A byte-identidade que o `J.a` promete, no artefato e não só no conteúdo."""
    store = ps.ParseStore(tmp_path / "indice")
    chave = ps.Chave(sha256=SHA, parser="docx:2")
    canonico = renderizar(documento(5, semente=2))

    store.gravar(chave, canonico)
    primeiro = store.caminho(chave).read_bytes()
    store.gravar(chave, canonico)
    segundo = store.caminho(chave).read_bytes()

    assert primeiro == segundo


def test_o_store_vive_dentro_do_indice_e_nunca_fora(tmp_path: Path) -> None:
    """Invariante 1 do pacote J: nada derivado é escrito nas pastas do usuário."""
    indice = tmp_path / "indice"
    acervo = tmp_path / "acervo"
    acervo.mkdir()

    store = ps.ParseStore(indice)
    store.gravar(ps.Chave(sha256=SHA, parser="docx:2"), renderizar(documento(2)))

    assert list(acervo.rglob("*")) == [], "o acervo é somente-leitura, sempre"
    assert store.raiz.is_relative_to(indice)


def test_entrada_corrompida_e_miss_e_nao_excecao(tmp_path: Path) -> None:
    """O store é descartável: entrada ilegível não pode derrubar a passada."""
    store = ps.ParseStore(tmp_path / "indice")
    chave = ps.Chave(sha256=SHA, parser="docx:2")
    store.gravar(chave, renderizar(documento(2)))
    store.caminho(chave).write_bytes(b"isto nao e zlib")

    assert store.obter(chave) is None
    assert not store.caminho(chave).exists(), "entrada podre é apagada, para a próxima reparsear"


def test_temporario_interrompido_nao_vira_entrada(tmp_path: Path) -> None:
    """`kill` no meio da escrita não deixa entrada meio gravada.

    A escrita é temp + `os.replace` no **mesmo diretório** — `os.replace` só é
    atômico dentro do mesmo volume, e `%TEMP%` pode estar em outro disco.
    """
    store = ps.ParseStore(tmp_path / "indice")
    chave = ps.Chave(sha256=SHA, parser="docx:2")
    alvo = store.caminho(chave)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    (alvo.parent / f"{alvo.name}.tmp999").write_bytes(zlib.compress(b'{"markdown":"meio"}'))

    assert store.obter(chave) is None
    assert store.estatisticas()["entradas"] == 0, "temporário não conta como entrada"


def test_apagar_o_store_nao_perde_nada_que_nao_se_regenere(tmp_path: Path) -> None:
    store = ps.ParseStore(tmp_path / "indice")
    chave = ps.Chave(sha256=SHA, parser="docx:2")
    canonico = renderizar(documento(3, semente=4))
    store.gravar(chave, canonico)

    store.apagar_tudo()
    assert store.obter(chave) is None

    store.gravar(chave, canonico)
    assert store.obter(chave) == canonico, "regenerar dá o mesmo — o store é 100% derivado"


# --- o GC ---------------------------------------------------------------------


def envelhecer(caminho: Path, dias: int) -> None:
    import os

    quando = caminho.stat().st_mtime - dias * 86400
    os.utime(caminho, (quando, quando))


def test_o_gc_remove_o_que_saiu_do_censo_depois_da_carencia(tmp_path: Path) -> None:
    store = ps.ParseStore(tmp_path / "indice")
    viva = ps.Chave(sha256=SHA, parser="docx:2")
    morta = ps.Chave(sha256=OUTRO_SHA, parser="docx:2")
    store.gravar(viva, renderizar(documento(2)))
    store.gravar(morta, renderizar(documento(2)))
    envelhecer(store.caminho(viva), 30)
    envelhecer(store.caminho(morta), 30)

    assert store.gc([SHA], carencia_dias=14) == 1
    assert store.obter(viva) is not None
    assert store.obter(morta) is None


def test_o_gc_nunca_remove_entrada_recente(tmp_path: Path) -> None:
    """A carência protege o censo que rodou parcial — pasta de rede fora do ar."""
    store = ps.ParseStore(tmp_path / "indice")
    morta = ps.Chave(sha256=OUTRO_SHA, parser="docx:2")
    store.gravar(morta, renderizar(documento(2)))

    assert store.gc([SHA], carencia_dias=14) == 0
    assert store.obter(morta) is not None


def test_censo_vazio_e_recusado_em_vez_de_apagar_tudo(tmp_path: Path) -> None:
    """A classe de `duas-falhas-silenciosas`: menos arquivo é o que se pediu.

    Um `hashes_vivos` vazio quase sempre é "o censo não rodou". Obedecer apagaria
    o store inteiro, e o sintoma seria uma reindexação lenta que ninguém liga à
    causa.
    """
    store = ps.ParseStore(tmp_path / "indice")
    chave = ps.Chave(sha256=SHA, parser="docx:2")
    store.gravar(chave, renderizar(documento(2)))
    envelhecer(store.caminho(chave), 90)

    assert store.gc([], carencia_dias=0) == 0
    assert store.obter(chave) is not None


def test_o_gc_apaga_as_duas_rotas_do_mesmo_conteudo(tmp_path: Path) -> None:
    """O que sumiu foi o **conteúdo**, e ele pode ter entrada por rota."""
    store = ps.ParseStore(tmp_path / "indice")
    nativa = ps.Chave(sha256=OUTRO_SHA, parser="pdf:2", rota=ps.ROTA_NATIVA)
    por_ocr = ps.Chave(sha256=OUTRO_SHA, parser="ocr:1", rota=ps.ROTA_OCR, motor="ocr:1:x")
    for c in (nativa, por_ocr):
        store.gravar(c, renderizar(documento(2)))
        envelhecer(store.caminho(c), 30)

    assert store.gc([SHA], carencia_dias=14) == 2


# --- a rota, derivada do parse e não escrita à mão ----------------------------


def test_a_rota_sai_do_meta_que_o_parser_escreveu() -> None:
    assert ps.rota_de({"fonte": "ocr"}) == ps.ROTA_OCR
    assert ps.rota_de({"convertido_de": ".doc"}) == ps.ROTA_LIBREOFFICE
    assert ps.rota_de({"formato": "docx"}) == ps.ROTA_NATIVA
    assert ps.rota_de({}) == ps.ROTA_NATIVA


def test_a_rota_nativa_nao_inventa_assinatura_de_motor() -> None:
    """Motor vazio onde não há motor: `parser_version` já cobre a saída."""
    assert ps.assinatura_do_motor(ps.ROTA_NATIVA) == ""
