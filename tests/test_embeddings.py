"""A janela do encoder e a contagem de tokens.

O defeito que estes testes travam custou uma fase inteira de medição: o
tokenizador que o fastembed expõe vem com truncagem ligada, `encode()` satura na
janela do modelo, e o chunker — que pergunta exatamente "isto passa da janela?" —
ouvia "não" para qualquer texto. O orçamento de tokens nunca era aplicado e
80,7% do texto indexado nunca chegou a virar vetor. Ver
`docs/truncagem-silenciosa.md`.

Os testes que precisam do modelo real são marcados: baixam ~2 GB na primeira vez
e ficam de fora da rodada padrão.
"""

from __future__ import annotations

import pytest

from segundocerebro.index.embeddings import (
    CARACTERES_POR_TOKEN,
    MARGEM_TOKENS,
    MODELOS,
    Embedder,
)

TEXTO_LONGO = "A política de inteligência artificial da Acme Holding estabelece critérios. " * 60


def test_toda_janela_declarada_e_conferida_no_pacote_do_modelo() -> None:
    """`max_tokens` é a janela real, não o padrão herdado.

    O MiniLM declara 512 posições no `config.json` e trunca em 128 no
    `tokenizer_config.json`. Vale a truncagem. Deixar o padrão de 512 valendo
    para todo modelo foi o que produziu a truncagem silenciosa.
    """
    assert MODELOS["minilm"].max_tokens == 128
    assert MODELOS["mpnet"].max_tokens == 512
    assert MODELOS["e5-large"].max_tokens == 512


def test_orcamento_desconta_a_margem() -> None:
    for spec in MODELOS.values():
        e = Embedder(spec.id)
        assert e.orcamento_tokens == spec.max_tokens - MARGEM_TOKENS
        assert e.orcamento_tokens > 0, f"{spec.id}: margem maior que a janela"


def test_estimativa_de_emergencia_quando_nao_ha_tokenizador(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem tokenizador, estima por caractere — mas nunca satura em silêncio."""
    e = Embedder("minilm")
    monkeypatch.setattr(e, "_tokenizador_de_contagem", lambda: None)

    assert e.contar_tokens(TEXTO_LONGO) == len(TEXTO_LONGO) // CARACTERES_POR_TOKEN
    assert e.contar_tokens(TEXTO_LONGO) > e.orcamento_tokens, (
        "a estimativa tem que ser capaz de acusar texto acima do orçamento"
    )


@pytest.mark.modelo
def test_contagem_nao_satura_na_janela_do_tokenizador() -> None:
    """O teste que teria pegado o defeito.

    `contar_tokens` de um texto acima da janela tem que devolver o tamanho real,
    e não a janela. Com truncagem ligada devolvia exatamente 128 no MiniLM e
    exatamente 512 no e5 — dois modelos, o mesmo texto, e cada um "contando" a
    própria janela.
    """
    for id_modelo in ("minilm", "e5-large"):
        e = Embedder(id_modelo)
        n = e.contar_tokens(TEXTO_LONGO)

        assert n > e.spec.max_tokens, f"{id_modelo}: contagem {n} saturou na janela"
        assert n > e.orcamento_tokens


@pytest.mark.modelo
def test_modelos_da_mesma_familia_contam_o_mesmo_texto_igual() -> None:
    """MiniLM e e5 usam tokenizador XLM-R; contagens muito diferentes denunciam saturação."""
    contagens = {m: Embedder(m).contar_tokens(TEXTO_LONGO) for m in ("minilm", "e5-large")}

    menor, maior = min(contagens.values()), max(contagens.values())
    assert maior / menor < 1.2, f"contagens incompatíveis entre modelos irmãos: {contagens}"


@pytest.mark.modelo
def test_chunk_no_orcamento_cabe_de_fato_no_encoder() -> None:
    """A propriedade que interessa: o que o chunker aprova, o encoder lê inteiro."""
    e = Embedder("minilm")
    tokenizador = e._carregar().model.tokenizer

    corte = len(TEXTO_LONGO)
    while corte > 100 and e.contar_tokens(TEXTO_LONGO[:corte]) > e.orcamento_tokens:
        corte -= 100
    aprovado = TEXTO_LONGO[:corte]

    lido = len(tokenizador.encode(aprovado, add_special_tokens=False).ids)
    assert lido == e.contar_tokens(aprovado), "o encoder truncou um chunk que o chunker aprovou"
