"""Tests for the store and the resumable indexer.

The properties that matter here are not about search quality:

- an interrupted run loses at most one document, and resuming re-processes
  nothing already done;
- switching embedding model re-embeds everything, because vectors from two
  models are not comparable;
- reindexing is idempotent — no duplicates, no orphans;
- FTS5 finds `PO-ACME-007`, which a naive MATCH parses as a NOT expression.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from segundocerebro.census import Config, DeclaredExclusions, RoleExclusion, RootSpec
from segundocerebro.config import ErroDeConfig
from segundocerebro.ingest.chunking import CHUNKER_VERSION, ChunkConfig
from segundocerebro.index.indexer import _deve_ativar_mcp, indexar
from segundocerebro.index.identidade_entrada import ColisaoDeCaminho
from segundocerebro.index.store import Store, consulta_fts

from tests.falsos import DIM, EmbedderFalso, chunk, config_de_raiz, corpus


# --- FTS5 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("PO-ACME-007", '"PO-ACME-007"'),
        ("ISO 42001", '"ISO" OR "42001"'),
        ("", ""),
        ("!!!", ""),
        ('aspas " no meio', '"aspas" OR "no" OR "meio"'),
    ],
)
def test_consulta_fts_aspa_cada_termo(entrada: str, esperado: str) -> None:
    """Hífen sem aspas vira operador NOT no FTS5 e a busca retorna zero."""
    assert consulta_fts(entrada) == esperado


def test_busca_lexical_encontra_codigo_com_hifen(store: Store) -> None:
    c = chunk("c1", "a.md", 0, "O PO-ACME-007 define o uso aceitável de IA.")
    store.gravar_chunks([c], [np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)], mtime=1.0)
    store.commit()

    acertos = store.buscar_lexical("PO-ACME-007", 5)

    assert [a.id for a in acertos] == ["c1"]


def test_busca_lexical_ignora_acento(store: Store) -> None:
    c = chunk("c1", "a.md", 0, "Classificação de risco e inteligência artificial")
    store.gravar_chunks([c], [np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)], mtime=1.0)
    store.commit()

    assert store.buscar_lexical("classificacao inteligencia", 5)


def test_pesos_de_coluna_do_bm25_invertem_nome_contra_conteudo(store: Store) -> None:
    """`C3.a`: o mínimo que reproduz a dupla contagem do nome do arquivo.

    Dois documentos sobre o mesmo termo. Num, ele está no **corpo**, num
    parágrafo técnico; no outro, só no **nome do arquivo**. Com o padrão 1/1/1 do
    FTS5 o segundo ganha — 1,52 contra 1,00 — e a razão não é ter um voto a mais:
    é que `caminho` é um campo **curto**, e a normalização por comprimento do
    bm25 premia o acerto no campo curto. O nome do arquivo não só vota dentro do
    bm25, ele vota **amplificado**, antes de o `RanqueadorDeNome` votar de novo
    na fusão.

    Os oito documentos de enchimento existem para o IDF sair do degenerado: com
    dois documentos os scores empatam em 1e-06 e a ordem vira desempate por
    rowid, que não mede nada.
    """
    vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
    corpo = (
        "Este documento tecnico trata do contrato de energia e descreve as condicoes "
        "de fornecimento, os prazos de vigencia, as penalidades aplicaveis e o "
        "procedimento de reajuste anual acordado entre as partes envolvidas. "
    ) * 3
    chunks = [
        chunk("conteudo", "pasta/laudo tecnico anexo iii.md", 0, corpo),
        chunk("nome", "pasta/contrato de energia.md", 0, "Sumario executivo em uma linha."),
        *(chunk(f"f{i}", f"pasta/nota {i}.md", 0, f"Assunto diverso numero {i}.") for i in range(8)),
    ]
    store.gravar_chunks(chunks, [vetor] * len(chunks), mtime=1.0)
    store.commit()

    padrao = [a.id for a in store.buscar_lexical("contrato", 5)]
    sem_caminho = [a.id for a in store.buscar_lexical("contrato", 5, (1.0, 1.0, 0.0))]
    pouco_caminho = [a.id for a in store.buscar_lexical("contrato", 5, (1.0, 1.0, 0.3))]

    assert padrao[0] == "nome"
    assert sem_caminho[0] == "conteudo"
    assert "nome" not in sem_caminho[:1]
    # 0,3 já basta para inverter: a coluna não precisa ser zerada para o corpo
    # voltar à frente, o que importa porque zerar perde o acervo de nome bom.
    assert pouco_caminho[0] == "conteudo"


def test_pesos_de_coluna_nulos_mantem_o_sql_de_sempre(store: Store) -> None:
    """`None` e (1,1,1) medem igual — e `None` é o SQL que produziu F1 a F4."""
    vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
    chunks = [
        chunk("c1", "pasta/laudo tecnico.md", 0, "Este documento trata do contrato de energia."),
        chunk("c2", "pasta/contrato de energia.md", 0, "Sumario executivo sem o termo no corpo."),
    ]
    store.gravar_chunks(chunks, [vetor, vetor], mtime=1.0)
    store.commit()

    assert [a.id for a in store.buscar_lexical("contrato", 5)] == [
        a.id for a in store.buscar_lexical("contrato", 5, (1.0, 1.0, 1.0))
    ]


def test_peso_de_coluna_da_trilha_separa_secao_de_corpo(store: Store) -> None:
    """A trilha é a terceira voz do bm25, e também é peso de consulta."""
    vetor = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
    chunks = [
        chunk("no_corpo", "a.md", 0, "O reajuste anual segue o indice contratado."),
        chunk("na_trilha", "b.md", 0, "Texto neutro sem o termo.", trilha=("Reajuste",)),
    ]
    store.gravar_chunks(chunks, [vetor, vetor], mtime=1.0)
    store.commit()

    so_trilha = [a.id for a in store.buscar_lexical("reajuste", 5, (0.1, 1.0, 0.0))]
    so_texto = [a.id for a in store.buscar_lexical("reajuste", 5, (1.0, 0.0, 0.0))]

    assert so_trilha[0] == "na_trilha"
    assert so_texto[0] == "no_corpo"


def test_fts_acompanha_remocao(store: Store) -> None:
    c = chunk("c1", "a.md", 0, "termo-unico-xyz aparece aqui")
    store.gravar_chunks([c], [np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)], mtime=1.0)
    store.commit()
    assert store.buscar_lexical("termo-unico-xyz", 5)

    store.remover_documento("a.md")
    store.commit()

    assert store.buscar_lexical("termo-unico-xyz", 5) == []


# --- busca densa ------------------------------------------------------------


def test_busca_densa_devolve_o_mais_proximo(store: Store) -> None:
    emb = EmbedderFalso()
    chunks = [chunk(f"c{i}", "a.md", i, f"texto numero {i}") for i in range(5)]
    vetores = emb.embed_passagens([c.text for c in chunks])
    store.gravar_chunks(chunks, vetores, mtime=1.0)
    store.commit()

    acertos = store.buscar_denso(vetores[2], k=3)

    assert acertos[0].id == "c2"
    assert acertos[0].score > acertos[-1].score


def test_vetores_por_id_devolve_o_que_gravou(store: Store) -> None:
    emb = EmbedderFalso()
    chunks = [chunk("c1", "a.md", 0, "conteúdo")]
    v = emb.embed_passagens(["conteúdo"])
    store.gravar_chunks(chunks, v, mtime=1.0)
    store.commit()
    lido = store.vetores_por_id()
    assert set(lido) == {"c1"}
    assert np.allclose(lido["c1"], v[0])


# --- registro e idempotência ------------------------------------------------


def test_reindexar_nao_duplica(store: Store) -> None:
    emb = EmbedderFalso()
    chunks = [chunk("c1", "a.md", 0, "conteúdo")]
    v = emb.embed_passagens(["conteúdo"])

    store.gravar_chunks(chunks, v, mtime=1.0)
    store.commit()
    store.remover_documento("a.md")
    store.gravar_chunks(chunks, v, mtime=1.0)
    store.commit()

    assert store.estatisticas()["chunks"] == 1
    assert len(store.buscar_denso(v[0], k=10)) == 1


def test_vizinhos_pega_chunks_adjacentes(store: Store) -> None:
    emb = EmbedderFalso()
    chunks = [chunk(f"c{i}", "a.md", i, f"parte {i}") for i in range(5)]
    store.gravar_chunks(chunks, emb.embed_passagens([c.text for c in chunks]), mtime=1.0)
    store.commit()

    vizinhos = store.vizinhos("c2", janela=1)

    assert [v.id for v in vizinhos] == ["c1", "c2", "c3"]


# --- indexador --------------------------------------------------------------


def test_indexar_recusa_minilm_no_cuda(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    emb = EmbedderFalso()
    emb.spec = type("Spec", (), {"id": "minilm", "dim": DIM})()
    store = Store(tmp_path / "indice", DIM)
    with pytest.raises(RuntimeError, match="NaN"):
        indexar(corpus(tmp_path / "raiz"), store, emb, parse_workers=1)
    store.fechar()


def test_pipeline_duas_gpus_grava_via_fila(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The GPU pool is a transport. Vectors that land in the store must match."""

    class FilaFalsa:
        def __init__(self, n: int, *, modelo: str, cache: Path) -> None:  # noqa: ARG002
            self._jobs: dict[int, list[str]] = {}
            self._ordem: list[int] = []
            self._n = 0
            self.fechou = False

        def submit(self, textos: list[str], batch_size: int = 32) -> int:  # noqa: ARG002
            self._n += 1
            self._jobs[self._n] = list(textos)
            self._ordem.append(self._n)
            return self._n

        def receber(self, timeout: float | None = None) -> tuple[int, list] | None:  # noqa: ARG002
            if not self._ordem:
                return None
            jid = self._ordem.pop(0)
            n = len(self._jobs.pop(jid))
            v = np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)
            return jid, [v] * n

        def fechar(self) -> None:
            self.fechou = True

    vistas: list[FilaFalsa] = []

    def fabricar(n: int, *, modelo: str, cache: Path) -> FilaFalsa:
        f = FilaFalsa(n, modelo=modelo, cache=cache)
        vistas.append(f)
        return f

    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime.listar_gpus",
        lambda: [{"name": "fake", "driver": "582.28", "compute": "8.9", "memoria": "8 GiB"}],
    )
    # The product path discovers providers. Without this stub, the CPU wheel
    # that fastembed pulled (1.29, no CUDA EP) refuses the pool as EP_AUSENTE
    # — the same class as CUDA 13 on Maxwell, a different message.
    monkeypatch.setattr(
        "segundocerebro.index.cuda_runtime._listar_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    monkeypatch.setattr("segundocerebro.index.gpu_pool.contar_gpus", lambda: 2)
    monkeypatch.setattr(
        "segundocerebro.index.indexer.dispositivos_embed", lambda **k: ["0", "1"]
    )
    monkeypatch.setattr("segundocerebro.index.indexer.EmbedFila", fabricar)

    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=2)

    assert vistas and vistas[0].fechou
    assert progresso.indexados == 2
    assert store.estatisticas()["por_status"] == {"ok": 2, "vazio": 1}
    store.fechar()


