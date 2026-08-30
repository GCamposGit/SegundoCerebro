"""A tabela `medicoes` — a lacuna estrutural que a v2 da estimativa fechou.

Antes dela o custo de indexar não era guardado em lugar nenhum: `documentos` tem
tamanho, n_chunks, páginas, digitalizado — e nenhuma coluna de tempo. Sem isto o
passo "recalibrar sobre histórico" não tem de onde ler.

Estes testes existem porque os três métodos aqui estavam cobertos **apenas** de
forma indireta, por execuções de ponta a ponta. Dois deles falham em silêncio:
`gravar_medicao` é chamado dentro de um `try/except` no indexador (medir não pode
derrubar indexar) e `podar_medicoes` usa função de janela do SQLite. Uma poda
quebrada não apareceria em nenhum lugar — só num arquivo crescendo sem limite.
"""

from __future__ import annotations

import pytest

from segundocerebro.index.estimativa import Observacao
from segundocerebro.index.store import Store

from tests.falsos import DIM


def _obs(rel: str, tipo: str = "txt", **kw) -> Observacao:
    campos = dict(
        rel=rel,
        tipo=tipo,
        mb=0.05,
        n_chunks=3,
        tokens=360,
        s_parse=0.01,
        s_chunk=0.002,
        s_embed=0.9,
        s_grava=0.04,
        s_total_ativo=0.952,
        perfil="normal",
        situacao="novo",
        status="ok",
    )
    campos.update(kw)
    return Observacao(**campos)


def test_medicao_guarda_etapas_e_procedencia(tmp_path):
    """Invariante 5 do projeto: todo registro carrega procedência."""
    store = Store(tmp_path / "i", DIM)
    store.gravar_medicao(
        _obs("a/b.txt"), execucao=7, fingerprint="fp123", model_id="e5-large:1024"
    )
    store.commit()

    linha = store.con.execute(
        "SELECT path, tipo, mb, n_chunks, tokens, s_parse, s_chunk, s_embed,"
        " s_grava, s_total_ativo, suspeito, perfil, fingerprint, model_id,"
        " situacao, status, execucao, quando FROM medicoes"
    ).fetchone()
    assert linha["path"] == "a/b.txt"
    assert linha["tipo"] == "txt"
    assert linha["s_embed"] == pytest.approx(0.9)
    assert linha["s_grava"] == pytest.approx(0.04)
    assert linha["suspeito"] == 0
    assert linha["execucao"] == 7
    assert linha["fingerprint"] == "fp123"
    assert linha["model_id"] == "e5-large:1024"
    assert linha["quando"], "sem data a linha não serve para auditar nada"


def test_etapa_nao_medida_fica_nula_e_nao_zero(tmp_path):
    """Zero e "não medi" são coisas diferentes.

    Um documento que tomou o atalho de sha256 nunca chegou ao encoder: gravar
    `s_embed = 0` diria que o encoder rodou instantaneamente, e a calibragem
    aprenderia que embeddar é grátis.
    """
    store = Store(tmp_path / "i", DIM)
    store.gravar_medicao(_obs("a/c.txt", s_embed=None, situacao="revalidado"))
    store.commit()
    linha = store.con.execute("SELECT s_embed, situacao FROM medicoes").fetchone()
    assert linha["s_embed"] is None
    assert linha["situacao"] == "revalidado"


def test_documento_com_relogio_suspeito_fica_marcado_e_guardado(tmp_path):
    """Guardar e marcar é melhor que descartar na origem: a linha ainda serve
    para auditar por que a calibragem ignorou aquela passada."""
    store = Store(tmp_path / "i", DIM)
    store.gravar_medicao(_obs("a/d.txt", suspeito=True, s_total_ativo=9000.0))
    store.commit()
    linha = store.con.execute("SELECT suspeito, s_total_ativo FROM medicoes").fetchone()
    assert linha["suspeito"] == 1
    assert linha["s_total_ativo"] == pytest.approx(9000.0)


def test_poda_mantem_as_recentes_de_cada_tipo(tmp_path):
    """`medicoes` cresce junto com `documentos`, e para sempre sem poda.

    O reservatório é por **tipo**, não global: um acervo com 3.000 `.txt` e 4
    `.csv` não pode perder os CSVs — são justamente os caros, e os que mais
    ensinam.
    """
    store = Store(tmp_path / "i", DIM)
    for i in range(30):
        store.gravar_medicao(_obs(f"t/{i}.txt", tipo="txt"))
    for i in range(4):
        store.gravar_medicao(_obs(f"c/{i}.csv", tipo="csv"))
    store.commit()

    removidas = store.podar_medicoes(por_tipo=10)
    store.commit()

    assert removidas == 20
    por_tipo = dict(
        store.con.execute("SELECT tipo, count(*) FROM medicoes GROUP BY tipo")
    )
    assert por_tipo == {"txt": 10, "csv": 4}
    # as mantidas são as **últimas**
    restantes = [
        r[0] for r in store.con.execute(
            "SELECT path FROM medicoes WHERE tipo='txt' ORDER BY id"
        )
    ]
    assert restantes[0] == "t/20.txt"
    assert restantes[-1] == "t/29.txt"


def test_poda_nao_falha_em_tabela_vazia(tmp_path):
    store = Store(tmp_path / "i", DIM)
    assert store.podar_medicoes(por_tipo=10) == 0


def test_estados_devolve_o_registro_inteiro_de_uma_vez(tmp_path):
    """O mapa restante é derivado por diferença a cada ciclo. Fazer isso com
    uma consulta por arquivo transformaria a derivação no gargalo que ela
    existe para evitar."""
    store = Store(tmp_path / "i", DIM)
    for i in range(5):
        store.registrar_documento(
            path=f"p/{i}.txt",
            raiz="r",
            tamanho=1000 + i,
            mtime=100.0 + i,
            sha256="a" * 64,
            status="ok",
            n_chunks=i,
            model_id="m",
            chunker="1",
            parser="1",
        )
    store.commit()

    estados = store.estados()
    assert len(estados) == 5
    assert estados["p/3.txt"].tamanho == 1003
    assert estados["p/3.txt"].mtime == pytest.approx(103.0)
    assert estados["p/3.txt"].n_chunks == 3
    assert store.estados() == store.estados()


def test_medicoes_existe_em_indice_criado_antes_da_v2(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` no script de esquema é a migração.

    Um índice de horas de trabalho não pode precisar de reconstrução para ganhar
    uma tabela nova — e o modo de falha, se faltasse, seria um `INSERT` falhando
    no meio de uma passada.
    """
    destino = tmp_path / "antigo"
    store = Store(destino, DIM)
    store.con.execute("DROP TABLE medicoes")
    store.commit()
    store.fechar()

    reaberto = Store(destino, DIM)
    reaberto.gravar_medicao(_obs("x/y.txt"))
    reaberto.commit()
    assert reaberto.con.execute("SELECT count(*) FROM medicoes").fetchone()[0] == 1
