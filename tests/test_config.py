"""Configuração multi-base: herança, ambiente, resolução e isolamento.

O teste que mais importa aqui é `test_espelhos_batem_com_o_codigo`. `config.py`
repete os padrões em vez de importá-los, para não arrastar `fastembed` e `numpy`
para dentro de toda leitura de configuração — e duas cópias de um número
divergem em silêncio se nada as amarrar. Ele é essa amarra.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from segundocerebro.census import RootSpec
from segundocerebro.config import (
    BASE_UNICA,
    Base,
    Busca,
    Chunking,
    Config,
    ErroDeConfig,
    Maquina,
    Pesos,
    carregar,
    gravar,
)

SEM_AMBIENTE: dict[str, str] = {}


def escrever(tmp_path: Path, texto: str) -> Path:
    caminho = tmp_path / "config.toml"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


# --------------------------------------------------------------------------- #
# A amarra entre os espelhos e o código


def test_espelhos_batem_com_o_codigo():
    """Os padrões de `config.py` são os mesmos das constantes que ele espelha."""
    from segundocerebro.index.embeddings import MODELO_PADRAO
    from segundocerebro.ingest.chunking import ChunkConfig
    from segundocerebro.mcp.server import JANELA_MAX, JANELA_PADRAO, K_MAX, K_PADRAO
    from segundocerebro.retrieve import hybrid

    assert Pesos() == Pesos(hybrid.PESO_DENSO, hybrid.PESO_LEXICAL, hybrid.PESO_NOME)

    busca = Busca()
    assert busca.candidatos == hybrid.CANDIDATOS
    assert busca.k_rrf == hybrid.K_RRF
    assert (busca.k, busca.k_max) == (K_PADRAO, K_MAX)
    assert (busca.janela, busca.janela_max) == (JANELA_PADRAO, JANELA_MAX)

    padrao_chunk = ChunkConfig()
    assert Chunking() == Chunking(
        padrao_chunk.max_chars, padrao_chunk.min_chars, padrao_chunk.overlap_chars
    )

    assert Base(id="x").modelo == MODELO_PADRAO

    from segundocerebro.config import LimitesDeIndexacao
    from segundocerebro.index.indexer import LIMITE_TEXTO_MB_PADRAO, LOTE_EMBEDDING

    assert Maquina().lote == LOTE_EMBEDDING
    assert LIMITE_TEXTO_MB_PADRAO == LimitesDeIndexacao().txt


# --------------------------------------------------------------------------- #
# Herança


def test_base_herda_de_padrao(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [padrao]
        modelo = "minilm"
        [padrao.pesos]
        denso = 0.8
        [[base]]
        id = "a"
        indice = "ia"
        """,
    )
    base = carregar(caminho, ambiente=SEM_AMBIENTE).base("a")
    assert base.modelo == "minilm"
    assert base.pesos.denso == 0.8
    assert base.pesos.lexical == Pesos().lexical, "o que a base não sobrescreve continua padrão"