def test_pipeline_com_varios_workers_bate_o_sequencial(tmp_path: Path) -> None:
    """Parse paralelo não pode mudar o que entra no índice, só o relógio."""
    cfg = corpus(tmp_path / "raiz")
    um = Store(tmp_path / "i1", DIM)
    varios = Store(tmp_path / "i4", DIM)
    a = indexar(cfg, um, EmbedderFalso(), parse_workers=1)
    b = indexar(cfg, varios, EmbedderFalso(), parse_workers=4)
    assert (a.indexados, a.falhas, a.pulados) == (b.indexados, b.falhas, b.pulados)
    assert sorted(um.paths_indexados()) == sorted(varios.paths_indexados())
    um.fechar()
    varios.fechar()


def test_indexa_e_registra_status_por_documento(tmp_path: Path) -> None:
    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    progresso = indexar(cfg, store, emb, chunk_cfg=ChunkConfig())

    assert progresso.indexados == 2
    assert progresso.falhas == {"vazio": 1}
    estat = store.estatisticas()
    assert estat["documentos"] == 3  # o vazio também é registrado
    assert estat["por_status"] == {"ok": 2, "vazio": 1}
    store.fechar()


def test_indexacao_publica_progresso_e_encerra(tmp_path: Path) -> None:
    """A instrumentação da F3.5-D num run de verdade, não isolada.

    O painel lê este arquivo; se o indexador não o escreve, a barra não existe.
    """
    from segundocerebro.index.progresso import ler

    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)

    indexar(cfg, store, EmbedderFalso(), esforco={"perfil": "leve", "prioridade": "leve"})

    publicado = ler(tmp_path / "indice")
    assert publicado["status"] == "concluida"
    # O denominador sai do mesmo `iter_files` que o laço consome — os 3 do corpus,
    # nunca uma contagem paralela.
    assert publicado["documentos"] == {"feitos": 3, "totais": 3}
    assert publicado["fracao"] == 1.0
    assert publicado["restante_segundos"] == 0
    assert publicado["esforco"]["perfil"] == "leve", "a tela mostra o que foi aplicado"
    assert publicado["resumo"], "o resumo textual do run fica junto"
    store.fechar()


