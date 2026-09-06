"""Tests for R6.1 autotune and per-base weight calibration."""

from __future__ import annotations

from pathlib import Path
import pytest

from segundocerebro.config import Base, Config, ErroDeConfig, Pesos, carregar
from segundocerebro.config_escrita import gravar as gravar_config
from segundocerebro.index.store import Store
from eval.autotune import (
    PRIOR_DENSO,
    PRIOR_LEXICAL,
    PRIOR_NOME,
    amostrar_perguntas,
    autotunar,
    grade_rrf,
    render_relatorio,
)
from eval.harness import Pergunta
from tests.falsos import DIM, EmbedderFalso, chunk


def test_grade_rrf_canonica() -> None:
    grade = grade_rrf()
    assert len(grade) == 37
    for d, l, n in grade:
        assert max(d, l, n) == 1.0
        assert d in (0.0, 0.25, 0.5, 1.0)
        assert l in (0.0, 0.25, 0.5, 1.0)
        assert n in (0.0, 0.25, 0.5, 1.0)


@pytest.fixture
def store_com_dados(tmp_path: Path) -> Store:
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso(dim=DIM)

    # Documentos
    docs = [
        ("Contratos/CT-VCE-2024-0142_Consultoria.txt", "Contrato CT-VCE-2024-0142 de consultoria com prazo de 12 meses."),
        ("Normas/PO-VCE-007_Politica_IA.txt", "A norma PO-VCE-007 e a ISO 42001 regem o desenvolvimento de modelos."),
        ("Relatorios/Relatorio_Anual_Financeiro.txt", "O fechamento do exercicio fiscal apresentou crescimento solido."),
    ]
    chunks_list = []
    for i, (path, texto) in enumerate(docs, start=1):
        store.registrar_documento(path=path, raiz="raiz", tamanho=len(texto), mtime=1000.0, status="ok")
        c = chunk(f"c{i}", path, 0, texto)
        chunks_list.append(c)

    store.gravar_chunks(chunks_list, emb.embed_passagens([c.text for c in chunks_list]), mtime=1.0, model_id=emb.model_id)
    store.commit()
    return store


def test_amostrar_perguntas(store_com_dados: Store) -> None:
    perguntas = amostrar_perguntas(store_com_dados, n_total=6, semente=42)
    assert len(perguntas) > 0
    fatias = {p.armadilha_fatia for p in perguntas}
    # Verifica que coletou identificadores, nomes ou conteudo
    assert fatias.intersection({"identificador", "nome", "conteudo"})
    for p in perguntas:
        assert p.pergunta
        assert len(p.fontes) == 1
        assert p.fontes[0] in store_com_dados.registrados()


