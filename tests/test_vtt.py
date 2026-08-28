"""O parser de transcrição — `F4-T`.

Vocabulário VCE. Nenhum arquivo de acervo: os fixtures são escritos aqui, que é a
regra de `docs/colaboracao.md` §2.
"""

from __future__ import annotations

import pytest

from segundocerebro.ingest.parsers import parser_for, supported_extensions
from segundocerebro.ingest.parsers.vtt import (
    ALVO_CHARS_POR_BLOCO,
    SALTO_DE_ASSUNTO,
    parse_transcricao,
)

VTT_TEAMS = """WEBVTT

NOTE
Gravação gerada automaticamente. Não é fala e não pode ser indexada.

00:00:02.000 --> 00:00:06.500
<v Ana Ribeiro>Bom dia. Vamos tratar do contrato NN-VCE-001.</v>

00:00:06.500 --> 00:00:11.000
<v Ana Ribeiro>O prazo de entrega venceu na sexta.</v>

00:00:11.000 --> 00:00:15.000
<v Bruno Salles>Eu revisei o escopo e a VCE aceitou a prorrogação.</v>
"""

SRT_ZOOM = """1
00:00:01,000 --> 00:00:04,000
Ana Ribeiro: O relatorio trimestral da VCE saiu.

2
00:00:04,000 --> 00:00:08,000
Bruno Salles: Confirmo o numero NN-VCE-002.
"""

SBV_MEET = """0:00:01.000,0:00:04.000
Abertura da reuniao de escopo.

0:00:04.000,0:00:07.000
O contrato NN-VCE-003 entra na proxima pauta.
"""


def texto_de(doc) -> str:  # noqa: ANN001
    return "\n".join(b.text for b in doc.blocks)


class TestRegistro:
    @pytest.mark.parametrize("ext", [".vtt", ".srt", ".sbv"])
    def test_as_tres_extensoes_tem_parser(self, ext: str) -> None:
        """A lacuna que o `F4-T` fecha: `retrieve/fonte.py` já as classificava."""
        assert ext in supported_extensions()
        assert parser_for(ext) is not None


class TestVttDoTeams:
    def test_fala_e_falante_sobrevivem(self) -> None:
        doc = parse_transcricao(VTT_TEAMS.encode("utf-8"), "gravacao.vtt")
        conteudo = texto_de(doc)
        assert "NN-VCE-001" in conteudo
        assert "Ana Ribeiro:" in conteudo
        assert "Bruno Salles:" in conteudo
        assert doc.meta["formato"] == "transcrição"

    def test_o_bloco_note_nao_entra(self) -> None:
        """Metadado do WebVTT não é fala, e indexá-lo poria ruído em todo arquivo."""
        conteudo = texto_de(parse_transcricao(VTT_TEAMS.encode("utf-8"), "g.vtt"))
        assert "gerada automaticamente" not in conteudo

    def test_marcacao_inline_sai(self) -> None:
        bruto = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n"
            "<v Ana>O <i>prazo</i> do <c.color00FF00>contrato</c> &amp; o anexo</v>\n"
        )
        conteudo = texto_de(parse_transcricao(bruto.encode("utf-8"), "g.vtt"))
        assert "<i>" not in conteudo and "<c" not in conteudo and "&amp;" not in conteudo
        assert "prazo" in conteudo and "& o anexo" in conteudo

    def test_marca_de_tempo_e_a_procedencia(self) -> None:
        """Invariante 5: todo retorno carrega procedência. Aqui ela é o instante."""
        doc = parse_transcricao(VTT_TEAMS.encode("utf-8"), "g.vtt")
        assert doc.blocks[0].locator == "00:02"

    def test_hora_aparece_no_locator_quando_existe(self) -> None:
        bruto = "WEBVTT\n\n01:05:09.000 --> 01:05:12.000\nfala tardia da reuniao\n"
        doc = parse_transcricao(bruto.encode("utf-8"), "g.vtt")
        assert doc.blocks[0].locator == "1:05:09"