def test_progresso_pode_ser_desligado(tmp_path: Path) -> None:
    """Publicar é conveniência; indexar sem publicar tem que continuar valendo."""
    from segundocerebro.index.progresso import ler

    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)

    progresso = indexar(cfg, store, EmbedderFalso(), publicar=False)

    assert progresso.indexados == 2
    assert ler(tmp_path / "indice") is None
    store.fechar()


def test_passada_global_faz_manutencao_fts_e_ann_automaticamente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A política de ANN roda sem botão depois de uma passada completa e consistente."""
    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    conferidos: list[int] = []
    fts_otimizado: list[bool] = []

    def conferir(_store: Store, n_vetores: int):  # noqa: ANN202
        conferidos.append(n_vetores)
        return SimpleNamespace(criar=False)

    monkeypatch.setattr(Store, "garantir_ann", conferir)
    monkeypatch.setattr(Store, "otimizar_fts", lambda _store: fts_otimizado.append(True))
    indexar(cfg, store, EmbedderFalso(), publicar=False)

    assert conferidos == [store.estatisticas()["chunks"]]
    assert fts_otimizado == [True]
    store.fechar()


def test_retomada_conta_pulados_como_feitos(tmp_path: Path) -> None:
    """Na segunda passada a barra tem que sair de quase-cheia, não de zero.

    Documento pulado sai do restante sem entrar na calibragem: pular é grátis, e
    deixar isso ensinar a vazão faria a estimativa prometer um ritmo que só existe
    enquanto há trabalho já feito.
    """
    from segundocerebro.index.progresso import ler

    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    indexar(cfg, store, EmbedderFalso())

    segunda = indexar(cfg, store, EmbedderFalso())

    assert segunda.pulados == 3 and segunda.indexados == 0
    publicado = ler(tmp_path / "indice")
    assert publicado["fracao"] == 1.0
    assert publicado["status"] == "concluida"
    store.fechar()


def test_prefixo_recorta_o_denominador(tmp_path: Path) -> None:
    """O total é do escopo pedido, não do corpus inteiro.

    Denominador maior que o escopo é o erro que reportou 45% quando o real era
    91% — aqui ele apareceria como barra que trava em 33%.
    """
    from segundocerebro.index.progresso import ler

    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)

    indexar(cfg, store, EmbedderFalso(), prefixo="Política de IA")

    publicado = ler(tmp_path / "indice")
    assert publicado["documentos"]["totais"] == 1
    assert publicado["fracao"] == 1.0
    store.fechar()


def test_segunda_passada_nao_reprocessa_nada(tmp_path: Path) -> None:
    """A retomada tem que ser barata, senão a interrupção custa a passada toda."""
    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    indexar(cfg, store, emb)
    chamadas_primeira = emb.chamadas
    segunda = indexar(cfg, store, emb)

    assert chamadas_primeira > 0
    assert emb.chamadas == chamadas_primeira, "não deveria ter embeddado nada de novo"
    assert segunda.pulados == 3
    assert segunda.indexados == 0
    store.fechar()


def test_trocar_de_modelo_reindexa_tudo(tmp_path: Path) -> None:
    """Vetores de modelos diferentes não são comparáveis — misturar é bug."""
    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)

    indexar(cfg, store, EmbedderFalso(model_id="modelo-a:8"))
    outro = EmbedderFalso(model_id="modelo-b:8")
    segunda = indexar(cfg, store, outro)

    assert segunda.indexados == 2
    assert segunda.pulados == 0
    assert store.estatisticas()["modelos"] == ["modelo-b:8"]
    store.fechar()


def test_arquivo_alterado_e_reindexado(tmp_path: Path) -> None:
    raiz = tmp_path / "raiz"
    cfg = corpus(raiz)
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    indexar(cfg, store, emb)
    alvo = raiz / "contrato.md"
    alvo.write_text("# Contrato\nTexto novo e diferente, bem maior que antes.\n", encoding="utf-8")

    segunda = indexar(cfg, store, emb)

    assert segunda.indexados == 1
    assert segunda.pulados == 2
    store.fechar()


def test_limite_para_a_execucao_e_a_retomada_continua(tmp_path: Path) -> None:
    """Simula interrupção: parar no primeiro documento e retomar depois."""
    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    primeira = indexar(cfg, store, emb, limite=1)
    assert primeira.indexados == 1

    segunda = indexar(cfg, store, emb)

    assert segunda.indexados == 1  # o outro documento com texto
    assert store.estatisticas()["por_status"]["ok"] == 2
    store.fechar()


def test_passada_completa_ativa_mcp_recortes_nao() -> None:
    """Índice pela metade no MCP faz o assistente achar que a base está vazia."""
    completa = argparse.Namespace(limite=None, prefixo=None, apenas_onda=None)
    assert _deve_ativar_mcp(completa)
    assert not _deve_ativar_mcp(argparse.Namespace(limite=1000, prefixo=None, apenas_onda=None))
    assert not _deve_ativar_mcp(argparse.Namespace(limite=None, prefixo="01.", apenas_onda=None))
    assert not _deve_ativar_mcp(argparse.Namespace(limite=None, prefixo=None, apenas_onda=1))


def test_execucao_fica_registrada(tmp_path: Path) -> None:
    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)

    indexar(cfg, store, EmbedderFalso())

    linha = store.con.execute(
        "SELECT model_id, chunker, documentos, chunks, status FROM execucoes ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert linha["status"] == "concluida"
    assert linha["chunker"] == CHUNKER_VERSION
    assert linha["documentos"] == 2
    assert linha["chunks"] > 0
    store.fechar()


def test_prefixo_filtra_sem_mudar_o_caminho_gravado(tmp_path: Path) -> None:
    """Restringir a subárvore não pode encurtar o caminho registrado.

    Re-enraizar deslocava todo path em uma pasta e tornava toda fonte esperada
    do conjunto dourado impossível de casar — o eval reportaria recall zero e a
    culpa cairia no ranqueador.
    """
    raiz = tmp_path / "raiz"
    cfg = corpus(raiz)
    (raiz / "outra pasta").mkdir()
    (raiz / "outra pasta" / "fora.md").write_text("# Fora\nnão deve entrar\n", encoding="utf-8")

    store = Store(tmp_path / "indice", DIM)
    progresso = indexar(cfg, store, EmbedderFalso(), prefixo="Política de IA")

    paths = sorted(store.paths_indexados())
    assert paths == ["Política de IA/PO-ACME-007_Política_IA_v8.md"]
    assert progresso.indexados == 1
    store.fechar()


def test_busca_lexical_encontra_termo_do_nome_do_arquivo(store: Store) -> None:
    """O nome do arquivo é o sinal mais forte deste acervo e tem que ser buscável.

    O baseline da F0 tira recall@1 = 0,55 lendo só nome de arquivo; a primeira
    versão do índice não indexava o caminho e ficou em 0,26.
    """
    c = chunk("c1", "Política de IA/Pack 260323/PO-ACME-007_Política_IA_v8.docx", 0, "Texto sem o código dentro.")
    store.gravar_chunks([c], [np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)], mtime=1.0)
    store.commit()

    assert [a.id for a in store.buscar_lexical("PO-ACME-007", 5)] == ["c1"]
    assert [a.id for a in store.buscar_lexical("Pack 260323", 5)] == ["c1"]


def test_trava_impede_dois_indexadores_no_mesmo_indice(tmp_path: Path) -> None:
    """Dois indexadores no mesmo diretório duplicam vetores em silêncio.

    Medido uma vez no índice real: 13.458 vetores para 7.214 chunks. O SQLite em
    WAL tolera a concorrência, o LanceDB não, e nada levanta erro.
    """
    from segundocerebro.index.indexer import TravaDeIndice, TravaOcupada

    with TravaDeIndice(tmp_path):
        with pytest.raises(TravaOcupada):
            with TravaDeIndice(tmp_path):
                pass

    # liberada ao sair: a segunda tentativa passa
    with TravaDeIndice(tmp_path):
        pass


def test_trava_orfa_de_processo_morto_e_assumida(tmp_path: Path) -> None:
    from segundocerebro.index.indexer import TravaDeIndice

    (tmp_path / "indexacao.lock").write_text("999999999", encoding="utf-8")

    with TravaDeIndice(tmp_path):  # não deve levantar
        pass


def test_verificar_consistencia_detecta_vetor_duplicado(store: Store) -> None:
    emb = EmbedderFalso()
    c = chunk("c1", "a.md", 0, "conteúdo")
    v = emb.embed_passagens(["conteúdo"])
    store.gravar_chunks([c], v, mtime=1.0, model_id="falso:8")
    store.commit()
    assert store.verificar_consistencia()["diferenca"] == 0

    store.gravar_chunks([c], v, mtime=1.0, model_id="falso:8")  # sem remover antes
    store.commit()

    assert store.verificar_consistencia()["diferenca"] == 1


def test_indice_de_outro_modelo_e_recusado_na_abertura(tmp_path: Path) -> None:
    """Falha ao abrir, não no meio da primeira busca.

    Sem a guarda, o erro vem de dentro do LanceDB — depois de carregar 2 GB de
    encoder e rodar metade do eval — como `query dim(384) doesn't match column
    dim(1024)`, que não diz o que fazer. Aconteceu de verdade em 13/08/2026,
    quando o `MODELO_PADRAO` mudou e um default esquecido no eval não mudou junto.
    """
    from segundocerebro.index.store import DimensaoIncompativel

    store = Store(tmp_path / "indice", dim=8)
    store.tabela  # cria a tabela com 8 dimensões
    store.fechar()

    outro = Store(tmp_path / "indice", dim=16)
    try:
        with pytest.raises(DimensaoIncompativel, match="8 dimensões"):
            outro.tabela
    finally:
        outro.fechar()


def test_mesma_dimensao_abre_normalmente(tmp_path: Path) -> None:
    store = Store(tmp_path / "indice", dim=8)
    store.tabela
    store.fechar()

    de_novo = Store(tmp_path / "indice", dim=8)
    try:
        assert de_novo.tabela is not None
    finally:
        de_novo.fechar()


def test_documento_travado_e_repescado_na_proxima_passada(tmp_path: Path) -> None:
    """A promessa do ROADMAP, que não estava implementada.

    `_precisa_indexar` compara tamanho, mtime, modelo e chunker — e um arquivo
    que estava aberto no Word passa nos quatro, então era pulado para sempre.
    Encontrado em 13/08/2026 com um `.docx` travado durante a reconstrução.
    """
    from segundocerebro.index.indexer import CHUNKER_VERSION, _precisa_indexar

    class Estado:
        def __init__(self, status: str) -> None:
            self.status = status
            self.model_id = "m:8"
            self.chunker = CHUNKER_VERSION
            self.parser = "1"
            self.tamanho = 10
            self.mtime = 1.0
            self.sha256 = "abc"
            self.n_chunks = 0

    class Arquivo:
        rel = "doc.pdf"  # `Q15.a`: a regra pergunta se este caminho espera OCR
        size = 10
        mtime = 1.0

    for status in ("travado", "placeholder", "erro", "sem_parser"):
        assert _precisa_indexar(Estado(status), Arquivo(), "m:8", "1"), f"{status} tem que ser repescado"


def test_documento_ok_ou_vazio_nao_e_reprocessado(tmp_path: Path) -> None:
    """`vazio` é determinístico: repescar custaria reprocessar PDF de 61 páginas por passada."""
    from segundocerebro.index.indexer import CHUNKER_VERSION, _precisa_indexar

    class Estado:
        def __init__(self, status: str) -> None:
            self.status = status
            self.model_id = "m:8"
            self.chunker = CHUNKER_VERSION
            self.parser = "1"
            self.tamanho = 10
            self.mtime = 1.0
            self.sha256 = "abc"
            self.n_chunks = 3

    class Arquivo:
        rel = "doc.pdf"  # `Q15.a`: a regra pergunta se este caminho espera OCR
        size = 10
        mtime = 1.0

    assert not _precisa_indexar(Estado("ok"), Arquivo(), "m:8", "1")
    assert not _precisa_indexar(Estado("vazio"), Arquivo(), "m:8", "1")


# --- versão de parser -------------------------------------------------------


def test_parser_corrigido_repesca_e_nao_repesca_de_novo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O defeito que custou um script avulso em 21/08/2026, agora fechado.

    Três asserções, e as três importam:

    1. Subir a versão do parser **repesca** o documento, mesmo com arquivo
       intocado — tamanho, mtime, modelo e chunker todos batem.
    2. Os chunks são **regenerados**, não reaproveitados: o atalho de "sha256
       idêntico com mtime novo" existe e reusaria `n_chunks` do estado antigo.
    3. A passada seguinte **pula**. Sem gravar a versão nova, o documento
       repescaria a cada passada para sempre, produzindo o mesmo texto.
    """
    from segundocerebro.ingest import parsers

    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    indexar(cfg, store, emb)
    assert store.estado_documento("contrato.md").parser == parsers.VERSAO_INICIAL

    monkeypatch.setitem(parsers._VERSOES, ".md", "7")
    depois = indexar(cfg, store, emb)

    assert depois.indexados == 2, "os dois .md com conteúdo têm que ser repescados"
    assert depois.pulados == 0
    assert depois.inalterados == 0, "o atalho de sha256 anularia a repesca"
    assert store.estado_documento("contrato.md").parser == "7"

    terceira = indexar(cfg, store, emb)
    assert terceira.indexados == 0, "repescaria para sempre sem gravar a versão"
    assert terceira.pulados == 3
    store.fechar()


