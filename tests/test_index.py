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

import hashlib
from pathlib import Path

import numpy as np
import pytest

from segundocerebro.census import Config, RootSpec
from segundocerebro.ingest.chunking import CHUNKER_VERSION, Chunk, ChunkConfig
from segundocerebro.ingest.document import BlockKind
from segundocerebro.index.indexer import indexar
from segundocerebro.index.store import Store, consulta_fts

DIM = 8


class EmbedderFalso:
    """Deterministic fake — the real model takes seconds to load per test."""

    def __init__(self, model_id: str = "falso:8", dim: int = DIM) -> None:
        self._model_id = model_id
        self.spec = type("Spec", (), {"id": "falso", "dim": dim})()
        self.dim = dim
        self.chamadas = 0
        self._cache_dir = Path("models")

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def orcamento_tokens(self) -> int:
        return 10_000  # folgado: estes testes não exercitam o orçamento

    def contar_tokens(self, texto: str) -> int:
        return len(texto) // 4

    def embed_passagens(self, textos, batch_size: int = 32) -> list[np.ndarray]:  # noqa: ANN001, ARG002
        self.chamadas += len(textos)
        saida = []
        for t in textos:
            semente = int(hashlib.sha1(t.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(semente)
            v = rng.standard_normal(self.dim).astype(np.float32)
            saida.append(v / np.linalg.norm(v))
        return saida

    def embed_consulta(self, texto: str) -> np.ndarray:
        return self.embed_passagens([texto])[0]


def chunk(id_: str, path: str, ordinal: int, texto: str, trilha: tuple[str, ...] = ()) -> Chunk:
    return Chunk(
        id=id_,
        doc_path=path,
        ordinal=ordinal,
        heading_path=trilha,
        text=texto,
        locator=f"p. {ordinal + 1}",
        kind=BlockKind.TEXT,
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "indice", DIM)
    yield s
    s.fechar()


def corpus(raiz: Path) -> Config:
    (raiz / "Política de IA").mkdir(parents=True)
    (raiz / "Política de IA" / "PO-ACME-007_Política_IA_v8.md").write_text(
        "# Política\nO PO-ACME-007 define o uso aceitável de inteligência artificial.\n", encoding="utf-8"
    )
    (raiz / "contrato.md").write_text(
        "# Contrato\nContrato 4600009999 com a Nimbus Tecnologia, vigência de 12 meses.\n", encoding="utf-8"
    )
    (raiz / "vazio.md").write_text("   \n", encoding="utf-8")
    return Config(roots=[RootSpec(name="teste", path=raiz)])


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
    monkeypatch.setattr("segundocerebro.index.indexer.contar_gpus", lambda: 2)
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
            self.tamanho = 10
            self.mtime = 1.0
            self.sha256 = "abc"
            self.n_chunks = 0

    class Arquivo:
        size = 10
        mtime = 1.0

    for status in ("travado", "placeholder", "erro", "sem_parser"):
        assert _precisa_indexar(Estado(status), Arquivo(), "m:8"), f"{status} tem que ser repescado"


def test_documento_ok_ou_vazio_nao_e_reprocessado(tmp_path: Path) -> None:
    """`vazio` é determinístico: repescar custaria reprocessar PDF de 61 páginas por passada."""
    from segundocerebro.index.indexer import CHUNKER_VERSION, _precisa_indexar

    class Estado:
        def __init__(self, status: str) -> None:
            self.status = status
            self.model_id = "m:8"
            self.chunker = CHUNKER_VERSION
            self.tamanho = 10
            self.mtime = 1.0
            self.sha256 = "abc"
            self.n_chunks = 3

    class Arquivo:
        size = 10
        mtime = 1.0

    assert not _precisa_indexar(Estado("ok"), Arquivo(), "m:8")
    assert not _precisa_indexar(Estado("vazio"), Arquivo(), "m:8")
