"""API do painel de ajuste.

O que se guarda aqui é sobretudo o que a tela **não** pode ser a única a impedir.
Regra que só existe no JavaScript é decoração: quem chama a API direto passa por
cima dela.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from segundocerebro.config import Busca, Pesos, carregar
from segundocerebro.painel.app import assinatura, criar_app, gerar_token

TOKEN = "token-de-teste"

CONFIG = """
[[base]]
id = "trabalho"
nome = "Acme Holding"
indice = "it"
[[base]]
id = "pessoal"
indice = "ip"
"""


@pytest.fixture
def caminho(tmp_path: Path) -> Path:
    alvo = tmp_path / "config.toml"
    alvo.write_text(CONFIG, encoding="utf-8")
    return alvo


@pytest.fixture
def medicoes_feitas() -> list:
    return []


@pytest.fixture
def cliente(caminho: Path, medicoes_feitas: list, monkeypatch: pytest.MonkeyPatch):
    from starlette.testclient import TestClient

    def medidor(base, pesos, busca):  # noqa: ANN001, ANN202
        medicoes_feitas.append((base.id, pesos, busca))
        return {"recall@1": 0.644, "mrr": 0.742, "armadilhas": 4}

    def diagnosticador(base, pesos, busca, consulta):  # noqa: ANN001, ANN202
        return {"trechos": [{"arquivo": "a.pdf", "texto": consulta, "achado_por": "denso"}]}

    monkeypatch.setattr("segundocerebro.index.retomada.instalada", lambda: False)

    return TestClient(
        criar_app(caminho, medidor=medidor, diagnosticador=diagnosticador, token=TOKEN)
    )


def cabecalho() -> dict[str, str]:
    return {"x-painel-token": TOKEN}


def ajuste(base: str = "trabalho", **pesos) -> dict:
    return {"base": base, "pesos": pesos or {"lexical": 0.5}}


# --- a porta local não é porta privada ---------------------------------------


@pytest.mark.parametrize("rota", ["/api/medir", "/api/salvar"])
def test_sem_token_nada_responde(cliente, rota: str) -> None:
    """Qualquer processo da máquina alcança uma porta aberta em 127.0.0.1."""
    assert cliente.post(rota, json={}).status_code == 403


def test_estado_sem_token_nao_responde(cliente) -> None:
    assert cliente.get("/api/estado").status_code == 403


def test_token_errado_nao_passa(cliente) -> None:
    assert cliente.get("/api/estado", headers={"x-painel-token": "outro"}).status_code == 403


# --- estado -------------------------------------------------------------------


def test_estado_lista_as_bases(cliente) -> None:
    dados = cliente.get("/api/estado", headers=cabecalho()).json()

    assert [b["id"] for b in dados["bases"]] == ["trabalho", "pessoal"]
    trabalho = dados["bases"][0]
    assert trabalho["nome"] == "Acme Holding"
    assert trabalho["indexada"] is False
    # Todo campo de `Pesos`, e não uma lista escrita à mão: a lista congelada
    # quebrou quando `C3.a` acrescentou os pesos de coluna do bm25, e quebrar é o
    # melhor caso — o pior é a tela deixar de mostrar um peso que decide ordem e
    # ninguém notar. `CAMPOS_DE_PESO` deriva da dataclass pelo mesmo motivo.
    from segundocerebro.config import Pesos

    assert set(trabalho["pesos"]) == set(Pesos.__dataclass_fields__)
    assert trabalho["pesos"]["denso"] == 1.0
    assert trabalho["pesos"]["lexical"] == 0.25
    assert trabalho["pesos"]["nome"] == 0.5


def test_sem_config_toml_o_painel_abre_e_descobre(tmp_path: Path, monkeypatch) -> None:
    """Encontrado ao subir o painel de verdade: ele devolvia 500.

    Forçava `config.toml`, que não existe até o primeiro salvamento — e recusava
    abrir por causa do arquivo que ele mesmo criaria.
    """
    from starlette.testclient import TestClient

    monkeypatch.delenv("SEGUNDOCEREBRO_BASE", raising=False)
    (tmp_path / "census.toml").write_text("[[roots]]\npath = 'C:\\\\Docs'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    c = TestClient(criar_app(tmp_path / "config.toml", medidor=lambda *a: {}, token=TOKEN))
    dados = c.get("/api/estado", headers=cabecalho()).json()

    assert [b["id"] for b in dados["bases"]] == ["padrao"]


def test_configuracao_ilegivel_diz_o_que_houve(tmp_path: Path) -> None:
    """400 com a mensagem, não 500 — a mensagem é o que ensina a consertar."""
    from starlette.testclient import TestClient

    ruim = tmp_path / "config.toml"
    ruim.write_text('[[base]]\nid = "A Maiúscula"\n', encoding="utf-8")

    c = TestClient(criar_app(ruim, medidor=lambda *a: {}, token=TOKEN))
    resposta = c.get("/api/estado", headers=cabecalho())

    assert resposta.status_code == 400
    assert "id de base inválido" in resposta.json()["erro"]


def test_estado_avisa_que_a_base_esta_indexando(cliente, caminho: Path) -> None:
    (caminho.parent / "it").mkdir()
    (caminho.parent / "it" / "indexacao.lock").write_text("123", encoding="utf-8")

    dados = cliente.get("/api/estado", headers=cabecalho()).json()
    assert dados["bases"][0]["indexando"] is True
    assert dados["bases"][1]["indexando"] is False


# --- invariante 4: nada é salvo sem medida ------------------------------------


def test_salvar_sem_medir_e_recusado(cliente) -> None:
    resposta = cliente.post("/api/salvar", json=ajuste(), headers=cabecalho())

    assert resposta.status_code == 409
    assert "medida" in resposta.json()["erro"] or "medir" in resposta.json()["erro"]


def test_medir_depois_salvar_funciona(cliente, caminho: Path) -> None:
    corpo = ajuste(lexical=0.5)

    assert cliente.post("/api/medir", json=corpo, headers=cabecalho()).status_code == 200
    assert cliente.post("/api/salvar", json=corpo, headers=cabecalho()).status_code == 200

    assert carregar(caminho, ambiente={}).base("trabalho").pesos.lexical == 0.5


def test_medir_uma_configuracao_nao_libera_outra(cliente) -> None:
    """A medição vale para o ponto medido, não para a vizinhança dele."""
    cliente.post("/api/medir", json=ajuste(lexical=0.5), headers=cabecalho())

    resposta = cliente.post("/api/salvar", json=ajuste(lexical=0.75), headers=cabecalho())
    assert resposta.status_code == 409


def test_medicao_de_uma_base_nao_libera_a_outra(cliente) -> None:
    cliente.post("/api/medir", json=ajuste("trabalho", lexical=0.5), headers=cabecalho())

    resposta = cliente.post("/api/salvar", json=ajuste("pessoal", lexical=0.5), headers=cabecalho())
    assert resposta.status_code == 409


def test_salvar_nao_mexe_nas_outras_bases(cliente, caminho: Path) -> None:
    corpo = ajuste("trabalho", lexical=0.5)
    cliente.post("/api/medir", json=corpo, headers=cabecalho())
    cliente.post("/api/salvar", json=corpo, headers=cabecalho())

    conf = carregar(caminho, ambiente={})
    assert conf.base("pessoal").pesos == Pesos()
    assert conf.base("pessoal").indice == caminho.parent / "ip"


# --- a classe cara não passa pela API de ajuste -------------------------------


@pytest.mark.parametrize("campo, valor", [("modelo", "minilm"), ("chunking", {"max_chars": 900}), ("indice", "outro")])
def test_parametro_de_reindexacao_e_recusado(cliente, campo: str, valor) -> None:
    """De 31 a 114 h de reindexação não é ajuste — é obra, e tem outro caminho."""
    corpo = {"base": "trabalho", "pesos": {"lexical": 0.5}, campo: valor}

    resposta = cliente.post("/api/medir", json=corpo, headers=cabecalho())
    assert resposta.status_code == 400
    assert "reindexar" in resposta.json()["erro"]


def test_campo_desconhecido_em_pesos_e_erro(cliente) -> None:
    """Errar o nome não pode virar 'o ajuste não fez efeito'."""
    corpo = {"base": "trabalho", "pesos": {"densoo": 1.0}}

    resposta = cliente.post("/api/medir", json=corpo, headers=cabecalho())
    assert resposta.status_code == 400
    assert "densoo" in resposta.json()["erro"]


def test_peso_invalido_e_erro(cliente) -> None:
    corpo = {"base": "trabalho", "pesos": {"denso": 0, "lexical": 0, "nome": 0}}

    resposta = cliente.post("/api/medir", json=corpo, headers=cabecalho())
    assert resposta.status_code == 400


# --- não medir contra um alvo em movimento ------------------------------------


def test_medir_com_a_base_indexando_e_recusado(cliente, caminho: Path) -> None:
    (caminho.parent / "it").mkdir()
    (caminho.parent / "it" / "indexacao.lock").write_text("123", encoding="utf-8")

    resposta = cliente.post("/api/medir", json=ajuste(), headers=cabecalho())
    assert resposta.status_code == 409
    assert "indexada" in resposta.json()["erro"]


# --- assinatura ---------------------------------------------------------------


def test_assinatura_ignora_a_ordem_e_separa_valores() -> None:
    assert assinatura(Pesos(1.0, 0.25, 0.5), Busca()) == assinatura(Pesos(1.0, 0.25, 0.5), Busca())
    assert assinatura(Pesos(1.0, 0.25, 0.5), Busca()) != assinatura(Pesos(1.0, 0.5, 0.5), Busca())
    assert json.loads(assinatura(Pesos(), Busca()))["pesos"]["denso"] == 1.0


def test_token_gerado_nao_e_adivinhavel() -> None:
    assert len(gerar_token()) >= 24 and gerar_token() != gerar_token()


def test_sessao_do_painel_grava_e_le_a_url(tmp_path: Path) -> None:
    """O atalho do Windows precisa da mesma porta e do mesmo token."""
    from segundocerebro.painel.app import caminho_da_sessao, gravar_sessao, ler_sessao

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[base]]\nid = "x"\n', encoding="utf-8")
    gravar_sessao(cfg, 18787, "abc")

    dados = ler_sessao(cfg)
    assert dados["porta"] == 18787
    assert dados["token"] == "abc"
    assert "18787" in dados["url"]
    assert caminho_da_sessao(cfg).name == ".painel.json"


def test_sessao_ilegivel_vira_ausencia(tmp_path: Path) -> None:
    from segundocerebro.painel.app import ler_sessao

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[base]]\nid = "x"\n', encoding="utf-8")
    (tmp_path / ".painel.json").write_text("{nao", encoding="utf-8")
    assert ler_sessao(cfg) is None


# --- o resumo que a tela consome ---------------------------------------------


def test_resumo_traz_o_movimento_por_pergunta() -> None:
    """A porta 5 é orçamento de regressão, e duas médias não dizem quais mudaram."""
    from segundocerebro.painel.medir import resumir

    from eval.harness import Pergunta, Resultado, ResultadoPergunta

    def item(id_: str, posicao: int | None, tipo: str = "exato", armadilha: bool = False):  # noqa: ANN202
        acertou = posicao is not None
        return ResultadoPergunta(
            pergunta=Pergunta(id=id_, tipo=tipo, pergunta="?", fontes=("a.pdf",), armadilha=armadilha),
            recuperados=["a.pdf"] if acertou else [],
            posicao_primeiro_acerto=posicao,
            recall={1: 1.0 if posicao == 1 else 0.0, 10: 1.0 if acertou else 0.0},
            mrr=1.0 / posicao if posicao else 0.0,
            ndcg=dict.fromkeys((5, 10), 1.0 if posicao == 1 else 0.0),
        )

    resultado = Resultado(
        retriever="teste",
        ks=(1, 10),
        itens=[
            item("g001", 1),
            item("g002", 4, armadilha=True),
            item("g003", None, armadilha=True),
            item("g004", 2, tipo="multihop"),
        ],
    )

    resumo = resumir(resultado)

    assert resumo["n"] == 4
    assert resumo["armadilhas"] == 1 and resumo["armadilhas_total"] == 2
    assert resumo["multihop"] == 1 and resumo["multihop_total"] == 1
    assert [p["posicao"] for p in resumo["perguntas"]] == [1, 4, None, 2]
    assert [p["no_top10"] for p in resumo["perguntas"]] == [True, True, False, True]


# --- a tela e as rotas que ela consome ---------------------------------------


def test_a_pagina_e_servida_e_nao_leva_o_token_embutido(cliente) -> None:
    """A página é pública; as rotas de dados é que exigem token.

    Embutir o token no HTML o gravaria no cache do navegador e no histórico de
    quem compartilhasse a página salva.
    """
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "Painel de Controle" in resposta.text
    assert TOKEN not in resposta.text


def test_a_pagina_nao_puxa_nada_de_fora(cliente) -> None:
    """Sem CDN: o painel roda numa máquina que pode não ter rede."""
    html = cliente.get("/").text
    for fora in ("http://", "https://", "//cdn", "<script src"):
        assert fora not in html


def test_todo_id_que_o_javascript_usa_existe_no_html(cliente) -> None:
    """`$("idxFalta")` num id que não existe falha em silêncio no navegador.

    Não há compilador entre o JavaScript e a página, e o modo de falha é o pior
    possível: metade da tela não atualiza e o console fica com um `null` que
    ninguém está olhando. Este teste é o compilador que falta.
    """
    import re

    html = cliente.get("/").text
    definidos = set(re.findall(r'id="([A-Za-z0-9_]+)"', html))
    usados = set(re.findall(r'\$\("([A-Za-z0-9_]+)"\)', html))

    assert usados, "o regex tem que estar achando as chamadas"
    assert usados <= definidos, f"ids usados e não definidos: {sorted(usados - definidos)}"


def test_perfis_trazem_pesos_e_o_custo_de_cada_um(cliente) -> None:
    """Cartão que só mostra ganho é propaganda."""
    perfis = cliente.get("/api/perfis", headers=cabecalho()).json()["perfis"]

    from segundocerebro.config import Pesos

    assert {p["id"] for p in perfis} >= {"equilibrado", "codigo", "significado", "nome"}
    for p in perfis:
        assert p["custo"] and p["para_quem"]
        # Derivado da dataclass, não escrito à mão — ver
        # `test_estado_lista_as_bases`. Os quatro perfis carregam os pesos de
        # coluna do bm25 no padrão 1/1/1: `C3.a` mede se algum deles muda, e um
        # perfil novo para acervo de nome ruim é decisão de `F4-P`, não daqui.
        assert set(p["pesos"]) == set(Pesos.__dataclass_fields__)
        assert Pesos(**p["pesos"]).colunas_fts is None


def test_perfis_exigem_token(cliente) -> None:
    assert cliente.get("/api/perfis").status_code == 403


def test_diagnostico_devolve_procedencia(cliente) -> None:
    r = cliente.post(
        "/api/diagnostico",
        json={"base": "trabalho", "consulta": "contrato"},
        headers=cabecalho(),
    )
    assert r.status_code == 200
    assert r.json()["resultado"]["trechos"][0]["achado_por"] == "denso"


def test_diagnostico_recusa_consulta_vazia(cliente) -> None:
    r = cliente.post("/api/diagnostico", json={"base": "trabalho", "consulta": "  "},
                     headers=cabecalho())
    assert r.status_code == 400


def test_diagnostico_sem_motor_responde_501(caminho: Path) -> None:
    """Sem diagnosticador injetado a rota existe e diz que não pode, em vez de estourar."""
    from starlette.testclient import TestClient

    c = TestClient(criar_app(caminho, medidor=lambda *a: {}, token=TOKEN))
    r = c.post("/api/diagnostico", json={"base": "trabalho", "consulta": "x"}, headers=cabecalho())
    assert r.status_code == 501


# --- barra de indexação: lida, nunca comandada daqui --------------------------


def test_sem_indexacao_a_barra_nao_aparece(cliente) -> None:
    dados = cliente.get("/api/indexacao", headers=cabecalho()).json()
    assert dados["bases"]["trabalho"]["progresso"] is None
    assert dados["bases"]["trabalho"]["indexando"] is False


def test_barra_le_o_que_o_indexador_publicou(cliente, caminho: Path) -> None:
    """O indexador publica, o painel lê. Fechar a tela não para nada."""
    from segundocerebro.index.estimativa import Estimador
    from segundocerebro.index.progresso import Publicador

    indice = caminho.parent / "it"
    indice.mkdir()
    e = Estimador()
    e.declarar([("a.pdf", 1_000_000), ("b.pdf", 1_000_000)])
    from segundocerebro.index.estimativa import Observacao

    e.registrar(
        Observacao(
            rel="a.pdf",
            tipo="pdf",
            mb=1_000_000 / 1_048_576,
            n_chunks=4,
            tokens=480,
            s_embed=8.0,
            s_grava=2.0,
            s_total_ativo=10.0,
        )
    )
    p = Publicador(indice=indice, estimador=e, intervalo=0.0)
    p.anotar(arquivo="b.pdf")
    p.publicar(forcar=True)

    dados = cliente.get("/api/indexacao", headers=cabecalho()).json()
    progresso = dados["bases"]["trabalho"]["progresso"]

    assert progresso["documentos"] == {"feitos": 1, "totais": 2}
    assert progresso["fracao"] == 0.5
    assert progresso["arquivo"] == "b.pdf"
    assert progresso["restante"]


def test_barra_separa_a_base_certa(cliente, caminho: Path) -> None:
    """Duas bases indexando não podem misturar barras."""
    from segundocerebro.index.estimativa import Estimador
    from segundocerebro.index.progresso import Publicador

    indice = caminho.parent / "ip"
    indice.mkdir()
    e = Estimador()
    e.declarar([("so-da-pessoal.pdf", 500)])
    Publicador(indice=indice, estimador=e, intervalo=0.0).publicar(forcar=True)

    dados = cliente.get("/api/indexacao", headers=cabecalho()).json()

    assert dados["bases"]["pessoal"]["progresso"]["documentos"]["totais"] == 1
    assert dados["bases"]["trabalho"]["progresso"] is None


def test_barra_exige_token(cliente) -> None:
    assert cliente.get("/api/indexacao").status_code == 403


def test_configuracao_ruim_nao_derruba_a_barra(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    ruim = tmp_path / "config.toml"
    ruim.write_text('[[base]]\nid = "Maiúscula"\n', encoding="utf-8")
    c = TestClient(criar_app(ruim, medidor=lambda *a: {}, token=TOKEN))

    resposta = c.get("/api/indexacao", headers=cabecalho())
    assert resposta.status_code == 400 and "erro" in resposta.json()


# --- estágio 0: criar uma base sem editar TOML --------------------------------


def corpo_de_base(tmp_path: Path, **extra) -> dict:  # noqa: ANN003
    pasta = tmp_path / "acervo"
    pasta.mkdir(exist_ok=True)
    (pasta / "nota.md").write_text("# Nota\nConteúdo qualquer.\n", encoding="utf-8")
    return {"id": "nova", "nome": "Base nova", "raizes": [str(pasta)], **extra}


def test_previa_separa_o_que_existe_do_que_e_legivel(cliente, tmp_path: Path) -> None:
    """Dois números, porque são duas perguntas diferentes.

    `arquivos` é o que está na pasta; `legiveis` é o que o indexador consegue ler
    hoje. Mostrar só o primeiro faria a estimativa parecer maior do que é, que é
    o erro do denominador da F1 aparecendo na tela de criação.
    """
    pasta = tmp_path / "acervo"
    pasta.mkdir()
    (pasta / "vale.md").write_text("conteúdo", encoding="utf-8")
    (pasta / "sem-parser.png").write_bytes(b"binario")
    (pasta / "~$temporario.docx").write_bytes(b"lixo")  # excluído por padrão

    dados = cliente.post(
        "/api/censo", json={"raizes": [str(pasta)]}, headers=cabecalho()
    ).json()

    assert dados["arquivos"] == 2, "o temporário do Office não entra"
    assert dados["legiveis"] == 1, "só o .md tem parser"


def test_previa_declara_placeholders_e_estimativa(cliente, tmp_path: Path) -> None:
    """"Isso vai demorar quanto?" respondido antes do compromisso, não depois."""
    pasta = tmp_path / "acervo"
    pasta.mkdir()
    (pasta / "a.md").write_text("x" * 5000, encoding="utf-8")

    dados = cliente.post("/api/censo", json={"raizes": [str(pasta)]}, headers=cabecalho()).json()

    assert "placeholders" in dados
    assert dados["estimativa"], "faixa em linguagem humana"
    assert dados["legiveis"] == 1
    assert dados["formatos"][0]["tem_parser"] is True


def test_previa_avisa_pasta_que_nao_existe(cliente) -> None:
    """Erro de digitação em caminho não pode virar 'zero arquivos, pode indexar'."""
    dados = cliente.post(
        "/api/censo", json={"raizes": ["Z:/nao/existe"]}, headers=cabecalho()
    ).json()
    assert dados["raizes_ausentes"] == ["Z:/nao/existe"]
    assert dados["arquivos"] == 0


def test_previa_exige_pasta(cliente) -> None:
    assert cliente.post("/api/censo", json={"raizes": []}, headers=cabecalho()).status_code == 400


def test_criar_base_escreve_no_config(cliente, caminho: Path, tmp_path: Path) -> None:
    r = cliente.post("/api/base", json=corpo_de_base(caminho.parent), headers=cabecalho())

    assert r.status_code == 200
    conf = carregar(caminho, ambiente={})
    nova = conf.base("nova", ambiente={})
    assert nova.nome == "Base nova"
    assert len(nova.raizes) == 1
    assert nova.indice != conf.base("trabalho", ambiente={}).indice, "índice próprio"


def test_criar_base_nao_indexa(cliente, caminho: Path) -> None:
    """Criar e indexar são decisões separadas — a segunda custa horas."""
    from segundocerebro.index.progresso import ler

    cliente.post("/api/base", json=corpo_de_base(caminho.parent), headers=cabecalho())

    nova = carregar(caminho, ambiente={}).base("nova", ambiente={})
    assert ler(nova.indice) is None


def test_id_repetido_e_recusado(cliente, caminho: Path) -> None:
    corpo = corpo_de_base(caminho.parent, id="trabalho")
    r = cliente.post("/api/base", json=corpo, headers=cabecalho())
    assert r.status_code == 409 and "já existe" in r.json()["erro"]


@pytest.mark.parametrize("ruim", ["Maiúscula", "com espaço", "com/barra", ""])
def test_id_invalido_e_recusado(cliente, caminho: Path, ruim: str) -> None:
    """O id vira nome de pasta e de servidor MCP — não aceita qualquer coisa."""
    corpo = corpo_de_base(caminho.parent, id=ruim)
    assert cliente.post("/api/base", json=corpo, headers=cabecalho()).status_code == 400


def test_criar_base_exige_pasta(cliente) -> None:
    r = cliente.post("/api/base", json={"id": "x", "raizes": []}, headers=cabecalho())
    assert r.status_code == 400


def test_registro_devolve_o_trecho_de_mcp_json(cliente) -> None:
    """O último degrau: conectar sem editar JSON à mão."""
    dados = cliente.get("/api/registro?base=trabalho", headers=cabecalho()).json()

    servidores = dados["json"]["mcpServers"]
    assert "segundocerebro-trabalho" in servidores
    assert servidores["segundocerebro-trabalho"]["command"] == "py"


def test_comando_exige_token(cliente) -> None:
    assert cliente.post("/api/comando", json={"acao": "pausar"}).status_code == 403


def test_comando_recusa_sem_indexacao_viva(cliente) -> None:
    r = cliente.post(
        "/api/comando", json={"base": "trabalho", "acao": "pausar"}, headers=cabecalho()
    )
    assert r.status_code == 409
    assert "não está sendo indexada" in r.json()["erro"]


def test_comando_grava_o_arquivo_ao_lado_do_indice(cliente, caminho: Path) -> None:
    from segundocerebro.index.comando import ler

    indice = caminho.parent / "it"
    indice.mkdir(exist_ok=True)
    (indice / "indexacao.lock").write_text("1", encoding="utf-8")

    r = cliente.post(
        "/api/comando", json={"base": "trabalho", "acao": "pausar"}, headers=cabecalho()
    )
    assert r.status_code == 200
    assert ler(indice) == "pausar"

    r = cliente.post(
        "/api/comando", json={"base": "trabalho", "acao": "retomar"}, headers=cabecalho()
    )
    assert r.status_code == 200
    assert ler(indice) is None


def test_indexar_recusa_base_ja_indexando(cliente, caminho: Path) -> None:
    """A trava é do indexador; o painel só não deve pedir o que vai falhar."""
    (caminho.parent / "it").mkdir(exist_ok=True)
    (caminho.parent / "it" / "indexacao.lock").write_text("1", encoding="utf-8")

    r = cliente.post("/api/indexar", json={"base": "trabalho"}, headers=cabecalho())
    assert r.status_code == 409 and "já está sendo indexada" in r.json()["erro"]


@pytest.mark.parametrize("rota", ["/api/censo", "/api/base", "/api/indexar"])
def test_estagio_zero_exige_token(cliente, rota: str) -> None:
    assert cliente.post(rota, json={}).status_code == 403


def test_registro_exige_token(cliente) -> None:
    assert cliente.get("/api/registro").status_code == 403


# --- conjunto dourado crescendo do uso real -----------------------------------


def test_pergunta_do_usuario_entra_no_dourado(cliente, caminho: Path, tmp_path: Path) -> None:
    """É o que faz "otimizar para o meu caso" ser verdade."""
    r = cliente.post(
        "/api/dourado",
        json={"base": "trabalho", "pergunta": "Onde está o contrato da Aurora?",
              "fontes": ["01. IA/contrato.pdf"]},
        headers=cabecalho(),
    )
    assert r.status_code == 200

    gravado = json.loads(Path(r.json()["arquivo"]).read_text(encoding="utf-8").strip())
    assert gravado["pergunta"] == "Onde está o contrato da Aurora?"
    assert gravado["autoria"] == "usuario", "marcado como do usuário, não rascunho meu"
    assert gravado["base"] == "trabalho", "carimba a base — conferência contra medir o acervo errado"


def test_ids_do_dourado_continuam_a_sequencia(cliente, caminho: Path) -> None:
    for i in range(2):
        cliente.post("/api/dourado",
                     json={"base": "trabalho", "pergunta": f"p{i}", "fontes": ["a.pdf"]},
                     headers=cabecalho())
    alvo = caminho.parent / "eval" / "golden" / "perguntas.jsonl"
    ids = [json.loads(l)["id"] for l in alvo.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert ids == ["g001", "g002"]


def test_dourado_exige_pergunta_e_fonte(cliente) -> None:
    """Pergunta sem fonte esperada não mede nada."""
    for corpo in ({"pergunta": "x", "fontes": []}, {"pergunta": "", "fontes": ["a.pdf"]}):
        r = cliente.post("/api/dourado", json={"base": "trabalho", **corpo}, headers=cabecalho())
        assert r.status_code == 400


# --- glossário: o dicionário do acervo de quem está usando --------------------


def test_glossario_comeca_vazio(cliente) -> None:
    """Nenhum dicionário embutido: o grupo genérico mediu zero em 18/08/2026."""
    r = cliente.get("/api/glossario?base=trabalho", headers=cabecalho())
    assert r.status_code == 200 and r.json()["termos"] == {}


def test_ensinar_sigla_grava_e_lista(cliente) -> None:
    r = cliente.post(
        "/api/glossario",
        json={"base": "trabalho", "sigla": "PO-VCE-007", "formas": ["Política de Inteligência Artificial", "política de IA"]},
        headers=cabecalho(),
    )
    assert r.status_code == 200 and r.json()["total"] == 1

    lido = cliente.get("/api/glossario?base=trabalho", headers=cabecalho()).json()
    assert lido["termos"] == {"PO-VCE-007": ["Política de Inteligência Artificial", "política de IA"]}


def test_ensinar_sigla_aponta_a_base_para_o_arquivo(cliente, caminho: Path) -> None:
    """Sem isto, o usuário ensina e nada muda — indistinguível de a expansão falhar."""
    cliente.post(
        "/api/glossario",
        json={"base": "trabalho", "sigla": "DPA", "formas": ["acordo de proteção de dados"]},
        headers=cabecalho(),
    )
    from segundocerebro.config import carregar

    base = carregar(caminho, ambiente={}).base("trabalho")
    assert base.glossario is not None and base.glossario.exists()


def test_glossario_do_painel_alimenta_a_recuperacao(cliente, caminho: Path) -> None:
    """A prova de que o laço fecha: o que a tela grava é o que a busca lê."""
    cliente.post(
        "/api/glossario",
        json={"base": "trabalho", "sigla": "CGI", "formas": ["Comitê de Governança de IA"]},
        headers=cabecalho(),
    )
    from segundocerebro.config import carregar
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    base = carregar(caminho, ambiente={}).base("trabalho")
    expandida = BuscaHibrida.glossario_de(base).expandir("o que houve na CGI")
    assert "Comitê de Governança de IA" in expandida


def test_ensinar_sigla_sem_forma_e_400(cliente) -> None:
    for corpo in ({"sigla": "DPA", "formas": []}, {"sigla": "", "formas": ["algo"]}):
        r = cliente.post("/api/glossario", json={"base": "trabalho", **corpo}, headers=cabecalho())
        assert r.status_code == 400


def test_glossario_exige_token(cliente) -> None:
    assert cliente.get("/api/glossario?base=trabalho").status_code == 403


def test_ensinar_sigla_nao_exige_medicao(cliente, medicoes_feitas: list) -> None:
    """Ao contrário de `salvar`: sigla é vocabulário do acervo, não peso de ranking."""
    r = cliente.post(
        "/api/glossario",
        json={"base": "trabalho", "sigla": "POC", "formas": ["prova de conceito"]},
        headers=cabecalho(),
    )
    assert r.status_code == 200 and not medicoes_feitas


# --- máquina: velocidade, e por isso sem a exigência de medir -----------------


def test_perfil_de_maquina_salva_sem_exigir_medicao(cliente, caminho: Path) -> None:
    """A invariante 4 exige medir antes de mudar **ranking**. Isto não é ranking.

    `[maquina]` muda a velocidade com que o índice é produzido e nunca o conteúdo
    dele, então não há métrica que se mova. Exigir medição aqui seria ritual, e
    ritual ensina o usuário a ignorar a regra onde ela importa.
    """
    r = cliente.post("/api/maquina", json={"perfil": "leve"}, headers=cabecalho())

    assert r.status_code == 200
    assert carregar(caminho, ambiente={}).maquina.perfil == "leve"


def test_perfil_normal_e_maximo_gravam(cliente, caminho: Path) -> None:
    """O painel fala leve/normal/maximo; o arquivo antigo falava completo/gpu."""
    r = cliente.post("/api/maquina", json={"perfil": "normal"}, headers=cabecalho())
    assert r.status_code == 200
    assert carregar(caminho, ambiente={}).maquina.perfil == "normal"
    r = cliente.post("/api/maquina", json={"perfil": "maximo"}, headers=cabecalho())
    assert r.status_code == 200
    assert carregar(caminho, ambiente={}).maquina.perfil == "maximo"
    assert r.json()["plano"]["cpu"]["percentual"] == 100


def test_perfil_invalido_e_recusado(cliente) -> None:
    r = cliente.post("/api/maquina", json={"perfil": "turbo"}, headers=cabecalho())
    assert r.status_code == 400


def test_estado_expoe_maquina_raizes_e_tamanho_do_dourado(cliente) -> None:
    dados = cliente.get("/api/estado", headers=cabecalho()).json()

    assert dados["maquina"]["perfil"]
    assert "plano" in dados["maquina"]
    assert "limites" in dados["maquina"]
    assert dados["limites_recomendados"]["txt"] == 2
    trabalho = dados["bases"][0]
    assert "raizes" in trabalho and "dourado" in trabalho
    assert "rerank" in trabalho["busca"], "a tela precisa saber se o rerank está ligado"


# --- re-apontar pastas: o caso de copiar a base de outra máquina ---------------


def test_reapontar_exige_confirmacao(cliente, tmp_path: Path) -> None:
    """Classe de instalação, não de ajuste: mudar pastas muda o acervo."""
    nova = tmp_path / "outro-lugar"
    nova.mkdir()

    r = cliente.post(
        "/api/raizes", json={"base": "trabalho", "raizes": [str(nova)]}, headers=cabecalho()
    )
    assert r.status_code == 409 and "confirme" in r.json()["erro"]


def test_reapontar_troca_as_pastas_e_avisa_que_nada_reindexa(cliente, caminho: Path, tmp_path: Path) -> None:
    """É justamente não reindexar que torna útil re-apontar depois de copiar."""
    nova = tmp_path / "acervo-copiado"
    nova.mkdir()

    r = cliente.post(
        "/api/raizes",
        json={"base": "trabalho", "raizes": [str(nova)], "confirmo": True},
        headers=cabecalho(),
    )

    assert r.status_code == 200
    assert "reindexado" in r.json()["aviso"]
    raizes = carregar(caminho, ambiente={}).base("trabalho", ambiente={}).raizes
    assert [str(x.path) for x in raizes] == [str(nova)]


def test_estado_traz_limites_padrao(cliente) -> None:
    dados = cliente.get("/api/estado", headers=cabecalho()).json()
    limites = dados["bases"][0]["limites"]
    assert limites["txt"] == 2.0
    assert limites["csv"] == 0.0
    assert limites["pdf"] == 0.0


def test_salvar_limites_nao_exige_medicao(cliente, caminho: Path) -> None:
    """Não é ranking: dump adiado não move recall, e ritual de medir ensinaria a ignorar a regra."""
    r = cliente.post(
        "/api/limites",
        json={"base": "trabalho", "limites": {"csv": 5, "xlsx": 40, "txt": 0}},
        headers=cabecalho(),
    )
    assert r.status_code == 200
    assert r.json()["limites"]["csv"] == 5
    gravada = carregar(caminho, ambiente={}).base("trabalho", ambiente={}).limites
    assert gravada.csv == 5 and gravada.xlsx == 40 and gravada.txt == 0
    assert gravada.pdf == 0


def test_limites_negativos_ou_tipo_desconhecido_sao_recusados(cliente) -> None:
    assert cliente.post(
        "/api/limites",
        json={"base": "trabalho", "limites": {"pdf": -1}},
        headers=cabecalho(),
    ).status_code == 400
    assert cliente.post(
        "/api/limites",
        json={"base": "trabalho", "limites": {"exe": 10}},
        headers=cabecalho(),
    ).status_code == 400


def test_reapontar_para_pasta_inexistente_e_recusado(cliente) -> None:
    """Caminho errado gravado é índice que nunca mais reconcilia."""
    r = cliente.post(
        "/api/raizes",
        json={"base": "trabalho", "raizes": ["Z:/nao/existe"], "confirmo": True},
        headers=cabecalho(),
    )
    assert r.status_code == 400 and "não encontrada" in r.json()["erro"]


# --- rerank é classe grátis, então passa pela API de ajuste --------------------


def test_rerank_pode_ser_ajustado_e_exige_medicao(cliente, caminho: Path) -> None:
    """Recarrega sem reindexar, então é ajuste — e ajuste passa pelo eval."""
    corpo = {"base": "trabalho", "pesos": {}, "busca": {"rerank": 0.25}}

    assert cliente.post("/api/salvar", json=corpo, headers=cabecalho()).status_code == 409
    assert cliente.post("/api/medir", json=corpo, headers=cabecalho()).status_code == 200
    assert cliente.post("/api/salvar", json=corpo, headers=cabecalho()).status_code == 200

    assert carregar(caminho, ambiente={}).base("trabalho", ambiente={}).busca.rerank == 0.25


def test_rerank_negativo_e_recusado(cliente) -> None:
    corpo = {"base": "trabalho", "busca": {"rerank": -1}}
    assert cliente.post("/api/medir", json=corpo, headers=cabecalho()).status_code == 400


@pytest.mark.parametrize("rota", ["/api/maquina", "/api/raizes", "/api/limites"])
def test_rotas_novas_exigem_token(cliente, rota: str) -> None:
    assert cliente.post(rota, json={}).status_code == 403


# --- invariante 6 -------------------------------------------------------------


def test_servidor_mcp_sobe_com_o_painel_ausente(tmp_path: Path, monkeypatch) -> None:
    """O painel é opcional por construção — o teste que o ROADMAP pede.

    Simula a ausência do módulo: se `mcp.server` dependesse do painel, mesmo que
    por um import de conveniência, isto quebraria.
    """
    import sys

    for nome in [m for m in sys.modules if m.startswith("segundocerebro.painel")]:
        monkeypatch.delitem(sys.modules, nome)
    monkeypatch.setattr(sys, "meta_path", [_BloqueiaPainel(), *sys.meta_path])

    from segundocerebro.mcp.server import Recursos, construir

    servidor = construir(Recursos(indice=tmp_path / "i", modelo="falso", threads=1))
    assert servidor.name == "segundocerebro"

    with pytest.raises(ImportError):
        __import__("segundocerebro.painel.app")


class _BloqueiaPainel:
    def find_module(self, nome, caminho=None):  # noqa: ANN001, ANN201 - protocolo antigo
        return None

    def find_spec(self, nome, caminho=None, alvo=None):  # noqa: ANN001, ANN201
        if nome.startswith("segundocerebro.painel"):
            raise ImportError(f"painel desinstalado: {nome}")
        return None


# --- retomada automática depois de reinício ----------------------------------
# O que estes guardam é o modo de falha, não o JSON: o `.cmd` de inicialização
# sobrevive à sessão, e o painel é a única tela do projeto que comanda algo.


def test_retomada_get_nao_mexe_no_agendador(cliente, monkeypatch) -> None:
    """Ler o estado nunca instala nada.

    É o defeito que mais assustaria: abrir a tela e ganhar uma tarefa agendada
    que ninguém pediu.
    """
    chamadas = []
    monkeypatch.setattr(
        "segundocerebro.index.retomada.agendar",
        lambda *, instalar: chamadas.append(instalar) or 0,
    )
    # `instalada` olha a pasta de inicialização real; fixá-la é o que faz este
    # teste medir a regra em vez do estado da máquina de quem roda a suíte.
    monkeypatch.setattr("segundocerebro.index.retomada.instalada", lambda: False)
    resposta = cliente.get("/api/retomada", params={"token": TOKEN})
    assert resposta.status_code == 200
    assert chamadas == []
    assert resposta.json()["instalada"] is False


def test_retomada_liga_e_desliga(cliente, monkeypatch) -> None:
    chamadas = []
    monkeypatch.setattr(
        "segundocerebro.index.retomada.agendar",
        lambda *, instalar: chamadas.append(instalar) or 0,
    )
    assert cliente.post("/api/retomada", json={"ligar": True}, params={"token": TOKEN}).status_code == 200
    assert cliente.post("/api/retomada", json={"ligar": False}, params={"token": TOKEN}).status_code == 200
    assert chamadas == [True, False]


def test_retomada_recusa_ligar_ausente_ou_nao_booleano(cliente, monkeypatch) -> None:
    """Corpo sem `ligar` explícito não vira instalação por omissão.

    `{"ligar": "sim"}` é o caso que um front mal escrito produz, e um `if
    corpo.get("ligar")` ingênuo trataria como verdadeiro.
    """
    chamadas = []
    monkeypatch.setattr(
        "segundocerebro.index.retomada.agendar",
        lambda *, instalar: chamadas.append(instalar) or 0,
    )
    for corpo in ({}, {"ligar": "sim"}, {"ligar": 1}, {"ligar": None}):
        resposta = cliente.post("/api/retomada", json=corpo, params={"token": TOKEN})
        assert resposta.status_code == 400, corpo
    assert chamadas == []


def test_retomada_relata_falha_do_agendador_com_causa(cliente, monkeypatch) -> None:
    monkeypatch.setattr("segundocerebro.index.retomada.agendar", lambda *, instalar: 2)
    resposta = cliente.post("/api/retomada", json={"ligar": True}, params={"token": TOKEN})
    assert resposta.status_code == 500
    assert "inicialização" in resposta.json()["erro"]


def test_retomada_exige_token(cliente) -> None:
    assert cliente.get("/api/retomada").status_code == 403
    assert cliente.post("/api/retomada", json={"ligar": True}).status_code == 403


def test_barra_nao_diz_faltam_quando_nao_ha_tempo() -> None:
    """No estado `cego` o texto da estimativa é a frase inteira.

    `faixa_humana` devolve "medindo esta máquina" quando não há calibragem
    local — número sem base local é mentira (spec §9). Prefixar isso com
    "faltam" produzia "faltam medindo esta máquina" na tela do usuário.
    """
    from pathlib import Path

    html = Path("src/segundocerebro/painel/index.html").read_text(encoding="utf-8")
    assert 'p.estimativa_estado === "cego"' in html, (
        "o painel voltou a prefixar o texto da estimativa sem olhar o estado"
    )
    # e o prefixo só aparece no ramo com tempo
    prefixo = html.index("`faltam ${p.restante}`")
    guarda = html.index('const semTempo = p.estimativa_estado === "cego";')
    assert guarda < prefixo, "o guarda tem de vir antes do prefixo"