def test_indice_antigo_e_estampado_e_nao_reindexado(tmp_path: Path) -> None:
    """A migração precisa afirmar algo, porque o default aqui não é neutro.

    `parser = ''` não bate com nenhuma versão declarada, então abrir um índice
    de 1.608 documentos com a coluna vazia mandaria 39 h de parede reproduzir o
    texto que já estava lá. Este teste é a única prova de que isso não acontece —
    e o custo do erro é grande demais para ficar sem uma.
    """
    from segundocerebro.ingest.parsers import VERSAO_INICIAL

    cfg = corpus(tmp_path / "raiz")
    store = Store(tmp_path / "indice", DIM)
    indexar(cfg, store, EmbedderFalso())
    store.con.execute("ALTER TABLE documentos DROP COLUMN parser")
    store.fechar()

    de_novo = Store(tmp_path / "indice", DIM)
    versoes = {r[0] for r in de_novo.con.execute("SELECT DISTINCT parser FROM documentos")}
    assert versoes == {VERSAO_INICIAL}

    passada = indexar(cfg, de_novo, EmbedderFalso())
    assert passada.indexados == 0, "índice antigo não pode reindexar por causa da coluna nova"
    assert passada.pulados == 3
    de_novo.fechar()


def test_versao_de_parser_vem_do_registro_de_extensoes() -> None:
    """A versão mora junto do parser, não numa tabela paralela que envelhece à parte."""
    from segundocerebro.ingest.parsers import VERSAO_INICIAL, parser_version_for

    assert parser_version_for(".msg") == parser_version_for(".eml") == "2"
    assert parser_version_for(".MSG") == "2", "extensão em maiúscula é a mesma extensão"
    assert parser_version_for(".csv") == "2"
    assert parser_version_for(".xlsx") == "2"
    assert parser_version_for(".doc") == parser_version_for(".ppt") == parser_version_for(".xls") == "2"
    assert parser_version_for(".pdf") == VERSAO_INICIAL
    assert parser_version_for(".xyz") == VERSAO_INICIAL, "sem parser é repescado por status"


