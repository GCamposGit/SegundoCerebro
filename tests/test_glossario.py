"""Expansão de consulta por glossário de siglas.

O que se guarda aqui é sobretudo o que **não** pode acontecer: a expansão trocar
a forma que o usuário escolheu, ou crescer sem teto até o `OR` do FTS5 recuperar
meio acervo.
"""

from __future__ import annotations

from segundocerebro.retrieve.glossario import MAX_TERMOS_POR_CONSULTA, Glossario


def de(termos: dict[str, object]) -> Glossario:
    return Glossario.de_dicionario(termos)


def test_vazio_devolve_a_consulta_intacta():
    """O padrão é não ter glossário, e nesse caso nada pode mudar."""
    assert Glossario.vazio().expandir("qual o contrato da Acme") == "qual o contrato da Acme"


def test_sigla_ganha_a_forma_por_extenso():
    g = de({"DPA": "acordo de proteção de dados"})
    assert g.expandir("onde está o DPA da Boreal") == (
        "onde está o DPA da Boreal acordo de proteção de dados"
    )


def test_forma_por_extenso_ganha_a_sigla():
    """O sentido que mais importa: a pergunta é por extenso e o documento usa a sigla."""
    g = de({"DPA": "acordo de proteção de dados"})
    assert g.expandir("onde está o acordo de proteção de dados") == (
        "onde está o acordo de proteção de dados DPA"
    )


def test_expandir_anexa_e_nunca_substitui():
    """A forma que o usuário escolheu é a que tem mais chance de estar no documento."""
    g = de({"CGI": "Comitê de Governança de IA"})
    saida = g.expandir("o que foi apresentado na CGI")
    assert saida.startswith("o que foi apresentado na CGI")


def test_caixa_e_acento_nao_importam():
    g = de({"DPA": "acordo de proteção de dados"})
    assert "acordo de proteção de dados" in g.expandir("cadê o dpa")
    assert "DPA" in g.expandir("cadê o acordo de protecao de dados")


def test_uma_forma_pode_ter_duas_siglas():
    """`dezembro` é `Dez` e é `Dec`, e qual está no documento é o que não se sabe.

    Guardar só a primeira perdia a que importava: a fonte da `g032` se chama
    `Apresentação IA CGI Dec-2025.pptx`, e a expansão parava em `Dez`.
    """
    g = de({"Dez": "dezembro", "Dec": ["dezembro", "December"]})
    saida = g.expandir("o que foi apresentado em dezembro de 2025")
    assert "Dez" in saida.split() and "Dec" in saida.split()


def test_uma_sigla_pode_ter_dois_significados():
    """`SST` não quer dizer a mesma coisa em duas empresas."""
    g = de({"SST": ["saúde e segurança do trabalho", "single source of truth"]})
    saida = g.expandir("relatório de SST")
    assert "saúde e segurança do trabalho" in saida and "single source of truth" in saida


def test_nao_reanexa_o_que_ja_esta_na_consulta():
    """Repetir não muda o `OR` do FTS5 e só gastaria o teto."""
    g = de({"DPA": "acordo de proteção de dados"})
    saida = g.expandir("o DPA é um acordo de proteção de dados")
    assert saida == "o DPA é um acordo de proteção de dados"


def test_sigla_ausente_da_consulta_nao_expande():
    g = de({"DPA": "acordo de proteção de dados"})
    assert g.expandir("qual o valor do contrato") == "qual o valor do contrato"


def test_teto_de_termos_acrescentados():
    """Sem teto, uma pergunta cheia de siglas viraria consulta de cinquenta termos."""
    termos = {f"S{i}": [f"forma numero {i}"] for i in range(MAX_TERMOS_POR_CONSULTA + 5)}
    g = de(termos)
    consulta = " ".join(termos)
    acrescentados = g.expandir(consulta)[len(consulta) :].split("forma")
    assert len(acrescentados) - 1 == MAX_TERMOS_POR_CONSULTA


def test_sigla_sem_forma_por_extenso_e_ignorada():
    g = de({"DPA": [], "CGI": "Comitê de Governança de IA"})
    assert "dpa" not in g.expansoes
    assert "cgi" in g.expansoes


def test_arquivo_ausente_devolve_vazio(tmp_path):
    """A recuperação funciona sem glossário; falhar por arquivo opcional seria pior."""
    g = Glossario.de_arquivo(tmp_path / "nao-existe.toml")
    assert not g


def test_com_acrescenta_preservando_o_que_havia():
    g = de({"DPA": "acordo de proteção de dados"}).com("CGI", ["Comitê de Governança de IA"])
    assert set(g.termos) == {"DPA", "CGI"}


def test_com_substitui_a_entrada_errada_em_vez_de_duplicar():
    """Corrigir uma sigla tem que tirar a errada — casando por forma normalizada."""
    g = de({"DPA": "coisa errada"}).com("dpa", ["acordo de proteção de dados"])
    assert list(g.termos) == ["dpa"]
    assert "acordo de proteção de dados" in g.expandir("onde está o DPA")
    assert "coisa errada" not in g.expandir("onde está o DPA")


def test_com_preserva_a_caixa_que_o_usuario_escreveu():
    """`PO-VCE-007` é como ele aparece no nome do arquivo; a tela tem que mostrar assim."""
    g = Glossario.vazio().com("PO-VCE-007", ["Política de Inteligência Artificial"])
    assert list(g.termos) == ["PO-VCE-007"]
    assert "Política de Inteligência Artificial" in g.expandir("o que é o po-vce-007")


def test_com_recusa_entrada_vazia():
    import pytest

    for sigla, formas in (("", ["algo"]), ("DPA", []), ("DPA", ["  "])):
        with pytest.raises(ValueError):
            Glossario.vazio().com(sigla, formas)


def test_gravar_e_reler_devolve_o_mesmo(tmp_path):
    g = de({"DPA": ["acordo de proteção de dados"], "CGI": ["Comitê de Governança de IA"]})
    alvo = tmp_path / "sub" / "glossario.toml"
    g.gravar(alvo)
    assert Glossario.de_arquivo(alvo).termos == g.termos


def test_toml_quebrado_nao_derruba_a_busca(tmp_path):
    """A tela do painel escreve aqui; erro de escrita não pode parar de recuperar."""
    caminho = tmp_path / "g.toml"
    caminho.write_text("[termos\nDPA = ", encoding="utf-8")
    assert not Glossario.de_arquivo(caminho)


def test_carrega_de_arquivo(tmp_path):
    caminho = tmp_path / "glossario.toml"
    caminho.write_text(
        '[termos]\nDPA = "acordo de proteção de dados"\nCGI = ["Comitê de Governança de IA"]\n',
        encoding="utf-8",
    )
    g = Glossario.de_arquivo(caminho)
    assert g and "acordo de proteção de dados" in g.expandir("o DPA da Acme")
