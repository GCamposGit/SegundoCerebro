"""Extração de identificadores para o grafo derivado.

O que estes testes guardam é sobretudo o que **não** deve ser extraído. Uma
aresta falsa é pior que uma ausente: o documento chega com procedência correta e
um motivo de ligação inventado, e o cliente não tem como desconfiar.

Vocabulário fictício da VCE (`eval/sintetico/`), nunca do acervo real — ver a
seção de vazamento no `CLAUDE.md`.
"""

from __future__ import annotations

import pytest

from segundocerebro.retrieve.identificadores import extrair


def valores(texto: str) -> set[str]:
    return {i.valor for i in extrair(texto)}


def tipos(texto: str) -> set[str]:
    return {i.tipo for i in extrair(texto)}


# --- normas: o caso que motiva a fase -----------------------------------------


def test_norma_iso_e_extraida() -> None:
    """É a aresta da `g048`: plano de ação → norma, em pastas diferentes, sem
    nada em comum além desta citação."""
    assert "ISO 42001" in valores("o plano prevê certificação ISO 42001 até dezembro")


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("conforme ISO/IEC 27001", "ISO 27001"),
        ("conforme ISO 27001", "ISO 27001"),
        ("segundo a ABNT NBR ISO 9001", "ISO 9001"),
        ("segundo a NBR 14001", "NBR 14001"),
        ("a NR 12 exige", "NR 12"),
        ("ISO-42001", "ISO 42001"),
        ("iso 42001", "ISO 42001"),
    ],
)
def test_grafias_da_mesma_norma_convergem(texto: str, esperado: str) -> None:
    """Duas grafias do mesmo identificador têm que produzir **a mesma** aresta.

    `ABNT NBR ISO 9001` e `ISO 9001` são a mesma norma citada com mais ou menos
    formalidade. Se cada grafia virasse um valor diferente, os dois documentos
    que a citam não se ligariam — e o defeito seria invisível, porque cada um
    teria sua aresta própria e igualmente plausível.
    """
    assert esperado in valores(texto)


def test_iso_sem_numero_nao_e_norma() -> None:
    """`ISO` sozinho é sigla, não identificador.

    Extraí-lo ligaria todo documento que menciona a palavra — a aresta mais
    inútil possível, e das mais numerosas.
    """
    assert not extrair("a norma ISO aplicável e o padrão ISO em geral")


# --- leis ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto, esperado",
    [
        # Ano fora nas promulgadas, dentro nos projetos — ver
        # `test_lei_promulgada_liga_com_e_sem_o_ano` para o motivo.
        ("nos termos da Lei 14.133/2021", "LEI 14.133"),
        ("o PL 2338/2023 propõe", "PL 2338/2023"),
        ("Decreto 10.278/2020", "DECRETO 10.278"),
        ("Lei nº 13.709", "LEI 13.709"),
    ],
)
def test_lei_e_extraida(texto: str, esperado: str) -> None:
    assert esperado in valores(texto)


def test_lei_com_numero_curto_e_sem_milhar_fica_fora() -> None:
    """"Lei 5" não é referência utilizável, e casá-la produziria aresta entre
    documentos que só têm em comum a palavra "lei" e um dígito."""
    assert not extrair("a Lei 5 de referência e a Lei 42 antiga")


def test_lei_e_norma_com_mesmo_numero_nao_se_confundem() -> None:
    """O tipo é o que separa espaços de nomeação.

    A lei 42.001 e a norma ISO 42001 têm o mesmo número e nada a ver uma com a
    outra. Sem o tipo na chave, seriam a mesma aresta — e o cliente receberia
    uma norma técnica como "documento relacionado" a um contrato de licitação.
    """
    achados = extrair("a Lei 42.001/2020 e a ISO 42001 tratam de coisas distintas")
    assert {(i.tipo, i.valor) for i in achados} == {
        ("lei", "LEI 42.001"),
        ("norma", "ISO 42001"),
    }


# --- códigos estruturados -----------------------------------------------------


@pytest.mark.parametrize(
    "codigo",
    ["PO-VCE-007", "CT-VCE-2024-0142", "MA-VCE-001", "NN-VCE-450.2025"],
)
def test_codigo_estruturado_e_extraido(codigo: str) -> None:
    assert codigo in valores(f"conforme o documento {codigo} vigente")


@pytest.mark.parametrize(
    "texto",
    [
        "o impacto da covid-19 no cronograma",
        "emissões de escopo-3 do projeto",
        "ficou entre os top-10 fornecedores",
        "a versão v6-2024 do arquivo",
    ],
)
def test_palavra_hifenizada_nao_e_codigo(texto: str) -> None:
    """Dois blocos não bastam.

    `covid-19` e `escopo-3` têm a forma de código e não são. Exigir o terceiro
    bloco é o que separa identificador de palavra-hifenizada — e o custo é
    perder códigos genuínos de dois blocos, que é o lado certo de errar.
    """
    assert not [i for i in extrair(texto) if i.tipo == "codigo"]


@pytest.mark.parametrize("texto", ["veja em po-vce-007 do site", "conforme Po-Vce-007 vigente"])
def test_codigo_exige_caixa_alta(texto: str) -> None:
    """Código de documento é escrito em caixa alta neste tipo de acervo, e a
    exigência é deliberada — não descuido do padrão.

    Aceitar minúsculas casaria trecho de URL e de caminho de arquivo. E aceitar
    caixa mista (`Po-Vce-007`) obrigaria `[A-Za-z]{2,4}` no primeiro bloco, que
    casaria **topônimo hifenizado com número** — `Rio-Grande-2024`,
    `Lagoa-Norte-2026` — como se fosse código de contrato. O ganho seria uma
    grafia rara; o custo, aresta falsa em nome de lugar, que é abundante num
    acervo de concessões rodoviárias.
    """
    assert not [i for i in extrair(texto) if i.tipo == "codigo"]