def test_flag_de_texto_nao_adia_csv() -> None:
    """C7.d: `--pular-texto-acima-de` is the .txt gate, not a second CSV hide."""
    from segundocerebro.config import LimitesDeIndexacao
    from segundocerebro.index.indexer import _limites_efetivos

    mapa = _limites_efetivos(LimitesDeIndexacao(txt=2, csv=0), 1.0)
    assert mapa[".txt"] == 1.0
    assert ".csv" not in mapa

    com_teto_de_base = _limites_efetivos(LimitesDeIndexacao(txt=2, csv=5), 1.0)
    assert com_teto_de_base[".csv"] == 5.0


# --- recorte por extensão ---------------------------------------------------


def test_so_extensao_recorta_o_escopo(tmp_path: Path) -> None:
    """Partir a passada por custo: em Meetings/ é 13 min contra 5–11 h."""
    cfg = corpus(tmp_path / "raiz")
    (tmp_path / "raiz" / "planilha.csv").write_text("a,b" + chr(10) + "1,2" + chr(10), encoding="utf-8")
    store = Store(tmp_path / "indice", DIM)

    progresso = indexar(cfg, store, EmbedderFalso(), so_extensao=frozenset({".csv"}))

    assert progresso.documentos == 1
    assert {p for p, in store.con.execute("SELECT path FROM documentos")} == {"planilha.csv"}
    store.fechar()


