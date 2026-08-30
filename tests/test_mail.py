"""Email: `.msg` do Outlook e `.eml`/MIME.

Vocabulário fictício da VCE (`eval/sintetico/`), nunca do acervo real — ver a
seção de vazamento no `CLAUDE.md`. O `.msg` de teste é construído byte a byte por
`tests/cfb.py` e lido pelo `olefile`: `.msg` de verdade neste projeto é acervo
corporativo e não entra no repositório.

O que estes testes guardam, em ordem de importância:

1. O envelope (assunto, participantes, data, **nome do anexo**) sempre produz
   bloco. É de onde vem a resposta quando o corpo é imagem, e é o que faz o
   documento existir para o ranqueador de nome, que só vê quem tem chunk.
2. A thread é partida por mensagem, com o assunto na trilha de cada uma.
3. O que **não** é corte de citação. Um `De:` solto em português é frase comum
   ("de acordo com"), e cortar ali picaria o corpo em blocos sem sentido.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.ingest.document import ParseStatus
from segundocerebro.ingest.parsers import parser_for, parser_for_familia, supported_extensions
from segundocerebro.ingest.parsers.mail import (
    Mensagem,
    documento_de,
    limpar_corpo,
    mensagem_de_mime,
    mensagem_de_streams,
    parse_eml,
    parse_msg,
    partir_thread,
    texto_de_html,
)
from segundocerebro.ingest.reader import parse_file

# `tests/` não é pacote (não tem `__init__.py`), então o diretório do próprio
# arquivo é o que entra no `sys.path` — o import é direto, sem `tests.`.
from cfb import escrever_cfb, filetime, msg_de

# --- MIME / .eml -------------------------------------------------------------

EML_SIMPLES = (
    b"Received: from mx.vce.example\r\n"
    b"From: Ana Ribeiro <ana@vce.example>\r\n"
    b"To: Bruno Melo <bruno@vce.example>\r\n"
    b"Cc: Comite <comite@vce.example>\r\n"
    b"Subject: Encerramento da POC de leitura de faturas\r\n"
    b"Date: Mon, 10 Nov 2025 14:32:00 -0300\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Ficou decidido seguir para producao no contrato CT-VCE-2024-0142.\r\n"
)


def texto_dos_blocos(doc) -> str:  # noqa: ANN001
    return "\n".join(b.text for b in doc.blocks)


def test_eml_envelope_vira_bloco_de_cabecalho() -> None:
    doc = parse_eml(EML_SIMPLES, "encerramento.eml")

    cabecalho = doc.blocks[0]
    assert cabecalho.locator == "cabeçalho"
    assert "Ana Ribeiro" in cabecalho.text
    assert "Bruno Melo" in cabecalho.text
    assert "Comite" in cabecalho.text
    assert "10/11/2025 14:32" in cabecalho.text


def test_eml_assunto_fica_na_trilha_de_todo_bloco() -> None:
    """É a trilha que `contextual_text` prefixa antes de embeddar."""
    doc = parse_eml(EML_SIMPLES, "encerramento.eml")

    assert doc.blocks
    for bloco in doc.blocks:
        assert bloco.heading_path == ("Encerramento da POC de leitura de faturas",)


def test_eml_corpo_entra_como_mensagem() -> None:
    doc = parse_eml(EML_SIMPLES, "encerramento.eml")

    assert "CT-VCE-2024-0142" in texto_dos_blocos(doc)
    assert doc.blocks[-1].locator == "mensagem"


def test_eml_texto_plano_ganha_do_html() -> None:
    """As duas partes dizem a mesma coisa; o plano não passou por conversor."""
    bruto = (
        b"From: ana@vce.example\r\nSubject: Proposta\r\n"
        b'Content-Type: multipart/alternative; boundary="b1"\r\n\r\n'
        b"--b1\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nversao em texto\r\n"
        b"--b1\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>versao em html</p>\r\n"
        b"--b1--\r\n"
    )
    doc = parse_eml(bruto, "proposta.eml")

    assert "versao em texto" in texto_dos_blocos(doc)
    assert "versao em html" not in texto_dos_blocos(doc)


def test_eml_so_com_html_e_aproveitado() -> None:
    bruto = (
        b"From: ana@vce.example\r\nSubject: Proposta\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><style>p{color:red}</style><p>Valor de R$ 42.000</p></html>\r\n"
    )
    doc = parse_eml(bruto, "proposta.eml")

    assert "R$ 42.000" in texto_dos_blocos(doc)
    assert "color" not in texto_dos_blocos(doc), "folha de estilo não é conteúdo"


def test_eml_charset_antigo_e_decodificado() -> None:
    bruto = (
        b"From: ana@vce.example\r\nSubject: Reuniao\r\n"
        b"Content-Type: text/plain; charset=iso-8859-1\r\n\r\n"
        + "decisão de manutenção".encode("latin-1")
        + b"\r\n"
    )
    assert "decisão de manutenção" in texto_dos_blocos(parse_eml(bruto, "r.eml"))


def test_eml_anexo_entra_pelo_nome_e_nao_pelo_conteudo() -> None:
    """O nome do anexo carrega número de contrato neste acervo. O conteúdo dele é
    outro documento, e virar dois documentos no índice depende do laço do
    indexador, que é do outro setup."""
    bruto = (
        b"From: ana@vce.example\r\nSubject: Contrato\r\n"
        b'Content-Type: multipart/mixed; boundary="b1"\r\n\r\n'
        b"--b1\r\nContent-Type: text/plain\r\n\r\nsegue anexo\r\n"
        b"--b1\r\nContent-Type: application/pdf\r\n"
        b'Content-Disposition: attachment; filename="CT-VCE-2024-0142.pdf"\r\n\r\n'
        b"%PDF-1.4 bytes\r\n"
        b"--b1--\r\n"
    )
    doc = parse_eml(bruto, "contrato.eml")

    assert "CT-VCE-2024-0142.pdf" in doc.blocks[0].text
    assert "%PDF" not in texto_dos_blocos(doc)
    assert doc.meta["anexos"] == "1"


def test_eml_sem_corpo_ainda_produz_bloco() -> None:
    """Email só com envelope não é documento vazio: o assunto é a informação.

    Se virasse `vazio`, o documento não teria chunk — e sem chunk ele é invisível
    até para o ranqueador de nome, que é construído sobre `paths_com_chunks()`."""
    bruto = b"From: ana@vce.example\r\nSubject: CT-VCE-2024-0142 assinado\r\n\r\n"
    doc = parse_eml(bruto, "assinado.eml")

    assert doc.blocks
    assert doc.total_chars
    assert doc.meta["suspeita"] == "sem corpo textual"


def test_data_ilegivel_sobrevive_como_texto() -> None:
    bruto = b"From: ana@vce.example\r\nSubject: X\r\nDate: ontem a tarde\r\n\r\ncorpo\r\n"
    assert "ontem a tarde" in parse_eml(bruto, "x.eml").blocks[0].text


# --- corte de thread ---------------------------------------------------------


def test_thread_do_outlook_em_portugues_vira_um_bloco_por_mensagem() -> None:
    corpo = (
        "Confirmado, seguimos.\n"
        "\n"
        "De: Bruno Melo <bruno@vce.example>\n"
        "Enviada em: sexta-feira, 7 de novembro de 2025 09:12\n"
        "Para: Ana Ribeiro\n"
        "Assunto: RE: POC\n"
        "\n"
        "A POC atingiu 92% de acerto.\n"
    )
    fatias = partir_thread(corpo)

    assert len(fatias) == 2
    assert fatias[0].startswith("Confirmado")
    assert "92%" in fatias[1]


@pytest.mark.parametrize(
    "marca",
    [
        "-----Mensagem original-----",
        "-----Original Message-----",
        "Em 7 de novembro de 2025, Bruno Melo escreveu:",
        "On Nov 7, 2025, at 09:12, Bruno Melo wrote:",
    ],
)
def test_marcas_de_citacao_reconhecidas(marca: str) -> None:
    fatias = partir_thread(f"resposta nova\n\n{marca}\nmensagem antiga\n")

    assert len(fatias) == 2
    assert "mensagem antiga" in fatias[1]


def test_de_solto_nao_e_corte() -> None:
    """"De: acordo com o item 4" é frase, não cabeçalho. Um corte falso picaria o
    corpo em blocos sem sentido, e blocos sem sentido não somem — viram vetor."""
    corpo = "De: acordo com o item 4 do contrato, o prazo é de 30 dias.\nSegue anexo."

    assert len(partir_thread(corpo)) == 1


def test_mensagem_unica_nao_ganha_numero_no_locator() -> None:
    doc = parse_eml(EML_SIMPLES, "x.eml")

    assert [b.locator for b in doc.blocks] == ["cabeçalho", "mensagem"]


def test_thread_numera_as_mensagens_na_ordem() -> None:
    corpo = "nova\n\n-----Mensagem original-----\nmedia\n\n-----Mensagem original-----\nantiga\n"
    doc = documento_de(Mensagem(assunto="A", corpo=corpo), "x.msg", "msg")

    assert [b.locator for b in doc.blocks] == ["cabeçalho", "mensagem 1", "mensagem 2", "mensagem 3"]


# --- limpeza do corpo: o que é endereço e não texto ---------------------------


def test_url_de_rastreio_vira_host() -> None:
    """A URL inteira é o que estourava o orçamento de token do chunker: 400
    caracteres opacos ocupam a janela de 512 tokens e produzem chunk de 82
    caracteres. O host sobrevive porque o domínio do remetente é sinal fraco e real."""
    limpo = limpar_corpo("Recibo em https://cloud.mail.vce.example/e/x?t=Zm9vYmFy&u=42 obrigado")

    assert "cloud.mail.vce.example" in limpo
    assert "Zm9vYmFy" not in limpo
    assert limpo.startswith("Recibo em (link:")


def test_www_sem_esquema_tambem_e_endereco() -> None:
    assert limpar_corpo("veja www.vce.example/promo/xyz") == "veja (link: vce.example)"


def test_blob_opaco_sai_do_corpo() -> None:
    blob = "A1b2C3d4" * 10  # 80 caracteres sem espaço
    assert blob not in limpar_corpo(f"assinatura {blob} fim")


def test_palavra_longa_de_verdade_sobrevive() -> None:
    """O corte é em 60 caracteres porque palavra em português não chega lá — e
    identificador de contrato, que é o que o grafo lê, muito menos."""
    for palavra in ("anticonstitucionalissimamente", "CT-VCE-2024-0142", "ISO/IEC 42001:2023"):
        assert palavra in limpar_corpo(f"conforme {palavra} no anexo")


def test_referencia_de_imagem_embutida_sai() -> None:
    assert "cid:" not in limpar_corpo("logo [cid:image001.png@01DA5F3B] fim")


def test_limpeza_vale_no_corpo_do_msg_e_do_eml() -> None:
    """Os dois caminhos passam pela mesma limpeza — senão o `.eml` reintroduziria
    o problema pelo lado que ninguém está olhando."""
    url = "https://rastreio.vce.example/x?token=" + "Zm9vYmFyYmF6" * 8
    doc_msg = parse_msg(msg_de(assunto="Recibo", corpo=f"segue {url}"), "r.msg")
    bruto = f"From: a@vce.example\r\nSubject: Recibo\r\n\r\nsegue {url}\r\n".encode()
    doc_eml = parse_eml(bruto, "r.eml")

    for doc in (doc_msg, doc_eml):
        texto = texto_dos_blocos(doc)
        assert "rastreio.vce.example" in texto
        assert "Zm9vYmFyYmF6" not in texto


# --- HTML --------------------------------------------------------------------


def test_html_vira_texto_com_quebra_de_linha() -> None:
    assert texto_de_html("<p>uma</p><p>outra</p>") == "uma\n\noutra"


def test_html_desescapa_entidade() -> None:
    assert texto_de_html("<div>Ol&aacute; &amp; boa tarde</div>") == "Olá & boa tarde"


def test_html_descarta_script_e_estilo() -> None:
    bruto = "<head><title>t</title></head><script>var a=1</script><p>conteudo</p>"

    assert texto_de_html(bruto) == "conteudo"


# --- MAPI, sem container ------------------------------------------------------


def test_mapi_le_unicode() -> None:
    msg = mensagem_de_streams(
        {
            "__substg1.0_0037001F": "Contrato CT-VCE-2024-0142".encode("utf-16-le"),
            "__substg1.0_1000001F": "Assinado hoje.".encode("utf-16-le"),
        }
    )

    assert msg.assunto == "Contrato CT-VCE-2024-0142"
    assert msg.corpo == "Assinado hoje."


def test_mapi_cai_para_codepage_antiga() -> None:
    """`.msg` gerado por Outlook antigo traz `001E` em vez de `001F`."""
    msg = mensagem_de_streams({"__substg1.0_0037001E": "Reunião".encode("cp1252")})

    assert msg.assunto == "Reunião"


def test_mapi_corpo_html_quando_nao_ha_texto() -> None:
    msg = mensagem_de_streams({"__substg1.0_1013001F": "<p>valor de R$ 12.500</p>".encode("utf-16-le")})

    assert msg.corpo == "valor de R$ 12.500"


def test_mapi_junta_nome_e_endereco_do_remetente() -> None:
    msg = mensagem_de_streams(
        {
            "__substg1.0_0C1A001F": "Ana Ribeiro".encode("utf-16-le"),
            "__substg1.0_0C1F001F": "ana@vce.example".encode("utf-16-le"),
        }
    )

    assert msg.de == "Ana Ribeiro <ana@vce.example>"


def test_mapi_nao_repete_o_endereco_que_ja_esta_no_nome() -> None:
    msg = mensagem_de_streams(
        {
            "__substg1.0_0C1A001F": "ana@vce.example".encode("utf-16-le"),
            "__substg1.0_0C1F001F": "ana@vce.example".encode("utf-16-le"),
        }
    )

    assert msg.de == "ana@vce.example"


def test_mapi_sem_stream_nenhum_devolve_mensagem_vazia() -> None:
    """Arquivo `.msg` que não é mensagem (calendário, contato) não é erro."""
    msg = mensagem_de_streams({})

    assert msg == Mensagem()


def test_mapi_data_de_envio_sai_do_stream_de_propriedades() -> None:
    dados = msg_de(assunto="X", corpo="y", envio=filetime(2025, 11, 10, 14, 32))

    assert parse_msg(dados, "x.msg").meta["data"] == "10/11/2025 14:32"


def test_mapi_data_implausivel_e_descartada() -> None:
    """Zero e lixo dariam 1601 e 9999 — data inventada é pior que data ausente."""
    dados = msg_de(assunto="X", corpo="y", envio=1)

    assert "data" not in parse_msg(dados, "x.msg").meta


# --- container CFB de verdade ------------------------------------------------


def test_msg_completo_atravessa_o_container() -> None:
    dados = msg_de(
        assunto="RE: POC de leitura de faturas",
        de="Ana Ribeiro",
        email_de="ana@vce.example",
        para="Bruno Melo",
        corpo="Aprovado o piloto.",
        anexos=("CT-VCE-2024-0142.pdf", "ata.docx"),
        envio=filetime(2025, 11, 10, 14, 32),
    )
    doc = parse_msg(dados, "poc.msg")

    assert doc.meta["formato"] == "msg"
    assert doc.blocks[0].locator == "cabeçalho"
    assert "CT-VCE-2024-0142.pdf; ata.docx" in doc.blocks[0].text
    assert "Aprovado o piloto." in texto_dos_blocos(doc)
    assert doc.blocks[-1].heading_path == ("RE: POC de leitura de faturas",)


def test_msg_com_corpo_grande_usa_setor_normal_e_nao_mini() -> None:
    """Acima de 4096 bytes o stream sai do mini-stream. É o caminho que uma
    thread real percorre, e ler errado ali devolveria bytes do lugar errado."""
    corpo = "linha de negociacao com valor R$ 42.000\n" * 300
    dados = msg_de(assunto="Negociacao", corpo=corpo)

    doc = parse_msg(dados, "negociacao.msg")

    assert doc.total_chars > 4096
    assert "R$ 42.000" in texto_dos_blocos(doc)


def test_msg_sem_corpo_ainda_carrega_o_envelope() -> None:
    """É o caso da `g001`: a resposta está no assunto e no nome do anexo."""
    dados = msg_de(assunto="CT-VCE-2024-0142 - assinado", anexos=("CT-VCE-2024-0142.pdf",))
    doc = parse_msg(dados, "assinado.msg")

    assert "CT-VCE-2024-0142" in doc.blocks[0].text
    assert doc.meta["suspeita"] == "sem corpo textual"


def test_cfb_com_storage_de_anexo_e_lido_pelo_olefile() -> None:
    """Se o container estiver fora da especificação, o `olefile` recusa — é o que
    faz este construtor ser fixture e não mock."""
    import olefile

    dados = escrever_cfb({"__substg1.0_0037001F": "x".encode("utf-16-le"), "sub/nome": b"y"})

    assert olefile.isOleFile(dados)


# --- despacho: registro, família e o portão de leitura ------------------------


def test_registro_cobre_email() -> None:
    assert parser_for(".msg") is parse_msg
    assert parser_for(".eml") is parse_eml
    assert ".msg" in supported_extensions()


def test_familia_email_tem_parser_e_familia_ambigua_nao() -> None:
    assert parser_for_familia("email") is parse_eml
    assert parser_for_familia("ole") is None, "ole é doc, xls ou msg — adivinhar erraria calado"
    assert parser_for_familia("ooxml") is None
    assert parser_for_familia("") is None


def test_parse_file_indexa_msg(tmp_path: Path) -> None:
    alvo = tmp_path / "POC - CT-VCE-2024-0142.msg"
    alvo.write_bytes(msg_de(assunto="POC encerrada", corpo="Aprovado o piloto."))

    resultado = parse_file(str(alvo))

    assert resultado.status is ParseStatus.OK
    assert resultado.doc is not None and resultado.doc.blocks
    assert resultado.natureza is not None
    assert not resultado.natureza.extensao_mente, "`.msg` é OLE de verdade"


def test_parse_file_nao_confunde_msg_corrompido_com_formato_desconhecido(tmp_path: Path) -> None:
    alvo = tmp_path / "quebrado.msg"
    alvo.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200)

    resultado = parse_file(str(alvo))

    assert resultado.status is ParseStatus.ERROR
    assert resultado.doc is None


def test_mime_com_extensao_pdf_e_reinterpretado(tmp_path: Path) -> None:
    """O caso `g033`: a fonte tem extensão `.pdf` e conteúdo MIME."""
    alvo = tmp_path / "PROPOSTA_VALE_ESTA.pdf"
    alvo.write_bytes(EML_SIMPLES)

    resultado = parse_file(str(alvo))

    assert resultado.status is ParseStatus.OK
    assert resultado.natureza is not None and resultado.natureza.extensao_mente
    assert resultado.doc is not None
    assert "CT-VCE-2024-0142" in texto_dos_blocos(resultado.doc)


def test_parser_de_email_nao_abre_arquivo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parser recebe bytes. Se algum abrir caminho, o check de nuvem some."""
    import builtins

    dados_msg = msg_de(assunto="x", corpo="y")

    def proibido(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(f"parser tentou abrir arquivo: {args!r}")

    monkeypatch.setattr(builtins, "open", proibido)

    assert parse_msg(dados_msg, "a.msg").blocks
    assert parse_eml(EML_SIMPLES, "a.eml").blocks


def test_mensagem_de_mime_ignora_multipart_sem_conteudo() -> None:
    assert mensagem_de_mime(b"Subject: vazio\r\n\r\n").corpo == ""