def test_guarda_corpo_baixa_variacao(tmp_path: Path) -> None:
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso(dim=DIM)

    store.registrar_documento(path="Texto_Unico.txt", raiz="raiz", tamanho=100, mtime=1000.0, status="ok")
    c = chunk("c1", "Texto_Unico.txt", 0, "Texto unico do documento.")
    store.gravar_chunks([c], emb.embed_passagens([c.text]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    base = Base(id="teste", indice=tmp_path / "indice")
    perguntas = [
        Pergunta(id="p1", tipo="exato", pergunta="Texto unico", fontes=("Texto_Unico.txt",))
    ]

    res = autotunar(base, store, emb, perguntas=perguntas)
    # Como todos os ranqueadores encontram Texto_Unico no top-1, a amplitude é zero -> guarda-corpo
    assert not res.ajustado
    assert res.motivo == "guarda_corpo_baixa_variacao"
    assert res.pesos.denso == PRIOR_DENSO
    assert res.pesos.lexical == PRIOR_LEXICAL
    assert res.pesos.nome == PRIOR_NOME


def test_guarda_corpo_prior_mantido(tmp_path: Path) -> None:
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso(dim=DIM)

    # Cria docs onde o prior já é 1.0 (nome e lexical casam juntos com prior 1.0/0.25/0.5)
    # mas com outro doc para haver variação na grade (amplitude > 5%)
    docs = [
        ("tecnologia.txt", "Primeiro documento sobre tecnologia e inovacao."),
        ("financas.txt", "Segundo documento sobre direito e financas."),
        ("outro_distrator.txt", "Terceiro documento sem relacao alguma."),
    ]
    chunks_list = []
    for i, (path, texto) in enumerate(docs, start=1):
        store.registrar_documento(path=path, raiz="raiz", tamanho=len(texto), mtime=1000.0, status="ok")
        chunks_list.append(chunk(f"c{i}", path, 0, texto))
    store.gravar_chunks(chunks_list, emb.embed_passagens([c.text for c in chunks_list]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    base = Base(id="teste", indice=tmp_path / "indice")
    perguntas = [
        Pergunta(id="p1", tipo="exato", pergunta="tecnologia inovacao", fontes=("tecnologia.txt",)),
        Pergunta(id="p2", tipo="exato", pergunta="direito financas", fontes=("financas.txt",)),
    ]

    res = autotunar(base, store, emb, perguntas=perguntas)
    # Como o prior já alcança 1.0, nenhum ponto supera por margem >= 0.005 -> prior_mantido
    assert not res.ajustado
    assert res.motivo == "prior_mantido"
    assert res.pesos.denso == PRIOR_DENSO
    assert res.pesos.lexical == PRIOR_LEXICAL
    assert res.pesos.nome == PRIOR_NOME


def test_autotune_convergencia_nomes_ruins(tmp_path: Path) -> None:
    """Em acervo com nomes hostis/não-informativos (IMG_xxxx), o peso de nome deve diminuir."""
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso(dim=DIM)

    # 3 docs com nomes não informativos
    # E um documento falso homônimo que casaria por nome
    docs = [
        ("Digitalizados/IMG_1001.txt", "Contrato confidencial de engenharia estrutural."),
        ("Digitalizados/IMG_1002.txt", "Ata de reuniao ordinaria de planejamento."),
        ("Digitalizados/IMG_1003.txt", "Relatorio ambiental e fauna local."),
    ]
    chunks_list = []
    for i, (path, texto) in enumerate(docs, start=1):
        store.registrar_documento(path=path, raiz="raiz", tamanho=len(texto), mtime=1000.0, status="ok")
        chunks_list.append(chunk(f"c{i}", path, 0, texto))
    store.gravar_chunks(chunks_list, emb.embed_passagens([c.text for c in chunks_list]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    base = Base(id="hostil", indice=tmp_path / "indice")
    perguntas = [
        Pergunta(id="p1", tipo="semantica", pergunta="engenharia estrutural", fontes=("Digitalizados/IMG_1001.txt",)),
        Pergunta(id="p2", tipo="semantica", pergunta="planejamento ordinario", fontes=("Digitalizados/IMG_1002.txt",)),
        Pergunta(id="p3", tipo="semantica", pergunta="fauna ambiental", fontes=("Digitalizados/IMG_1003.txt",)),
    ]

    res = autotunar(base, store, emb, perguntas=perguntas)
    # Como as perguntas não usam IMG, o sinal de nome é neutro/ruído
    # O peso vencedor ou prior preservado não privilegia nome sobre denso/lexical
    assert res.pesos.nome <= 0.5


def test_autotune_convergencia_nomes_informativos(tmp_path: Path) -> None:
    """Em acervo onde nomes são informativos, o ranqueador de nome ajuda a desempatar ou subir MRR."""
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso(dim=DIM)

    # Documentos onde o conteúdo é genérico, mas o nome do arquivo identifica a área
    docs = [
        ("Diretrizes/Manual_Auditoria_Interna.txt", "Texto de diretriz e procedimentos operacionais padrao."),
        ("Diretrizes/Manual_Recursos_Humanos.txt", "Texto de diretriz e procedimentos operacionais padrao."),
        ("Diretrizes/Manual_Seguranca_Informacao.txt", "Texto de diretriz e procedimentos operacionais padrao."),
    ]
    chunks_list = []
    for i, (path, texto) in enumerate(docs, start=1):
        store.registrar_documento(path=path, raiz="raiz", tamanho=len(texto), mtime=1000.0, status="ok")
        chunks_list.append(chunk(f"c{i}", path, 0, texto))
    store.gravar_chunks(chunks_list, emb.embed_passagens([c.text for c in chunks_list]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    base = Base(id="informativo", indice=tmp_path / "indice")
    perguntas = [
        Pergunta(id="p1", tipo="exato", pergunta="auditoria interna", fontes=("Diretrizes/Manual_Auditoria_Interna.txt",)),
        Pergunta(id="p2", tipo="exato", pergunta="recursos humanos", fontes=("Diretrizes/Manual_Recursos_Humanos.txt",)),
        Pergunta(id="p3", tipo="exato", pergunta="seguranca informacao", fontes=("Diretrizes/Manual_Seguranca_Informacao.txt",)),
    ]

    res = autotunar(base, store, emb, perguntas=perguntas)
    # Aqui o sinal de nome é crucial para desambiguar os manuais com texto idêntico
    assert res.pesos.nome > 0.0
    assert res.ajustado or res.motivo == "prior_mantido"


def test_persistencia_e_procedencia(tmp_path: Path) -> None:
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso(dim=DIM)

    store.registrar_documento(path="doc.txt", raiz="raiz", tamanho=100, mtime=1000.0, status="ok")
    c = chunk("c1", "doc.txt", 0, "Conteudo unico para teste.")
    store.gravar_chunks([c], emb.embed_passagens([c.text]), mtime=1.0, model_id=emb.model_id)
    store.commit()

    cfg_path = tmp_path / "config.toml"
    base_inicial = Base(id="teste", indice=tmp_path / "indice")
    cfg_inicial = Config(bases=(base_inicial,))
    gravar_config(cfg_inicial, cfg_path)

    perguntas = [
        Pergunta(id="p1", tipo="exato", pergunta="Conteudo unico", fontes=("doc.txt",))
    ]

    res = autotunar(
        base_inicial,
        store,
        emb,
        perguntas=perguntas,
        gravar=True,
        caminho_config=cfg_path,
        cfg=cfg_inicial,
    )
    assert res is not None

    cfg_recarregado = carregar(cfg_path)
    base_salva = cfg_recarregado.base("teste")
    assert base_salva.pesos.denso == res.pesos.denso
    assert base_salva.pesos.lexical == res.pesos.lexical
    assert base_salva.pesos.nome == res.pesos.nome


def test_pesos_validacao_procedencia() -> None:
    # Válido
    p = Pesos(denso=1.0, lexical=0.5, nome=0.25, ajustado_em="2026-09-06T00:00:00Z", n_perguntas=60, mrr=0.75)
    p.validar("teste")

    # Invalido n_perguntas negativo
    with pytest.raises(ErroDeConfig, match="n_perguntas"):
        Pesos(n_perguntas=-1).validar("teste")

    # Invalido n_perguntas booleano
    with pytest.raises(ErroDeConfig, match="n_perguntas"):
        Pesos(n_perguntas=True).validar("teste")  # type: ignore

    # Invalido mrr negativo
    with pytest.raises(ErroDeConfig, match="mrr"):
        Pesos(mrr=-0.01).validar("teste")

    # Invalido mrr > 1
    with pytest.raises(ErroDeConfig, match="mrr"):
        Pesos(mrr=1.05).validar("teste")

    # Invalido ajustado_em nao-str
    with pytest.raises(ErroDeConfig, match="ajustado_em"):
        Pesos(ajustado_em=123).validar("teste")  # type: ignore


def test_render_relatorio_markdown() -> None:
    from eval.autotune import PontoGrade, ResultadoAutotune

    res = ResultadoAutotune(
        base_id="corporativo",
        pesos=Pesos(denso=1.0, lexical=0.5, nome=0.25, ajustado_em="2026-09-06T00:00:00Z", n_perguntas=60, mrr=0.812),
        prior=Pesos(),
        mrr_prior=0.742,
        mrr_escolhido=0.812,
        n_perguntas=60,
        motivo="melhoria_comprovada",
        grade=[
            PontoGrade(1.0, 0.5, 0.25, 0.812, 0.700),
            PontoGrade(1.0, 0.25, 0.5, 0.742, 0.650),
        ],
        ajustado=True,
    )
    md = render_relatorio(res)
    assert "# Relatório de Autotune (R6.1) — Base `corporativo`" in md
    assert "melhoria_comprovada" in md
    assert "0.812" in md
    assert "0.742" in md
    assert "Grade de Calibração" in md