class TestFormaRealDoTeams:
    """O arquivo que o Teams grava de verdade tem duas coisas que os fixtures
    simplificados não têm: cabeçalhos `Kind`/`Language` depois do `WEBVTT`, e uma
    linha de **identificador de cue** antes da linha de tempo. Nenhuma das duas é
    fala, e as duas apareceriam como texto se o parser só procurasse `-->`."""

    TEAMS = """WEBVTT
Kind: captions
Language: pt-br

0d4e5a2c-9f11-4b7e-8a01-1c2d3e4f5a6b/1-0
00:00:03.120 --> 00:00:07.480
<v Ana Ribeiro>O contrato NN-VCE-001 vence na sexta.</v>

0d4e5a2c-9f11-4b7e-8a01-1c2d3e4f5a6b/2-0
00:00:07.480 --> 00:00:12.000
<v Bruno Salles>A VCE aceitou a prorrogacao.</v>
"""

    def test_cabecalho_e_identificador_de_cue_nao_viram_texto(self) -> None:
        doc = parse_transcricao(self.TEAMS.encode("utf-8"), "Reuniao.vtt")
        conteudo = texto_de(doc)
        assert "Kind:" not in conteudo
        assert "Language:" not in conteudo
        assert "0d4e5a2c" not in conteudo
        assert "NN-VCE-001" in conteudo and "prorrogacao" in conteudo

    def test_os_dois_falantes_saem_rotulados(self) -> None:
        conteudo = texto_de(parse_transcricao(self.TEAMS.encode("utf-8"), "R.vtt"))
        assert "Ana Ribeiro:" in conteudo and "Bruno Salles:" in conteudo

    def test_locator_do_primeiro_bloco_e_o_inicio_da_fala(self) -> None:
        doc = parse_transcricao(self.TEAMS.encode("utf-8"), "R.vtt")
        assert doc.blocks[0].locator == "00:03"


class TestOutrosFormatos:
    def test_srt_com_virgula_decimal_e_linha_de_indice(self) -> None:
        doc = parse_transcricao(SRT_ZOOM.encode("utf-8"), "reuniao.srt")
        conteudo = texto_de(doc)
        assert "NN-VCE-002" in conteudo
        assert "Ana Ribeiro:" in conteudo
        # A linha "1" e "2" do SRT é índice, não fala.
        assert not any(b.text.strip() in {"1", "2"} for b in doc.blocks)

    def test_sbv_usa_virgula_como_separador_de_tempo(self) -> None:
        doc = parse_transcricao(SBV_MEET.encode("utf-8"), "reuniao.sbv")
        conteudo = texto_de(doc)
        assert "NN-VCE-003" in conteudo
        assert doc.blocks[0].locator == "00:01"

    def test_falante_solto_do_zoom_e_reconhecido(self) -> None:
        doc = parse_transcricao(SRT_ZOOM.encode("utf-8"), "r.srt")
        assert "Ana Ribeiro:" in texto_de(doc)

    def test_dois_pontos_de_frase_nao_viram_falante(self) -> None:
        """"Resumo: ..." é fala, não falante — e perder `Resumo` perderia sentido."""
        bruto = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n"
            "Resumo: fechamos o contrato com a VCE. Segue o anexo.\n"
        )
        conteudo = texto_de(parse_transcricao(bruto.encode("utf-8"), "g.vtt"))
        assert conteudo.startswith("Resumo:")


class TestLegendaRolante:
    def test_cue_que_cresce_entra_uma_vez_so(self) -> None:
        """Teams reemite o cue crescendo; sem isto o documento repete o mesmo trecho."""
        bruto = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\nBom\n\n"
            "00:00:02.000 --> 00:00:03.000\nBom dia\n\n"
            "00:00:03.000 --> 00:00:04.000\nBom dia a todos\n\n"
            "00:00:04.000 --> 00:00:05.000\nBom dia a todos\n"
        )
        conteudo = texto_de(parse_transcricao(bruto.encode("utf-8"), "g.vtt"))
        assert conteudo.strip() == "Bom dia a todos"

    def test_fala_diferente_nao_e_engolida(self) -> None:
        bruto = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\nO prazo venceu\n\n"
            "00:00:02.000 --> 00:00:03.000\nA VCE aceitou\n"
        )
        conteudo = texto_de(parse_transcricao(bruto.encode("utf-8"), "g.vtt"))
        assert "O prazo venceu" in conteudo and "A VCE aceitou" in conteudo


