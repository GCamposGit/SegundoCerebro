"""A cobertura do conjunto dourado — e a garantia de que ela não some do relatório.

O defeito que estes testes fecham não é de cálculo: é de **omissão**. Um relatório
que não diz quanto do acervo as perguntas alcançam é lido como se elas
alcançassem tudo, e foi assim que o crescimento de `Meetings/` apareceu como
queda de recall em 24/08/2026. A classe inteira é "número que qualifica a métrica
mora em documento escrito à mão e envelhece calado" — o `ROADMAP.md` guarda
18,2%, o `docs/dourado-cobertura.md` guarda 25%, e nenhum dos dois era o número
do dia em que isto foi escrito.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from .cobertura import ALVO, RAIZ, bloco, medir
from .harness import Pergunta, Resultado, avaliar, render_markdown


@dataclass(frozen=True)
class _P:
    """O mínimo que `medir` exige de uma pergunta: as fontes."""

    fontes: tuple[str, ...]


def _universo(*paths: str) -> list[str]:
    return list(paths)


class TestMedir:
    def test_pasta_de_topo_agrupa_e_a_raiz_tem_rotulo_proprio(self) -> None:
        c = medir(_universo("A/x.pdf", "A/y.pdf", "B/z.pdf", "solto.md"), [_P(("A/x.pdf",))])
        assert [(p.nome, p.documentos) for p in c.pastas] == [("A", 2), ("B", 1), (RAIZ, 1)]

    def test_alcance_conta_a_pasta_inteira_e_fontes_contam_o_documento(self) -> None:
        """Os dois números existem porque nenhum sozinho é honesto."""
        universo = _universo("A/1.pdf", "A/2.pdf", "A/3.pdf", "B/4.pdf")
        c = medir(universo, [_P(("A/1.pdf",))])

        assert c.alcance == pytest.approx(0.75), "uma pergunta cobre a pasta A inteira — teto"
        assert c.fracao_de_fontes == pytest.approx(0.25), "só um documento é resposta — piso"
        assert c.documentos_so_distrator == 1

    def test_fonte_fora_do_universo_e_contada(self) -> None:
        """Pergunta cuja fonte o índice não tem mede zero por falta de dado."""
        c = medir(_universo("A/1.pdf"), [_P(("A/1.pdf", "A/sumiu.pdf"))])
        assert c.fontes == 2
        assert c.fontes_no_universo == 1
        assert c.fontes_fora == 1

    def test_separador_do_windows_nao_cria_pasta_nova(self) -> None:
        """`A\\x.pdf` e `A/x.pdf` são a mesma pasta — o dourado normaliza para `/`."""
        c = medir(_universo("A\\x.pdf", "A/y.pdf"), [])
        assert len(c.pastas) == 1

    def test_universo_vazio_nao_divide_por_zero(self) -> None:
        c = medir([], [_P(("A/1.pdf",))])
        assert c.alcance == 0.0
        assert c.fracao_de_fontes == 0.0

    def test_crescer_o_acervo_com_o_dourado_parado_baixa_a_cobertura(self) -> None:
        """A assimetria que originou a `F4-D`, como teste.

        Documento novo em pasta sem pergunta entra na disputa como distrator e
        **nunca** como resposta: a métrica cai sem que nada tenha ficado pior.
        Se um dia a cobertura deixar de reagir a isso, o instrumento parou de
        medir o que a `F4-D` precisa que ele meça.
        """
        dourado = [_P(("A/1.pdf",))]
        antes = medir(_universo("A/1.pdf", "A/2.pdf"), dourado)
        depois = medir(_universo("A/1.pdf", "A/2.pdf", "C/3.pdf", "C/4.pdf"), dourado)

        assert antes.alcance == 1.0
        assert depois.alcance == pytest.approx(0.5)
        assert depois.documentos_so_distrator == 2


class TestBloco:
    def test_sem_medicao_o_bloco_diz_isso_em_voz_alta(self) -> None:
        """Silêncio é indistinguível de "cobre tudo". Confessar é a única saída honesta."""
        texto = "\n".join(bloco(None))
        assert "Não medida" in texto
        assert "py -m eval.cobertura" in texto, "quem lê precisa saber como medir"

    def test_cobertura_abaixo_do_alvo_sai_marcada(self) -> None:
        c = medir(_universo(*[f"A/{i}.pdf" for i in range(9)], "B/x.pdf"), [_P(("B/x.pdf",))])
        assert c.alcance < ALVO
        assert "⚠" in "\n".join(bloco(c))

    def test_cobertura_no_alvo_nao_e_marcada(self) -> None:
        c = medir(_universo("A/1.pdf", "B/2.pdf"), [_P(("A/1.pdf",))])
        assert "⚠" not in "\n".join(bloco(c))

    def test_pastas_sem_pergunta_aparecem_nomeadas(self) -> None:
        c = medir(_universo("A/1.pdf", "B/2.pdf", "B/3.pdf"), [_P(("A/1.pdf",))])
        texto = "\n".join(bloco(c))
        assert "pastas sem pergunta nenhuma" in texto
        assert "`B`" in texto

    def test_muitas_pastas_descobertas_entram_somadas(self) -> None:
        """Trinta linhas de pasta viram ruído que se aprende a pular."""
        universo = _universo("A/1.pdf", *[f"P{i}/x.pdf" for i in range(12)])
        texto = "\n".join(bloco(medir(universo, [_P(("A/1.pdf",))])))
        assert "outras 4 pastas" in texto

    def test_universo_de_disco_nao_se_anuncia_como_indice(self) -> None:
        """Existir não é ser legível: o baseline por nome alcança o que não lê."""
        c = medir(_universo("A/1.pdf"), [_P(("A/1.pdf",))], de_conteudo=False)
        assert "arquivos enumerados em disco" in "\n".join(bloco(c))


class _RecuperadorFixo:
    nome = "fixo"

    def __init__(self, paths: list[str]) -> None:
        self._paths = paths

    def search(self, consulta: str, k: int):  # noqa: ANN201, ARG002
        from .harness import Hit

        return [Hit(path=p) for p in self._paths[:k]]


def _resultado() -> Resultado:
    perguntas = [Pergunta(id="g1", tipo="exato", pergunta="?", fontes=("A/1.pdf",))]
    return avaliar(_RecuperadorFixo(["A/1.pdf"]), perguntas)


class TestRelatorio:
    """A porta da `F4-D`: nenhum relatório sai sem responder à pergunta."""

    def test_relatorio_sem_cobertura_confessa_em_vez_de_omitir(self) -> None:
        """Este é o teste que pega a classe, e não o caso.

        Quem escrever o próximo relatório e esquecer de medir não produz um
        documento silencioso: produz um que diz "não medida". A alternativa —
        seção ausente — é exatamente o que fazia a métrica ser lida como se
        valesse para o acervo inteiro.
        """
        texto = render_markdown(_resultado(), "t")
        assert "## Cobertura do conjunto dourado" in texto
        assert "Não medida" in texto

    def test_relatorio_com_cobertura_traz_os_dois_numeros(self) -> None:
        c = medir(_universo("A/1.pdf", "B/2.pdf"), [_P(("A/1.pdf",))])
        texto = render_markdown(_resultado(), "t", cobertura=c)
        assert "teto generoso" in texto
        assert "piso exato" in texto

    def test_a_secao_vem_antes_do_resto_do_relatorio(self) -> None:
        """Ressalva no rodapé não é lida. Ela qualifica a tabela `Geral`, e fica junto."""
        texto = render_markdown(_resultado(), "t", cobertura=medir(_universo("A/1.pdf"), []))
        assert texto.index("## Cobertura") < texto.index("## Por tipo de pergunta")
