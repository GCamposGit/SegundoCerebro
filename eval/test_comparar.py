"""A porta 5 é por caso, não por média — estes testes fixam o que "por caso" quer dizer."""

from __future__ import annotations

from eval.comparar import MAX_QUEDAS_DO_PRIMEIRO, comparar, render
from eval.harness import Pergunta, Resultado, ResultadoPergunta


def item(id_: str, posicao: int | None, *, armadilha: bool = False, tipo: str = "exato") -> ResultadoPergunta:
    return ResultadoPergunta(
        pergunta=Pergunta(id=id_, tipo=tipo, pergunta=f"pergunta {id_}", fontes=("a.pdf",), armadilha=armadilha),
        recuperados=[],
        posicao_primeiro_acerto=posicao,
        recall={1: 0.0, 10: 0.0},
        mrr=0.0,
        ndcg={5: 0.0, 10: 0.0},
    )


def resultado(nome: str, itens: list[ResultadoPergunta]) -> Resultado:
    return Resultado(retriever=nome, ks=(1, 10), itens=itens)


def test_detecta_melhora_piora_e_empate() -> None:
    antes = resultado("a", [item("g1", 5), item("g2", 1), item("g3", 3)])
    depois = resultado("b", [item("g1", 1), item("g2", 4), item("g3", 3)])

    movs = {m.id: m for m in comparar(antes, depois)}

    assert movs["g1"].melhorou and not movs["g1"].piorou
    assert movs["g2"].piorou and movs["g2"].caiu_do_primeiro
    assert not movs["g3"].melhorou and not movs["g3"].piorou


def test_nao_achado_conta_como_pior_que_qualquer_posicao() -> None:
    """`None` é pior que a posição 20; sem isso a comparação inverteria o sinal."""
    antes = resultado("a", [item("g1", 20), item("g2", None)])
    depois = resultado("b", [item("g1", None), item("g2", 20)])

    movs = {m.id: m for m in comparar(antes, depois)}

    assert movs["g1"].piorou and movs["g1"].perdeu_de_vez
    assert movs["g2"].melhorou and not movs["g2"].perdeu_de_vez


def test_regressao_em_armadilha_reprova_mesmo_com_tudo_o_mais_melhorando() -> None:
    """A porta diz "nenhuma regressão em caso crítico" — e crítico é armadilha."""
    antes = resultado("a", [item("g1", 5), item("g2", 5), item("g3", 1, armadilha=True)])
    depois = resultado("b", [item("g1", 1), item("g2", 1), item("g3", 4, armadilha=True)])

    texto = render(comparar(antes, depois), "a", "b", "")

    assert "**Porta 5: não passa.**" in texto
    assert "2 perguntas melhoraram, 1 pioraram" in texto


def test_orcamento_permite_troca_favoravel() -> None:
    """Melhorar trinta e piorar uma tem que passar — é a razão de a porta ser orçamento."""
    antes = resultado("a", [item(f"g{i}", 5) for i in range(30)] + [item("gx", 1)])
    depois = resultado("b", [item(f"g{i}", 1) for i in range(30)] + [item("gx", 2)])

    texto = render(comparar(antes, depois), "a", "b", "")

    assert "**Porta 5: passa.**" in texto


def test_estoura_o_orcamento_de_quedas_do_primeiro() -> None:
    n = MAX_QUEDAS_DO_PRIMEIRO + 1
    antes = resultado("a", [item(f"g{i}", 1) for i in range(n)])
    depois = resultado("b", [item(f"g{i}", 2) for i in range(n)])

    texto = render(comparar(antes, depois), "a", "b", "")

    assert "**Porta 5: não passa.**" in texto


def test_pergunta_ausente_de_um_dos_lados_e_ignorada() -> None:
    """Conjunto dourado que cresceu entre as duas execuções não pode inventar movimento."""
    antes = resultado("a", [item("g1", 1)])
    depois = resultado("b", [item("g1", 1), item("g2", 3)])

    assert [m.id for m in comparar(antes, depois)] == ["g1"]


# --- Δ pareado com IC95 — o pacote E5 -----------------------------------------


def item_metrico(id_: str, recall1: float, mrr: float, *, fontes: tuple[str, ...] = ("Contratos/a.pdf",)) -> ResultadoPergunta:
    return ResultadoPergunta(
        pergunta=Pergunta(id=id_, tipo="exato", pergunta=f"pergunta {id_}", fontes=fontes,
                          idioma="pt", idioma_fonte="pt"),
        recuperados=[],
        posicao_primeiro_acerto=1 if recall1 else None,
        recall={1: recall1, 10: 1.0},
        mrr=mrr,
        ndcg={5: 0.0, 10: 0.0},
    )


def par_de_resultados(antes_vals: list[float], depois_vals: list[float]) -> tuple[Resultado, Resultado]:
    a = Resultado("a", (1, 10), [item_metrico(f"g{i:03d}", v, v) for i, v in enumerate(antes_vals)])
    d = Resultado("b", (1, 10), [item_metrico(f"g{i:03d}", v, v) for i, v in enumerate(depois_vals)])
    return a, d


def test_a_tabela_de_delta_so_aparece_com_os_dois_resultados() -> None:
    """Quatro argumentos continuam valendo — a tabela é aditiva, como o F4-P.0."""
    a, d = par_de_resultados([0.0] * 40, [1.0] * 40)
    assert "Δ pareado" not in render(comparar(a, d), "a", "b", "")
    assert "Δ pareado" in render(comparar(a, d), "a", "b", "", antes=a, depois=d)