def test_so_extensao_nao_reconcilia(tmp_path: Path) -> None:
    """O recorte por extensão é o caso em que reconciliar apaga o acervo.

    Todo documento de outra extensão fica fora de `vistos`, e reconciliar leria
    isso como "sumiu do disco". A passada de `.txt` de Meetings/ apagaria os
    1.514 documentos que já estavam indexados.
    """
    cfg = corpus(tmp_path / "raiz")
    (tmp_path / "raiz" / "planilha.csv").write_text("a,b" + chr(10) + "1,2" + chr(10), encoding="utf-8")
    store = Store(tmp_path / "indice", DIM)

    indexar(cfg, store, EmbedderFalso())
    antes = {p for p, in store.con.execute("SELECT path FROM documentos")}
    progresso = indexar(cfg, store, EmbedderFalso(), so_extensao=frozenset({".csv"}))

    assert progresso.reconciliacao.removidos == []
    assert {p for p, in store.con.execute("SELECT path FROM documentos")} == antes
    store.fechar()


def test_extensoes_da_cli_aceitam_com_e_sem_ponto() -> None:
    from segundocerebro.index.indexer import _extensoes

    assert _extensoes("txt,.PDF") == frozenset({".txt", ".pdf"})
    assert _extensoes("") is None
    assert _extensoes(None) is None


def test_txt_com_muitos_trechos_e_adiado_sem_embeddar(tmp_path: Path) -> None:
    """Rede de segurança: dump que passa do teto de bytes ainda pode explodir em trechos."""
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (raiz / "dump.txt").write_text(("palavra " * 40 + "\n") * 80, encoding="utf-8")
    cfg = config_de_raiz(raiz, "r")
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    progresso = indexar(
        cfg,
        store,
        emb,
        chunk_cfg=ChunkConfig(max_chars=60, min_chars=20, overlap_chars=8),
        limite_chunks=5,
        publicar=False,
    )

    estado = store.estado_documento("dump.txt")
    assert estado is not None and estado.status == "adiado"
    assert progresso.indexados == 0
    assert emb.chamadas == 0
    assert "adiado" in progresso.falhas
    store.fechar()


def test_txt_curto_passa_pelo_teto_de_trechos(tmp_path: Path) -> None:
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (raiz / "nota.txt").write_text("nota curta o bastante para um trecho só.\n", encoding="utf-8")
    cfg = config_de_raiz(raiz, "r")
    store = Store(tmp_path / "indice", DIM)

    progresso = indexar(cfg, store, EmbedderFalso(), limite_chunks=5, publicar=False)

    assert store.estado_documento("nota.txt").status == "ok"
    assert progresso.indexados == 1
    store.fechar()


def test_teto_de_trechos_nao_adia_markdown(tmp_path: Path) -> None:
    """O teto é para dump .txt/.csv. Relatório em markdown continua no índice."""
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (raiz / "relatorio.md").write_text("# T\n\n" + ("parágrafo. " * 40 + "\n") * 80, encoding="utf-8")
    cfg = config_de_raiz(raiz, "r")
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    progresso = indexar(
        cfg,
        store,
        emb,
        chunk_cfg=ChunkConfig(max_chars=60, min_chars=20, overlap_chars=8),
        limite_chunks=5,
        publicar=False,
    )

    assert store.estado_documento("relatorio.md").status == "ok"
    assert progresso.indexados == 1
    assert emb.chamadas > 0
    store.fechar()


# --- Exclusão declarada é conferida antes de abrir arquivo -------------------
#
# A passada é o caminho que paga o custo: quando a regra é inerte, é aqui que as
# 3 h 22 min de 26/08/2026 foram gastas. Conferir no censo e não aqui deixaria o
# defeito exatamente onde ele estava — o indexador roda sem censo nenhum.


def corpus_aninhado(raiz: Path) -> Path:
    (raiz / "corpus" / "16. Anexos volumosos").mkdir(parents=True)
    (raiz / "corpus" / "12. Normas").mkdir(parents=True)
    (raiz / "corpus" / "16. Anexos volumosos" / "anexo.md").write_text(
        "# Anexo\nTotal geral do anexo: 4.200.\n", encoding="utf-8"
    )
    (raiz / "corpus" / "12. Normas" / "norma.md").write_text(
        "# Norma\nA norma NR-000 exige registro anual.\n", encoding="utf-8"
    )
    return raiz


def _cfg_com_papel(raiz: Path, dirs: tuple[str, ...]) -> Config:
    regra = RoleExclusion(globs=("*",), dirs=dirs)
    return Config(
        roots=[RootSpec(name="teste", path=corpus_aninhado(raiz))],
        role_exclusions=(regra,),
        declared=DeclaredExclusions(roles=(regra,)),
    )


def test_progresso_publica_a_contagem_por_regra(tmp_path: Path) -> None:
    """Total sozinho não distingue exclusão declarada de regra inerte."""
    cfg = _cfg_com_papel(tmp_path / "raiz", ("corpus/16. Anexos volumosos",))
    store = Store(tmp_path / "indice", DIM)

    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=1)
    store.fechar()

    publicado = json.loads((tmp_path / "indice" / "progresso.json").read_text(encoding="utf-8"))
    exclusoes = publicado["exclusoes"]
    assert exclusoes["arquivos"] == 1
    assert exclusoes["inertes"] == []
    assert list(exclusoes["por_regra"].values()) == [1]
    assert progresso.indexados == 1, "o excluído não entrou no índice"