def test_base_sobrescreve_padrao(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [padrao.pesos]
        lexical = 0.25
        [[base]]
        id = "trabalho"
        indice = "it"
        [base.pesos]
        lexical = 0.5
        """,
    )
    assert carregar(caminho, ambiente=SEM_AMBIENTE).base("trabalho").pesos.lexical == 0.5


def test_chave_desconhecida_em_secao_e_erro(tmp_path):
    """Errar o nome de um peso não pode virar 'a configuração não fez efeito'."""
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [base.pesos]
        densoo = 1.0
        """,
    )
    with pytest.raises(ErroDeConfig, match="densoo"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_exclusoes_somam_e_nao_substituem(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [base.exclude]
        dirs = ["Backups"]
        """,
    )
    base = carregar(caminho, ambiente=SEM_AMBIENTE).base("a")
    assert "Backups" in base.exclude_dirs
    assert ".git" in base.exclude_dirs, "as exclusões técnicas continuam valendo"


# --------------------------------------------------------------------------- #
# Resolução de base


def test_base_unica_dispensa_escolha(tmp_path):
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\n')
    assert carregar(caminho, ambiente=SEM_AMBIENTE).base().id == "a"


def test_duas_bases_sem_escolha_e_erro(tmp_path):
    """A ambiguidade é que é erro. Indexar por cima do índice errado é caro."""
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        indice = "ia"
        [[base]]
        id = "b"
        indice = "ib"
        """,
    )
    cfg = carregar(caminho, ambiente=SEM_AMBIENTE)
    with pytest.raises(ErroDeConfig, match="--base"):
        cfg.base(ambiente=SEM_AMBIENTE)
    assert cfg.base("b", ambiente=SEM_AMBIENTE).id == "b"
    assert cfg.base(ambiente={"SEGUNDOCEREBRO_BASE": "b"}).id == "b"


def test_base_inexistente_lista_as_que_existem(tmp_path):
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\n')
    with pytest.raises(ErroDeConfig, match="a"):
        carregar(caminho, ambiente=SEM_AMBIENTE).base("nao-existe", ambiente=SEM_AMBIENTE)


# --------------------------------------------------------------------------- #
# Isolamento — invariante 7


def test_duas_bases_no_mesmo_indice_e_erro(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "pessoal"
        indice = "index"
        [[base]]
        id = "trabalho"
        indice = "index"
        """,
    )
    with pytest.raises(ErroDeConfig, match="mesmo índice"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_indice_de_uma_base_dentro_da_outra_e_erro(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "pessoal"
        indice = "index"
        [[base]]
        id = "trabalho"
        indice = "index/trabalho"
        """,
    )
    with pytest.raises(ErroDeConfig, match="dentro"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_indice_padrao_por_base_nao_colide(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [[base]]
        id = "b"
        """,
    )
    cfg = carregar(caminho, ambiente=SEM_AMBIENTE)
    assert cfg.base("a").indice == tmp_path / "index" / "a"
    assert cfg.base("b").indice == tmp_path / "index" / "b"


def test_caminho_relativo_ancora_no_arquivo_e_nao_no_cwd(tmp_path, monkeypatch):
    """Rodar de outra pasta não pode mudar qual índice é aberto.

    O modo de falha seria silencioso: índice vazio, e o sintoma ("a busca não
    acha nada") apontaria para o ranqueador em vez de para o caminho.
    """
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\nindice = "meu-indice"\n')
    monkeypatch.chdir(tmp_path.parent)

    assert carregar(caminho, ambiente=SEM_AMBIENTE).base("a").indice == tmp_path / "meu-indice"


def test_gravar_mantem_relativo_o_que_era_relativo(tmp_path):
    """Simetria de `_resolver`: o par config.toml + index/ continua copiável."""
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\nindice = "meu-indice"\n')
    cfg = carregar(caminho, ambiente=SEM_AMBIENTE)

    destino = tmp_path / "saida.toml"
    gravar(cfg, destino)

    assert 'indice = "meu-indice"' in destino.read_text(encoding="utf-8")
    assert carregar(destino, ambiente=SEM_AMBIENTE).base("a").indice == tmp_path / "meu-indice"


def test_duas_bases_no_mesmo_dourado_e_erro(tmp_path):
    """Mesmo motivo do índice: dois números plausíveis e incomparáveis."""
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        indice = "ia"
        dourado = "eval/golden/perguntas.jsonl"
        [[base]]
        id = "b"
        indice = "ib"
        dourado = "eval/golden/perguntas.jsonl"
        """,
    )
    with pytest.raises(ErroDeConfig, match="mesmo conjunto"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_glossario_e_opcional_e_nasce_vazio(tmp_path):
    """Nenhum dicionário embutido: o genérico mediu zero (`docs/ablacao-glossario.md`)."""
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\nindice = "i"\n')
    assert carregar(caminho, ambiente=SEM_AMBIENTE).base("a").glossario is None


def test_glossario_e_ancorado_na_raiz_do_config(tmp_path):
    """Como o `dourado`: o par `config.toml` + acervo tem que poder ser copiado."""
    caminho = escrever(
        tmp_path, '[[base]]\nid = "a"\nindice = "i"\nglossario = "siglas.toml"\n'
    )
    resolvido = carregar(caminho, ambiente=SEM_AMBIENTE).base("a").glossario
    assert resolvido == tmp_path / "siglas.toml"


def test_dourado_e_opcional(tmp_path):
    """Sem declarar, o eval usa o padrão — que é o caso de hoje."""
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\n')
    assert carregar(caminho, ambiente=SEM_AMBIENTE).base("a").dourado is None


def test_raizes_sobrepostas_avisam_sem_impedir(tmp_path, caplog, monkeypatch):
    # `logger.py` desliga a propagação de propósito — stdout é do protocolo MCP.
    # Religar aqui é o que deixa o caplog enxergar o aviso.
    monkeypatch.setattr(logging.getLogger("segundocerebro"), "propagate", True)
    raiz = str(tmp_path).replace("\\", "\\\\")
    caminho = escrever(
        tmp_path,
        f"""
        [[base]]
        id = "a"
        indice = "ia"
        raizes = [{{ nome = "r", caminho = "{raiz}" }}]
        [[base]]
        id = "b"
        indice = "ib"
        raizes = [{{ nome = "r", caminho = "{raiz}" }}]
        """,
    )
    with caplog.at_level("WARNING"):
        cfg = carregar(caminho, ambiente=SEM_AMBIENTE)
    assert len(cfg.bases) == 2, "sobreposição é legítima — só cara"
    assert "sobreposta" in caplog.text


# --------------------------------------------------------------------------- #
# Ambiente: só a classe grátis


def test_ambiente_altera_peso_e_threads(tmp_path):
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\n')
    cfg = carregar(
        caminho,
        ambiente={"SEGUNDOCEREBRO_PESO_LEXICAL": "0.75", "SEGUNDOCEREBRO_THREADS": "2"},
    )
    assert cfg.base("a").pesos.lexical == 0.75
    assert cfg.maquina.threads == 2, "threads é da máquina, não da base"


def test_ambiente_nao_alcanca_parametro_de_indice(tmp_path):
    """Trocar modelo ou chunking custa horas de reindexação e invalida medição.

    Uma variável de ambiente é o caminho silencioso que a separação por custo
    existe para impedir — ver o docstring de `config.py`.
    """
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\nmodelo = "minilm"\n')
    base = carregar(
        caminho,
        ambiente={"SEGUNDOCEREBRO_MODELO": "e5-large", "SEGUNDOCEREBRO_MAX_CHARS": "9000"},
    ).base("a")
    assert base.modelo == "minilm"
    assert base.chunking.max_chars == Chunking().max_chars


def test_ambiente_com_numero_invalido_falha_claro(tmp_path):
    caminho = escrever(tmp_path, '[[base]]\nid = "a"\n')
    with pytest.raises(ErroDeConfig, match="SEGUNDOCEREBRO_THREADS"):
        carregar(caminho, ambiente={"SEGUNDOCEREBRO_THREADS": "muitas"})


# --------------------------------------------------------------------------- #
# Máquina — hardware muda velocidade, nunca conteúdo


def test_maquina_e_do_computador_nao_da_base(tmp_path):
    """O mesmo config.toml acompanha o acervo entre notebook e desktop."""
    caminho = escrever(
        tmp_path,
        """
        [maquina]
        perfil = "gpu"
        threads = 24
        provider = "cuda"
        [[base]]
        id = "a"
        [[base]]
        id = "b"
        """,
    )
    cfg = carregar(caminho, ambiente=SEM_AMBIENTE)
    assert (cfg.maquina.perfil, cfg.maquina.threads, cfg.maquina.provider) == ("maximo", 24, "cuda")
    assert not hasattr(cfg.base("a"), "threads"), "threads não é atributo de base"


def test_ambiente_vence_o_arquivo_na_maquina(tmp_path):
    """É assim que o notebook roda a configuração escrita para o desktop."""
    caminho = escrever(tmp_path, '[maquina]\nperfil = "gpu"\nthreads = 24\n[[base]]\nid = "a"\n')
    m = carregar(
        caminho, ambiente={"SEGUNDOCEREBRO_PERFIL": "leve", "SEGUNDOCEREBRO_THREADS": "4"}
    ).maquina
    assert (m.perfil, m.threads) == ("leve", 4)


def test_perfil_leve_usa_metade_dos_nucleos():
    """Leve ~25%, normal ~50% e nunca 100% se houver núcleo de sobra. Máximo usa tudo."""
    assert Maquina(perfil="leve").threads_efetivos(nucleos=12) == 3
    assert Maquina(perfil="normal").threads_efetivos(nucleos=12) == 6
    assert Maquina(perfil="completo").threads_efetivos(nucleos=12) == 6, "completo é alias de normal"
    assert Maquina(perfil="maximo").threads_efetivos(nucleos=12) == 12
    assert Maquina(perfil="leve", threads=10).threads_efetivos(nucleos=12) == 10, "explícito vence"
    assert Maquina(perfil="normal").threads_efetivos(nucleos=12) < 12
    assert Maquina(perfil="leve").threads_efetivos(nucleos=12) < 12


def test_alias_completo_e_gpu_continuam_lendo(tmp_path):
    caminho = escrever(tmp_path, '[maquina]\nperfil = "completo"\n[[base]]\nid = "a"\n')
    assert carregar(caminho, ambiente=SEM_AMBIENTE).maquina.perfil == "normal"
    caminho2 = escrever(tmp_path, '[maquina]\nperfil = "gpu"\n[[base]]\nid = "b"\n')
    assert carregar(caminho2, ambiente=SEM_AMBIENTE).maquina.perfil == "maximo"


def test_perfil_invalido(tmp_path):
    caminho = escrever(tmp_path, '[maquina]\nperfil = "turbo"\n[[base]]\nid = "a"\n')
    with pytest.raises(ErroDeConfig, match="perfil de máquina"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_provider_nao_entra_na_identidade_do_indice():
    """Se `model_id` carregasse o provider, copiar o índice reembeddaria tudo.

    Guarda a propriedade que torna legítimo indexar no desktop e consultar no
    notebook (`ARCHITECTURE.md` §4).
    """
    from segundocerebro.index.embeddings import Embedder

    assert "cuda" not in Embedder("minilm").model_id.lower()
    assert "provider" not in Embedder("minilm").model_id.lower()


# --------------------------------------------------------------------------- #
# Validação


@pytest.mark.parametrize(
    "trecho, esperado",
    [
        ('[[base]]\nid = "Maiúscula"\n', "id de base inválido"),
        ('[[base]]\nid = "a"\n[base.pesos]\ndenso = -1\n', "negativo"),
        ('[[base]]\nid = "a"\n[base.pesos]\ndenso = 0\nlexical = 0\nnome = 0\n', "três pesos"),
        ('[[base]]\nid = "a"\n[base.busca]\nk = 999\n', "k_max"),
        ('[[base]]\nid = "a"\n[base.chunking]\nmin_chars = 5000\n', "min_chars"),
        ("versao = 99\n[[base]]\nid = \"a\"\n", "versão"),
        ("[padrao]\nmodelo = \"minilm\"\n", r"nenhuma \[\[base\]\]"),
    ],
)
def test_configuracao_invalida(tmp_path, trecho, esperado):
    with pytest.raises(ErroDeConfig, match=esperado):
        carregar(escrever(tmp_path, trecho), ambiente=SEM_AMBIENTE)


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(ErroDeConfig, match="não encontrada"):
        carregar(tmp_path / "nao-existe.toml", ambiente=SEM_AMBIENTE)


# --------------------------------------------------------------------------- #
# Continuidade: o census.toml de hoje


def test_census_legado_vira_base_unica(tmp_path, monkeypatch):
    """Nada reindexa por causa desta fase: a base aponta para o `index/` atual."""
    (tmp_path / "census.toml").write_text(
        '[[roots]]\nname = "pessoal"\npath = \'C:\\Docs\'\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    cfg = carregar(ambiente=SEM_AMBIENTE)
    base = cfg.base()
    assert base.id == BASE_UNICA
    assert base.indice == Path("index")
    assert [r.name for r in base.raizes] == ["pessoal"]
    assert cfg.caminho is None, "sintetizada — o painel não deve escrever por cima do census"


def test_sem_arquivo_nenhum_usa_padroes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = carregar(ambiente=SEM_AMBIENTE).base()
    assert base.id == BASE_UNICA
    assert base.pesos == Pesos()


def test_census_apontado_a_mao_continua_valendo(tmp_path):
    """`--config census.toml` está nos comandos documentados e tem que rodar."""
    censo = tmp_path / "census.toml"
    censo.write_text("[[roots]]\nname = 'x'\npath = 'C:\\\\Docs'\n", encoding="utf-8")

    base = carregar(censo, ambiente=SEM_AMBIENTE).base()
    assert base.id == BASE_UNICA
    assert [r.name for r in base.raizes] == ["x"]


def test_raiz_de_descoberta(tmp_path):
    """Descobre a configuração fora do diretório de trabalho."""
    (tmp_path / "config.toml").write_text('[[base]]\nid = "remota"\n', encoding="utf-8")
    assert carregar(ambiente=SEM_AMBIENTE, raiz=tmp_path).base().id == "remota"


def test_config_toml_tem_precedencia_sobre_census(tmp_path, monkeypatch):
    (tmp_path / "census.toml").write_text("[[roots]]\npath = 'C:\\Docs'\n", encoding="utf-8")
    (tmp_path / "config.toml").write_text('[[base]]\nid = "nova"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert carregar(ambiente=SEM_AMBIENTE).base().id == "nova"


# --------------------------------------------------------------------------- #
# Ponte para o resto do sistema


def test_censo_traduz_para_o_indexador(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        raizes = [{ nome = "docs", caminho = 'C:\\Docs' }]
        [base.exclude]
        dirs = ["Velho"]
        """,
    )
    censo = carregar(caminho, ambiente=SEM_AMBIENTE).base("a").censo()
    assert [r.name for r in censo.roots] == ["docs"]
    assert censo.excluded_dir("Velho")
    assert censo.excluded_dir(".git")


def test_pesos_da_base_chegam_na_busca():
    """A ponte que faz o número medido ser o número que roda."""
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    base = Base(id="a", pesos=Pesos(denso=1.0, lexical=0.5, nome=0.0), busca=Busca(candidatos=50, k_rrf=10))
    busca = BuscaHibrida.de_base(None, None, base)

    assert (busca.peso_denso, busca.peso_lexical, busca.peso_nome) == (1.0, 0.5, 0.0)
    assert (busca.candidatos, busca.k_rrf) == (50, 10)
    assert busca.usar_denso and busca.usar_lexical
    assert not busca.usar_nome, "peso zero desliga o ranqueador, não entra com voz nula"


def test_pesos_de_coluna_do_fts_chegam_na_busca():
    """`C3.a`: a ponte dos pesos de coluna do bm25, que são de consulta."""
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    base = Base(id="a", pesos=Pesos(fts_trilha=0.5, fts_caminho=0.3))
    busca = BuscaHibrida.de_base(None, None, base)

    assert busca.pesos_fts == (1.0, 0.5, 0.3)


def test_pesos_de_coluna_padrao_nao_chegam_como_tripla():
    """1/1/1 vira `None`, para o SQL ser o `bm25(chunks_fts)` que mediu F1 a F4.

    Não é frescura: passar (1,1,1) daria o mesmo número por um caminho de código
    que nunca foi medido, e é a classe de troca que já custou caro aqui.
    """
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    assert Pesos().colunas_fts is None
    assert BuscaHibrida.de_base(None, None, Base(id="a")).pesos_fts is None


def test_peso_de_coluna_negativo_e_recusado():
    with pytest.raises(ErroDeConfig, match="fts_caminho"):
        Pesos(fts_caminho=-0.1).validar("[base.pesos]")


def test_lexical_ativo_com_as_tres_colunas_em_zero_e_recusado():
    """Configuração que pede busca lexical e a deixa sem coluna nenhuma para ordenar."""
    with pytest.raises(ErroDeConfig, match="colunas do bm25"):
        Pesos(lexical=0.25, fts_texto=0, fts_trilha=0, fts_caminho=0).validar("[base.pesos]")


def test_colunas_em_zero_passam_se_o_lexical_estiver_desligado():
    """Sem ranqueador lexical não há bm25 a configurar — recusar seria zelo falso."""
    Pesos(lexical=0, fts_texto=0, fts_trilha=0, fts_caminho=0).validar("[base.pesos]")


def test_rerank_desligado_por_padrao():
    """Melhora a qualidade e custa 6,8× no tempo — o padrão é o tempo.

    Medido em 16/08/2026: recall@1 0,644 → 0,678, e a consulta 0,92 s → 6,28 s.
    """
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    assert BuscaHibrida.de_base(None, None, Base(id="a")).reranker is None


def test_rerank_da_base_chega_na_busca():
    ligado = Base(id="a", busca=Busca(rerank=0.25, rerank_candidatos=10))
    busca = BuscaHibrida_de(ligado)

    assert busca.reranker is not None
    assert busca.reranker.peso == 0.25
    assert busca.reranker.candidatos == 10


def test_construir_reranker_nao_carrega_o_modelo():
    """1 GB não pode abrir só porque alguém montou um recuperador."""
    busca = BuscaHibrida_de(Base(id="a", busca=Busca(rerank=0.25)))
    assert busca.reranker._encoder is None


def BuscaHibrida_de(base):  # noqa: N802, ANN001, ANN201
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    return BuscaHibrida.de_base(None, None, base)


def test_nome_do_servidor_mcp():
    """Base única mantém o nome histórico — não quebra .mcp.json existente."""
    assert Base(id=BASE_UNICA).servidor == "segundocerebro"
    assert Base(id="trabalho").servidor == "segundocerebro-trabalho"


def test_config_sem_base_e_erro():
    with pytest.raises(ErroDeConfig, match="nenhuma base"):
        Config(bases=()).validar()


# --------------------------------------------------------------------------- #
# Gravar — a metade que o painel precisa


def test_ida_e_volta_preserva_a_configuracao(tmp_path):
    """Exigência 2 do critério de saída: o que o painel grava é o que a busca usa."""
    original = escrever(
        tmp_path,
        r"""
        [maquina]
        perfil = "gpu"
        threads = 24
        [[base]]
        id = "trabalho"
        nome = "Acme Holding"
        descricao = "Contratos e atas."
        indice = "index"
        modelo = "minilm"
        dourado = "eval/golden/trabalho.jsonl"
        glossario = "eval/glossario-trabalho.toml"
        raizes = [{ nome = "va", caminho = 'C:\Users\alguém\Área de Trabalho\07. Acme Holding' }]
        [base.pesos]
        lexical = 0.5
        [base.busca]
        k = 12
        [base.exclude]
        dirs = ["Backups"]
        """,
    )
    antes = carregar(original, ambiente=SEM_AMBIENTE)

    destino = tmp_path / "gravado.toml"
    gravar(antes, destino)
    depois = carregar(destino, ambiente=SEM_AMBIENTE)

    assert depois.bases == antes.bases
    assert depois.maquina == antes.maquina


def test_gravar_escapa_caminho_do_windows(tmp_path):
    """Barra invertida e acento no caminho é o caso normal aqui, não a exceção."""
    caminho = Path(r"C:\Users\alguem\Área de Trabalho\07. Acme Holding")
    cfg = Config(bases=(Base(id="a", raizes=(RootSpec(name="va", path=caminho),)),))

    destino = tmp_path / "c.toml"
    gravar(cfg, destino)

    assert carregar(destino, ambiente=SEM_AMBIENTE).base("a").raizes[0].path == caminho


def test_gravar_omite_o_que_e_padrao(tmp_path):
    """Arquivo que repete todo padrão vira cópia congelada do dia em que nasceu."""
    destino = tmp_path / "c.toml"
    gravar(Config(bases=(Base(id="a"),)), destino)

    texto = destino.read_text(encoding="utf-8")
    assert "pesos" not in texto and "chunking" not in texto
    assert "limites" not in texto
    assert "maquina" not in texto
    assert 'id = "a"' in texto


def test_limites_por_tipo_sobrescrevem_o_padrao(tmp_path):
    """Teto de dump é da base: um acervo tem CSV enorme, outro pode não ter."""
    from segundocerebro.config import LimitesDeIndexacao

    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "vce"
        [base.limites]
        csv = 5
        xlsx = 40
        txt = 0
        """,
    )
    base = carregar(caminho, ambiente=SEM_AMBIENTE).base("vce", ambiente=SEM_AMBIENTE)

    assert base.limites.csv == 5
    assert base.limites.xlsx == 40
    assert base.limites.txt == 0
    assert base.limites.pdf == 0
    assert ".csv" in base.limites.como_mapa()
    assert ".txt" not in base.limites.como_mapa()
    assert base.limites.como_mapa()[".xlsx"] == 40
    assert LimitesDeIndexacao().txt == 2.0


def test_limites_desconhecidos_sao_erro(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [base.limites]
        exe = 10
        """,
    )
    with pytest.raises(ErroDeConfig, match="exe"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_ida_e_volta_preserva_limites(tmp_path):
    original = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [base.limites]
        pdf = 80
        csv = 1.5
        """,
    )
    antes = carregar(original, ambiente=SEM_AMBIENTE)
    destino = tmp_path / "gravado.toml"
    gravar(antes, destino)
    depois = carregar(destino, ambiente=SEM_AMBIENTE)
    assert depois.base("a", ambiente=SEM_AMBIENTE).limites == antes.base("a", ambiente=SEM_AMBIENTE).limites


def test_gravar_recusa_configuracao_invalida(tmp_path):
    """Validar antes de escrever: arquivo inválido em disco trava o servidor."""
    ruim = Config(bases=(Base(id="a", indice=Path("i")), Base(id="b", indice=Path("i"))))
    destino = tmp_path / "c.toml"

    with pytest.raises(ErroDeConfig, match="mesmo índice"):
        gravar(ruim, destino)
    assert not destino.exists()


def test_gravar_nao_deixa_arquivo_pela_metade(tmp_path):
    """Escrita atômica: configuração meio escrita é pior que configuração velha."""
    destino = tmp_path / "c.toml"
    gravar(Config(bases=(Base(id="a"),)), destino)
    gravar(Config(bases=(Base(id="b"),)), destino)

    assert carregar(destino, ambiente=SEM_AMBIENTE).base().id == "b"
    assert not list(tmp_path.glob("*.tmp"))


# --------------------------------------------------------------------------- #
# A configuração chega às linhas de comando


@pytest.fixture
def sem_env(monkeypatch):
    """O ambiente da máquina não pode decidir o resultado de um teste."""
    for chave in ("SEGUNDOCEREBRO_BASE", "SEGUNDOCEREBRO_CONFIG", "SEGUNDOCEREBRO_THREADS"):
        monkeypatch.delenv(chave, raising=False)


def test_indexador_recusa_base_ambigua(tmp_path, sem_env):
    """Indexar a base errada por cima da certa é caro de descobrir e de desfazer."""
    from segundocerebro.index.indexer import main

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[[base]]\nid = "a"\nindice = "ia"\n[[base]]\nid = "b"\nindice = "ib"\n', encoding="utf-8"
    )
    assert main(["--config", str(cfg)]) == 2


def test_indexador_recusa_base_inexistente(tmp_path, sem_env):
    from segundocerebro.index.indexer import main

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[base]]\nid = "a"\n', encoding="utf-8")
    assert main(["--config", str(cfg), "--base", "fantasma"]) == 2


def test_indexador_recusa_base_sem_raiz(tmp_path, sem_env):
    """Uma base só de leitura não tem o que indexar — e o erro diz isso."""
    from segundocerebro.index.indexer import main

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[base]]\nid = "a"\n', encoding="utf-8")
    assert main(["--config", str(cfg), "--base", "a"]) == 2


def test_eval_recusa_base_inexistente(tmp_path, sem_env):
    from eval.rodar import main

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[base]]\nid = "a"\n', encoding="utf-8")
    assert main(["--config", str(cfg), "--base", "fantasma"]) == 2


# --------------------------------------------------------------------------- #
# Exclusão por papel — padrão de nome com escopo de pasta
#
# A §6 de docs/colaboracao.md pedia que a exclusão por papel morasse na
# configuração da base, e não em código do indexador. Mora aqui. O escopo de
# pasta é o que a medição de 24/08/2026 exigiu (docs/ablacao-f4-meetings.md):
# glob solto casa pelo nome em qualquer lugar da raiz, e dois `*_relatorio.pdf`
# fora da árvore de reuniões seriam descartados em silêncio — um deles a única
# cópia da sua reunião.


def test_papel_chega_no_censo_com_escopo_de_pasta(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        raizes = [{ nome = "docs", caminho = 'C:\\Docs' }]

        [[base.exclude.papel]]
        dirs = ["Meetings", "09. Meetings"]
        globs = ["*_relatorio.pdf", "*_context.txt"]
        """,
    )
    censo = carregar(caminho, ambiente=SEM_AMBIENTE).base("a").censo()

    assert len(censo.role_exclusions) == 1
    assert censo.excluded_file("x_relatorio.pdf", "Meetings/reuniao-1")
    assert censo.excluded_file("x_relatorio.pdf", "09. Meetings/reuniao-1")
    assert not censo.excluded_file("x_relatorio.pdf", "02. Novos Negócios/Fibra")
    assert not censo.excluded_file("x_transcript.txt", "Meetings/reuniao-1")


def test_papel_aceita_tabela_em_linha(tmp_path):
    """As duas escritas do TOML descrevem a mesma coisa e têm de dar no mesmo."""
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [base.exclude]
        globs = ["*.bak"]
        papel = [{ dirs = ["Meetings"], globs = ["*_relatorio.pdf"] }]
        """,
    )
    base = carregar(caminho, ambiente=SEM_AMBIENTE).base("a")

    assert base.exclude_roles[0].dirs == ("Meetings",)
    assert base.exclude_roles[0].globs == ("*_relatorio.pdf",)
    assert "*.bak" in base.exclude_globs, "o glob solto continua valendo ao lado do papel"


def test_papel_do_padrao_e_herdado_pelas_bases(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[padrao.exclude.papel]]
        dirs = ["Meetings"]
        globs = ["*_context.txt"]

        [[base]]
        id = "a"

        [[base]]
        id = "b"
        [[base.exclude.papel]]
        globs = ["*.rascunho"]
        """,
    )
    cfg = carregar(caminho, ambiente=SEM_AMBIENTE)

    assert len(cfg.base("a").exclude_roles) == 1
    # a base soma à herança, não substitui — igual a dirs e globs
    assert len(cfg.base("b").exclude_roles) == 2


def test_papel_sem_globs_e_erro(tmp_path):
    """Regra que não exclui nada é pior que erro: parece proteção e não é."""
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [[base.exclude.papel]]
        dirs = ["Meetings"]
        """,
    )
    with pytest.raises(ErroDeConfig, match="globs"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_papel_recusa_chave_desconhecida(tmp_path):
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [[base.exclude.papel]]
        pastas = ["Meetings"]
        globs = ["*.pdf"]
        """,
    )
    with pytest.raises(ErroDeConfig, match="pastas"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_exclude_recusa_chave_desconhecida(tmp_path):
    """`papeis` em vez de `papel` seria ignorado em silêncio — e o corpus inteiro
    entraria na fila sem ninguém notar."""
    caminho = escrever(
        tmp_path,
        """
        [[base]]
        id = "a"
        [base.exclude]
        papeis = [{ globs = ["*.pdf"] }]
        """,
    )
    with pytest.raises(ErroDeConfig, match="papeis"):
        carregar(caminho, ambiente=SEM_AMBIENTE)


def test_gravar_preserva_papel(tmp_path):
    from segundocerebro.census import RoleExclusion

    destino = tmp_path / "config.toml"
    antes = Config(
        bases=(
            Base(
                id="a",
                exclude_roles=(
                    RoleExclusion(globs=("*_relatorio.pdf",), dirs=("Meetings",)),
                    RoleExclusion(globs=("*.rascunho",)),
                ),
            ),
        )
    )
    gravar(antes, destino)

    depois = carregar(destino, ambiente=SEM_AMBIENTE).base("a")
    assert depois.exclude_roles == antes.bases[0].exclude_roles