class TestAUnidadeNaoEALegenda:
    def _transcricao_longa(self, n: int, passo: float = 3.0) -> bytes:
        linhas = ["WEBVTT", ""]
        for i in range(n):
            ini, fim = i * passo, i * passo + passo
            linhas += [
                "%02d:%02d.000 --> %02d:%02d.000"
                % (int(ini // 60), int(ini % 60), int(fim // 60), int(fim % 60)),
                f"Ponto {i} da pauta do contrato NN-VCE-{i:03d} discutido em reuniao.",
                "",
            ]
        return "\n".join(linhas).encode("utf-8")

    def test_cues_sao_fundidos_em_paragrafo(self) -> None:
        """Um bloco por cue daria milhares de trechos de ~40 caracteres."""
        doc = parse_transcricao(self._transcricao_longa(60), "longa.vtt")
        assert len(doc.blocks) < 10, f"{len(doc.blocks)} blocos para 60 cues"
        assert doc.blocks[0].text.count("\n") >= 5

    def test_bloco_persegue_o_alvo_de_tamanho(self) -> None:
        doc = parse_transcricao(self._transcricao_longa(120), "longa.vtt")
        assert len(doc.blocks) >= 2
        # Fecha ao atingir o alvo, e a fala em curso termina — daí a folga.
        assert all(len(b.text) <= ALVO_CHARS_POR_BLOCO * 1.5 for b in doc.blocks)
        assert max(len(b.text) for b in doc.blocks) > ALVO_CHARS_POR_BLOCO / 2

    def test_silencio_longo_fecha_o_paragrafo(self) -> None:
        """A pausa é a única fronteira estrutural que a transcrição dá de graça."""
        bruto = (
            "WEBVTT\n\n"
            "00:00.000 --> 00:03.000\nPrimeiro assunto da reuniao\n\n"
            f"00:{int(3 + SALTO_DE_ASSUNTO + 2):02d}.000 --> "
            f"00:{int(3 + SALTO_DE_ASSUNTO + 5):02d}.000\nOutro assunto, depois da pausa\n"
        )
        doc = parse_transcricao(bruto.encode("utf-8"), "g.vtt")
        assert len(doc.blocks) == 2
        assert doc.blocks[1].locator != doc.blocks[0].locator


class TestBordas:
    def test_arquivo_so_com_cabecalho_nao_inventa_bloco(self) -> None:
        """`vazio` é honesto; um bloco com o nome do arquivo seria invenção."""
        doc = parse_transcricao(b"WEBVTT\n\n", "vazia.vtt")
        assert doc.blocks == ()

    def test_arquivo_vazio(self) -> None:
        assert parse_transcricao(b"", "nada.vtt").blocks == ()

    def test_sem_nenhuma_marca_de_tempo_nao_quebra(self) -> None:
        doc = parse_transcricao(b"isto nao e uma transcricao\nlinha solta\n", "x.vtt")
        assert doc.blocks == ()

    def test_cp1252_e_bom_sao_decodificados(self) -> None:
        """O corpus real é Windows: a lição de codificação já está em `text.decode`."""
        bruto = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nprorrogação e revisão do anexo\n"
        for dados in (bruto.encode("cp1252"), bruto.encode("utf-8-sig")):
            conteudo = texto_de(parse_transcricao(dados, "g.vtt"))
            assert "prorrogação" in conteudo

    def test_cue_sem_texto_nao_gera_bloco(self) -> None:
        bruto = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v Ana></v>\n"
        assert parse_transcricao(bruto.encode("utf-8"), "g.vtt").blocks == ()