def test_regra_inerte_sai_como_aviso_no_progresso(tmp_path: Path) -> None:
    """O caso de 26/08 tal como foi escrito: prefixo sem `corpus/`."""
    cfg = _cfg_com_papel(tmp_path / "raiz", ("16. Anexos volumosos",))
    store = Store(tmp_path / "indice", DIM)

    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=1)
    store.fechar()

    publicado = json.loads((tmp_path / "indice" / "progresso.json").read_text(encoding="utf-8"))
    assert publicado["exclusoes"]["arquivos"] == 0
    assert len(publicado["exclusoes"]["inertes"]) == 1
    # e a passada correu mesmo assim: aviso é o padrão, recusa é opt-in
    assert progresso.indexados == 2


def test_exigir_exclusoes_recusa_antes_de_abrir_arquivo(tmp_path: Path) -> None:
    """Recusa antes do custo — nenhum documento no índice, nenhum byte lido."""
    cfg = _cfg_com_papel(tmp_path / "raiz", ("16. Anexos volumosos",))
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    with pytest.raises(ErroDeConfig, match="não casou com nada"):
        indexar(cfg, store, emb, parse_workers=1, exigir_exclusoes=True)

    assert emb.chamadas == 0
    assert store.estatisticas()["documentos"] == 0
    store.fechar()


def test_exigir_exclusoes_nao_atrapalha_regra_que_funciona(tmp_path: Path) -> None:
    cfg = _cfg_com_papel(tmp_path / "raiz", ("corpus/16. Anexos volumosos",))
    store = Store(tmp_path / "indice", DIM)

    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=1, exigir_exclusoes=True)
    store.fechar()

    assert progresso.indexados == 1


# --- FND-01a: recusa de colisão de caminhos antes de escrever ------------------


def test_colisao_de_caminhos_demonstracao_vulnerabilidade_anterior(tmp_path: Path) -> None:
    """Requirement 1 de FND-01a: demonstra que sem a guarda, o Store terminava com uma só linha.

    Dois arquivos homônimos em raízes distintas sobrescreviam-se mutuamente no SQLite
    devido ao ON CONFLICT(path), inclusive se o hash for idêntico.
    """
    store = Store(tmp_path / "indice", DIM)
    # Raiz A
    store.registrar_documento(
        path="contrato.md",
        raiz="raiz_a",
        tamanho=100,
        mtime=1.0,
        sha256="hash_a" * 8,
        status="ok",
    )
    store.commit()
    assert store.estatisticas()["documentos"] == 1
    raiz_doc_a = store.con.execute("SELECT raiz FROM documentos WHERE path = 'contrato.md'").fetchone()[0]
    assert raiz_doc_a == "raiz_a"

    # Raiz B registra mesmo path (conteúdo diferente)
    store.registrar_documento(
        path="contrato.md",
        raiz="raiz_b",
        tamanho=200,
        mtime=2.0,
        sha256="hash_b" * 8,
        status="ok",
    )
    store.commit()
    # O Store antigo terminava com uma única linha, da raiz B
    assert store.estatisticas()["documentos"] == 1
    raiz_doc_b = store.con.execute("SELECT raiz FROM documentos WHERE path = 'contrato.md'").fetchone()[0]
    assert raiz_doc_b == "raiz_b"

    # Caso com mesmo hash em raízes distintas
    store.registrar_documento(
        path="mesmo_hash.md",
        raiz="raiz_a",
        tamanho=50,
        mtime=1.0,
        sha256="mesmo_hash" * 6,
        status="ok",
    )
    store.registrar_documento(
        path="mesmo_hash.md",
        raiz="raiz_b",
        tamanho=50,
        mtime=2.0,
        sha256="mesmo_hash" * 6,
        status="ok",
    )
    store.commit()
    raiz_hash = store.con.execute("SELECT raiz FROM documentos WHERE path = 'mesmo_hash.md'").fetchone()[0]
    assert raiz_hash == "raiz_b"
    store.fechar()