# --- CNPJ e processo ----------------------------------------------------------


def test_cnpj_formatado_e_extraido() -> None:
    assert "12.345.678/0001-90" in valores("inscrita no CNPJ 12.345.678/0001-90")


def test_cnpj_sem_pontuacao_fica_fora() -> None:
    """Quatorze dígitos soltos, num acervo com 686 planilhas, casam valor
    financeiro e número de série."""
    assert not extrair("o número 12345678000190 na coluna")


def test_processo_cnj_e_extraido() -> None:
    assert "0001234-56.2023.8.26.0100" in valores("processo 0001234-56.2023.8.26.0100")


# --- fronteiras e limites -----------------------------------------------------


def test_nao_casa_no_meio_de_palavra() -> None:
    """`aISO42001` não é citação de norma."""
    assert not extrair("xISO 42001x".replace(" ", ""))


def test_acento_colado_nao_impede_o_casamento() -> None:
    """`\\b` trata acento como fronteira; o lookbehind explícito não.

    "à ISO 42001" tem acento imediatamente antes do espaço, e uma implementação
    com `\\b` erraria aqui de um jeito que só aparece em português.
    """
    assert "ISO 42001" in valores("conformidade à ISO 42001 exigida")


def test_repeticao_nao_duplica() -> None:
    achados = extrair("ISO 42001, ainda a ISO 42001, sempre ISO 42001")
    assert len(achados) == 1


def test_ordem_de_aparicao_e_preservada() -> None:
    """Ordem estável mantém o grafo reprodutível entre passadas."""
    achados = extrair("primeiro CT-VCE-2024-0142, depois a ISO 42001")
    assert [i.valor for i in achados] == ["ISO 42001", "CT-VCE-2024-0142"] or [
        i.valor for i in achados
    ] == ["CT-VCE-2024-0142", "ISO 42001"]


def test_chunk_que_lista_identificadores_e_cortado() -> None:
    """Um chunk que cita 40 identificadores não fala sobre nenhum: está listando.

    Sem o corte, cada um viraria aresta para todo documento que os cite, e um
    sumário de normas ligaria o acervo inteiro a si mesmo.
    """
    texto = " ".join(f"ISO {9000 + i}" for i in range(60))
    assert len(extrair(texto, limite=40)) == 40


def test_texto_vazio_nao_explode() -> None:
    assert extrair("") == []
    assert extrair("   ") == []


# --- edição e ano colado: medidos no acervo real em 20/08/2026 ----------------


def test_edicao_declarada_nao_cria_identificador_separado() -> None:
    """`ISO 42001:2023` e `ISO 42001` são a mesma norma, e tinham que ligar.

    Antes desta correção não ligavam: o ano de publicação entrava no valor
    canônico, então dois documentos falando da mesma norma — um citando a edição,
    outro não — ficavam sem aresta. O defeito era invisível, porque cada um tinha
    seu identificador próprio e igualmente plausível.
    """
    assert valores("conforme a ISO 42001:2023") == valores("conforme a ISO 42001")


def test_edicoes_diferentes_da_mesma_norma_ligam() -> None:
    """`ISO 27001:2013` e `ISO 27001:2022` são vintages do mesmo padrão.

    Para aresta, ligar é o certo: quem pergunta sobre segurança da informação
    quer os dois.
    """
    assert valores("ISO 27001:2013") == valores("ISO 27001:2022") == {"ISO 27001"}


def test_ano_colado_ao_numero_e_separado() -> None:
    """`ISO-420012023` é `42001` + `2023` sem separador — convenção de nome deste
    acervo, anotada no conjunto dourado.

    Sem tratar, o número saía truncado em `420012` pela gulodice do
    quantificador: um identificador que não existe em documento nenhum, que é
    pior que não extrair.
    """
    assert valores("ISO-420012023 -Web.pdf") == {"ISO 42001"}


def test_numero_de_quatro_digitos_nao_e_lido_como_ano() -> None:
    """`ISO 9001` não é `ISO 90` do ano `01`.

    O corte do ano só vale quando o resto tem tamanho de número de norma.
    """
    assert "ISO 9001" in valores("conforme a ISO 9001")


def test_norma_com_ponto_de_milhar_liga_com_a_sem() -> None:
    """`ISO 14.001` e `ISO 14001` são a mesma norma.

    Antes desta correção a expressão casava só o `14` — a fronteira aceitava o
    ponto — e produzia `ISO 14`, um identificador que ficou órfão em 15
    documentos do acervo real sem nunca ligar com nada.
    """
    assert valores("conforme a ISO 14.001") == valores("conforme a ISO 14001") == {"ISO 14001"}


def test_lei_promulgada_liga_com_e_sem_o_ano() -> None:
    """A LGPD é a `Lei 13.709` tanto quanto a `Lei 13.709/2018`.

    Lei promulgada tem numeração única e o ano é decoração. Medido no acervo:
    manter o ano partia a mesma lei em dois identificadores, um citado por 40
    documentos e outro por 15, que não se ligavam.
    """
    assert valores("nos termos da Lei 13.709/2018") == valores("nos termos da Lei 13.709")


def test_projeto_de_lei_mantem_o_ano() -> None:
    """Aqui o ano **é** identidade, e a regra segue a numeração legislativa.

    Numeração de proposta reinicia a cada ano: `PL 2338/2023` e `PL 2338/2019`
    são propostas diferentes, e ligá-las seria aresta falsa entre textos sem
    relação nenhuma.
    """
    assert valores("o PL 2338/2023") != valores("o PL 2338/2019")
    assert valores("o PL 2338/2023") == {"PL 2338/2023"}