def test_ganho_consistente_grande_da_veredito_de_ganho() -> None:
    a, d = par_de_resultados([0.0] * 40, [1.0] * 40)
    texto = render(comparar(a, d), "a", "b", "", antes=a, depois=d)
    assert "+1.000 [+1.000, +1.000]" in texto
    assert "veredito **ganha**" in texto


def test_ganho_pequeno_em_n_pequeno_empata_e_nao_e_adotado() -> None:
    """O caso que motivou o pacote: média sobe, e o intervalo cruza zero."""
    antes = [0.0, 0.0] + [1.0, 0.0] * 5
    depois = [1.0, 0.0] + [1.0, 0.0] * 5
    a, d = par_de_resultados(antes, depois)
    texto = render(comparar(a, d), "a", "b", "", antes=a, depois=d)
    assert "veredito **empate**" in texto
    assert "não é adotada pelo agregado" in texto


def test_recorte_com_n_abaixo_do_piso_vai_marcado() -> None:
    a, d = par_de_resultados([0.0] * 12, [1.0] * 12)
    texto = render(comparar(a, d), "a", "b", "", antes=a, depois=d)
    assert "⚠" in texto, "n=12 está abaixo do piso de 30 e tem de aparecer marcado"


def test_pergunta_de_um_lado_so_nao_entra_no_pareado() -> None:
    """Braços de tamanhos diferentes seriam ValueError no bootstrap — `alinhar` evita."""
    a = Resultado("a", (1, 10), [item_metrico(f"g{i:03d}", 0.0, 0.0) for i in range(40)])
    d = Resultado("b", (1, 10), [item_metrico(f"g{i:03d}", 1.0, 1.0) for i in range(35)])
    texto = render(comparar(a, d), "a", "b", "", antes=a, depois=d)
    assert "com n=35" in texto, "o n reportado é o da interseção, não o do maior braço"


# --- o arremedo de Args entre comparar._montar e rodar._montar ----------------


def test_o_arremedo_de_args_cobre_tudo_que_rodar_montar_le() -> None:
    """A porta 5 não rodava desde o bloco A da F3.5, e nenhum teste pegou.

    `comparar._montar` monta uma classe `Args` à mão para reusar `rodar._montar`.
    Em 24/08/2026 faltavam quatro campos (`base_cfg`, `glossario`, `rerank`,
    `sem_rerank`) e qualquer recuperador que não fosse o baseline levantava
    `AttributeError`. Os testes acima montam `Resultado` direto e nunca passam
    por `_montar` — por isso ficaram verdes sobre uma ferramenta quebrada.

    Este teste lê o código-fonte de `rodar._montar` e exige que todo `args.X` que
    ele consome esteja declarado. A próxima fase que acrescentar um campo quebra
    aqui, que é barato, em vez de quebrar a porta, que não é."""
    import inspect
    import re

    from eval import rodar
    from eval.comparar import _CAMPOS_DE_MONTAGEM

    lidos = set(re.findall(r"args\.(\w+)", inspect.getsource(rodar._montar)))
    faltam = sorted(lidos - _CAMPOS_DE_MONTAGEM)
    assert not faltam, (
        f"rodar._montar lê args.{{{', '.join(faltam)}}} e comparar._montar não declara — "
        "eval.comparar vai levantar AttributeError fora do baseline"
    )


def test_a_classe_args_declara_o_que_o_contrato_promete() -> None:
    """E o contrato não pode virar uma lista que ninguém mantém."""
    import inspect
    import re

    from eval import comparar as mod

    fonte = inspect.getsource(mod._montar)
    declarados = set(re.findall(r"^\s{8}(\w+) =", fonte, re.M)) | set(
        re.findall(r"^\s{4}Args\.(\w+) =", fonte, re.M)
    )
    assert mod._CAMPOS_DE_MONTAGEM == declarados, (
        f"contrato e classe divergem: só no contrato {sorted(mod._CAMPOS_DE_MONTAGEM - declarados)}, "
        f"só na classe {sorted(declarados - mod._CAMPOS_DE_MONTAGEM)}"
    )


def test_entregue_envolve_os_dois_bracos() -> None:
    """`--entregue` na comparação, e nos dois lados.

    A `F4-P` muda `buscar_chunks`. Sem esta flag o Δ do `E5` e a porta 5 mediriam
    `search`, que é o caminho que a fase **não** toca — a mesma classe de erro que
    criou o `F4-P.0`, um nível acima. E envolver só um braço seria pior que não
    envolver nenhum: mediria a diferença entre os dois caminhos somada à mudança,
    e nenhum dos dois efeitos sairia identificável."""

    class Args:
        entregue = True
        base_cfg = None
        prefixo = None
        indice = None
        modelo = None
        threads = 1
        candidatos = None
        peso_denso = None
        peso_nome = None
        glossario = None
        rerank = None
        rerank_depois = None
        sem_rerank = True

    class Falso:
        nome = "falso"

        def buscar_chunks(self, consulta: str, k: int) -> list:
            return []

    import eval.comparar as mod
    import eval.rodar as rodar
    from eval.entregue import CaminhoEntregue

    montado = (Falso(), "t", "c", None, set())

    guardado = rodar._montar
    try:
        rodar._montar = lambda *a, **k: montado
        for papel in ("antes", "depois"):
            r, *_ = mod._montar("hibrido", Args(), None, papel)
            assert isinstance(r, CaminhoEntregue), f"braço `{papel}` ficou fora do caminho entregue"
    finally:
        rodar._montar = guardado