def test_indexar_recusa_colisao_duas_raizes(tmp_path: Path) -> None:
    """FND-01a: recusa a passada antes de qualquer escrita quando há homônimos."""
    raiz_a = tmp_path / "raiz_a"
    raiz_b = tmp_path / "raiz_b"
    raiz_a.mkdir()
    raiz_b.mkdir()
    (raiz_a / "contrato.md").write_text("# Contrato A\nconteudo a\n", encoding="utf-8")
    (raiz_b / "contrato.md").write_text("# Contrato B\nconteudo b\n", encoding="utf-8")

    cfg = Config(roots=[RootSpec(name="raiz_a", path=raiz_a), RootSpec(name="raiz_b", path=raiz_b)])
    store = Store(tmp_path / "indice", DIM)
    emb = EmbedderFalso()

    with pytest.raises(ColisaoDeCaminho) as exc_info:
        indexar(cfg, store, emb, parse_workers=1)

    msg = str(exc_info.value)
    assert "contrato.md" in msg
    assert "raiz_a" in msg
    assert "raiz_b" in msg
    assert "bases distintas" in msg
    assert "config.toml" in msg

    # Integridade comprovada: nenhum documento gerou embeddings, nenhum foi gravado
    assert emb.chamadas == 0
    assert store.estatisticas()["documentos"] == 0

    # Estado de execução registrado explicitamente como 'recusada'
    status_exec = store.con.execute("SELECT status FROM execucoes ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert status_exec == "recusada"
    store.fechar()


def test_indexar_recusa_colisao_ordem_invertida(tmp_path: Path) -> None:
    """A recusa não favorece a primeira nem a última raiz silenciosamente."""
    raiz_a = tmp_path / "raiz_a"
    raiz_b = tmp_path / "raiz_b"
    raiz_a.mkdir()
    raiz_b.mkdir()
    (raiz_a / "nota.txt").write_text("nota a\n", encoding="utf-8")
    (raiz_b / "nota.txt").write_text("nota b\n", encoding="utf-8")

    cfg = Config(roots=[RootSpec(name="raiz_b", path=raiz_b), RootSpec(name="raiz_a", path=raiz_a)])
    store = Store(tmp_path / "indice", DIM)

    with pytest.raises(ColisaoDeCaminho):
        indexar(cfg, store, EmbedderFalso(), parse_workers=1)
    store.fechar()


def test_indexar_recusa_colisao_mesmo_hash(tmp_path: Path) -> None:
    """Mesmo conteúdo/hash em raízes distintas também é recusado para evitar colisão de procedência."""
    raiz_a = tmp_path / "raiz_a"
    raiz_b = tmp_path / "raiz_b"
    raiz_a.mkdir()
    raiz_b.mkdir()
    conteudo = "# Idêntico\nmesmo conteúdo em ambas as raízes\n"
    (raiz_a / "identico.md").write_text(conteudo, encoding="utf-8")
    (raiz_b / "identico.md").write_text(conteudo, encoding="utf-8")

    cfg = Config(roots=[RootSpec(name="raiz_a", path=raiz_a), RootSpec(name="raiz_b", path=raiz_b)])
    store = Store(tmp_path / "indice", DIM)

    with pytest.raises(ColisaoDeCaminho):
        indexar(cfg, store, EmbedderFalso(), parse_workers=1)
    store.fechar()


def test_indexar_recusa_colisao_contra_indice_pre_existente(tmp_path: Path) -> None:
    """Conflito entre raiz atual e raiz já registrada no Store recusa sem apagar nada."""
    raiz_a = tmp_path / "raiz_a"
    raiz_b = tmp_path / "raiz_b"
    raiz_a.mkdir()
    raiz_b.mkdir()
    (raiz_a / "contrato.md").write_text("# Contrato A\n", encoding="utf-8")
    (raiz_b / "contrato.md").write_text("# Contrato B\n", encoding="utf-8")

    store = Store(tmp_path / "indice", DIM)
    # 1. Indexa raiz A normalmente
    cfg_a = Config(roots=[RootSpec(name="raiz_a", path=raiz_a)])
    progresso_a = indexar(cfg_a, store, EmbedderFalso(), parse_workers=1)
    assert progresso_a.indexados == 1
    assert store.estatisticas()["documentos"] == 1
    raiz_antes = store.con.execute("SELECT raiz FROM documentos WHERE path = 'contrato.md'").fetchone()[0]
    assert raiz_antes == "raiz_a"

    # 2. Tenta indexar raiz B com o mesmo contrato.md
    cfg_b = Config(roots=[RootSpec(name="raiz_b", path=raiz_b)])
    with pytest.raises(ColisaoDeCaminho) as exc_info:
        indexar(cfg_b, store, EmbedderFalso(), parse_workers=1)

    assert "raiz_b" in str(exc_info.value)
    assert "raiz_a" in str(exc_info.value)

    # 3. Estado anterior permaneceu intocado; reconciliação de remoção NÃO disparou
    assert store.estatisticas()["documentos"] == 1
    raiz_depois = store.con.execute("SELECT raiz FROM documentos WHERE path = 'contrato.md'").fetchone()[0]
    assert raiz_depois == "raiz_a"
    store.fechar()


def test_indexar_recusa_colisao_com_prefixo(tmp_path: Path) -> None:
    """Passada incremental com --prefixo detecta conflito se o prefixo alcançar o homônimo."""
    raiz_a = tmp_path / "raiz_a"
    raiz_b = tmp_path / "raiz_b"
    (raiz_a / "sub").mkdir(parents=True)
    (raiz_b / "sub").mkdir(parents=True)
    (raiz_a / "sub" / "doc.md").write_text("# Doc A\n", encoding="utf-8")
    (raiz_b / "sub" / "doc.md").write_text("# Doc B\n", encoding="utf-8")

    cfg = Config(roots=[RootSpec(name="raiz_a", path=raiz_a), RootSpec(name="raiz_b", path=raiz_b)])
    store = Store(tmp_path / "indice", DIM)

    with pytest.raises(ColisaoDeCaminho):
        indexar(cfg, store, EmbedderFalso(), parse_workers=1, prefixo="sub")
    store.fechar()


def test_indexar_duas_raizes_sem_homonimos_sucesso(tmp_path: Path) -> None:
    """Bases sem colisão preservam comportamento normal de indexação."""
    raiz_a = tmp_path / "raiz_a"
    raiz_b = tmp_path / "raiz_b"
    raiz_a.mkdir()
    raiz_b.mkdir()
    (raiz_a / "doc_a.md").write_text("# Doc A\n", encoding="utf-8")
    (raiz_b / "doc_b.md").write_text("# Doc B\n", encoding="utf-8")

    cfg = Config(roots=[RootSpec(name="raiz_a", path=raiz_a), RootSpec(name="raiz_b", path=raiz_b)])
    store = Store(tmp_path / "indice", DIM)

    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=1)
    assert progresso.indexados == 2
    assert store.estatisticas()["documentos"] == 2
    store.fechar()


def test_indexar_raiz_vazia_sem_colisao_sucesso(tmp_path: Path) -> None:
    raiz_a = tmp_path / "raiz_a"
    raiz_b = tmp_path / "raiz_b"
    raiz_a.mkdir()
    raiz_b.mkdir()
    (raiz_a / "doc_a.md").write_text("# Doc A\n", encoding="utf-8")

    cfg = Config(roots=[RootSpec(name="raiz_a", path=raiz_a), RootSpec(name="raiz_b", path=raiz_b)])
    store = Store(tmp_path / "indice", DIM)

    progresso = indexar(cfg, store, EmbedderFalso(), parse_workers=1)
    assert progresso.indexados == 1
    assert store.estatisticas()["documentos"] == 1
    store.fechar()

