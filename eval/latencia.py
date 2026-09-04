"""Latência das operações do servidor MCP, e a porta que impede regressão — R9.3.

"Rápido, para não ficar perdido em buscas enormes" é requisito do usuário desde
o começo, e até 24/08/2026 nenhuma porta o media. A lição da truncagem
silenciosa aplicada a tempo: o que não tem número antes e depois regride sem
ninguém ver, e latência regride mais fácil que recall porque nenhum teste falha.

**Duas portas, não uma, e é a correção que a medição faz no `R9.3` original.**

- **porta de produto** — orçamento da operação completa no cenário de
  referência. Não reparte o tempo em metas arbitrárias para BM25, ANN ou
  encoder; existe para dizer se a experiência entregue ainda cabe.
- **piso de regressão** — o que esta máquina faz hoje, mais margem medida. É a
  porta que **vale agora**, e a única que pode falhar por culpa de alguém.

**Número sem máquina é mentira**, do mesmo jeito que número sem corpus é
(`docs/colaboracao.md` §4, regra 7). 1.418 ms num i7-1355U de 15 W não diz nada
sobre o desktop, e um piso de regressão medido lá reprovaria aqui todo dia. Por
isso o piso é **por máquina nomeada**, e `--porta` exige dizer qual.
"""

from __future__ import annotations

import os
import platform
import statistics
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORTAS = REPO / "eval" / "portas-latencia.toml"

AQUECIMENTO = 3
"""Consultas descartadas antes de medir.

O `e5-large` abre na primeira consulta e leva ~80 s. Sem descarte ele entraria
na amostra como um outlier que domina o p95 e some do p50 — o pior dos dois
mundos, porque o número fica alto e a causa fica invisível. Três e não uma
porque o cache do SQLite e o `lancedb` também esquentam."""

RODADAS = 3
"""Quantas vezes o conjunto de consultas roda.

A dispersão que interessa é **entre consultas** — a pergunta lenta, não a
rodada lenta. Repetir o conjunto inteiro em vez de repetir cada consulta em
sequência é o que impede o cache de responder à segunda medição da mesma
consulta e achatar a cauda."""

K_PADRAO = 10
JANELA_PADRAO = 2
LIMITE_VIZINHOS = 10

OPERACOES = ("search", "search+rerank", "read_note", "neighbors")
"""O que existe para medir hoje.

`overview` está no `R9.3` com porta de 200 ms e **não existe** — é `R7.1`, onda
7. Um harness que medisse zero e reportasse "dentro da porta" para uma
ferramenta ausente seria pior que a ausência dela."""

COMPONENTES_SEARCH = ("encoder", "denso", "bm25", "nome", "fusão+hidratação")
"""Partes do braço `search`, medidas dentro da chamada entregue.

O último item é residual por consulta: RRF, ordenação, leitura dos chunks,
colapso de famílias e montagem da resposta. Separá-lo por subtração mantém a
instrumentação aditiva — o relatório mede a mesma chamada que a porta, não uma
segunda implementação parecida com ela.
"""


def percentil(valores, p: float) -> float:  # noqa: ANN001
    """Percentil por posto mais próximo (*nearest-rank*), 1-indexado.

    Escolhido em vez do interpolado porque **o valor devolvido é uma medição que
    aconteceu**, e não a média de duas. Numa amostra de 62 consultas a diferença
    é de décimos de milissegundo; a diferença que importa é poder dizer "esta
    consulta levou isto" quando alguém for investigar a cauda.
    """
    ordenados = sorted(valores)
    if not ordenados:
        return 0.0
    posto = max(1, -(-int(round(p * len(ordenados) * 100)) // 100))
    return ordenados[min(posto, len(ordenados)) - 1]


@dataclass(frozen=True)
class Amostra:
    operacao: str
    ms: tuple[float, ...]

    @property
    def n(self) -> int:
        return len(self.ms)

    @property
    def p50(self) -> float:
        return percentil(self.ms, 0.50)

    @property
    def p95(self) -> float:
        return percentil(self.ms, 0.95)

    @property
    def p99(self) -> float:
        return percentil(self.ms, 0.99)

    @property
    def minimo(self) -> float:
        return min(self.ms) if self.ms else 0.0

    @property
    def maximo(self) -> float:
        return max(self.ms) if self.ms else 0.0

    @property
    def desvio(self) -> float:
        """Desvio-padrão, que é o que dimensiona a margem do piso de regressão.

        Sem ele a margem seria chutada, e margem chutada tem dois modos de falha
        simétricos: apertada demais pisca vermelho por ruído térmico até alguém
        desligar a porta, e larga demais deixa passar a regressão que ela
        existe para pegar."""
        return statistics.stdev(self.ms) if len(self.ms) > 1 else 0.0


@dataclass(frozen=True)
class Ambiente:
    """O que precisa estar no relatório para o número significar alguma coisa."""

    maquina: str
    processador: str
    nucleos: int
    documentos: int
    chunks: int
    modelo: str
    threads: int

    def linha(self) -> str:
        return (
            f"`{self.maquina}` · {self.processador} · {self.nucleos} fios "
            f"({self.threads} para a busca) · índice de {self.chunks} trechos "
            f"em {self.documentos} documentos · `{self.modelo}`"
        )


@dataclass(frozen=True)
class Violacao:
    operacao: str
    medido: float
    porta: float
    especie: str
    """`produto` (o alvo, informativo) ou `regressao` (esta máquina piorou)."""

    @property
    def fator(self) -> float:
        return self.medido / self.porta if self.porta else 0.0


def carregar_portas(caminho: Path = PORTAS) -> dict:
    if not caminho.exists():
        return {}
    return tomllib.loads(caminho.read_text(encoding="utf-8"))


def limites_de(secao: dict) -> dict:
    """Os limites de uma seção de portas — a subtabela `p95`, e só ela.

    A descrição da máquina mora no nível de cima justamente para não se
    confundir com limite: `indice_chunks = 98326` no mesmo nível seria
    indistinguível de uma porta de 98 segundos para uma operação chamada
    `indice_chunks`, que nunca dispararia e pareceria cobertura.
    """
    p95 = secao.get("p95", {})
    return {k: v for k, v in p95.items() if isinstance(v, (int, float))}


def conferir(amostras, portas: dict, maquina: str = "") -> list[Violacao]:  # noqa: ANN001
    """As duas portas, marcadas por espécie.

    `produto` sai como violação mesmo sendo esperada hoje: o relatório tem que
    dizer quanto falta, e "quanto falta" some se a linha desaparece quando
    reprova. Quem decide o código de saída é `main`, e só `regressao` o move.
    """
    violacoes: list[Violacao] = []
    por_operacao = {a.operacao: a for a in amostras}
    for especie, tabela in (
        ("produto", limites_de(portas.get("produto", {}))),
        ("regressao", limites_de(portas.get("regressao", {}).get(maquina, {}) if maquina else {})),
    ):
        for operacao, limite in tabela.items():
            amostra = por_operacao.get(operacao)
            if amostra is None or not isinstance(limite, (int, float)):
                continue
            if amostra.p95 > limite:
                violacoes.append(Violacao(operacao, amostra.p95, float(limite), especie))
    return violacoes


# --- medição ----------------------------------------------------------------


def _cronometrar(chamada) -> float:  # noqa: ANN001
    """Milissegundos de uma chamada. `perf_counter` porque é monotônico e fino."""
    comecou = time.perf_counter()
    chamada()
    return (time.perf_counter() - comecou) * 1000.0


class _DecompositorSearch:
    """Cronometra componentes sem trocar o caminho executado por `buscar_chunks`.

    Os wrappers vivem apenas durante a medição e chamam os métodos originais.
    Medir cada componente em chamadas separadas aqueceria caches diferentes e
    repetiria o defeito que fez o primeiro R9.3 rotular outro braço de `search`.
    """

    def __init__(self, busca, *, relogio=time.perf_counter) -> None:  # noqa: ANN001
        self.busca = busca
        self.relogio = relogio
        self._atual: dict[str, float] | None = None
        self._valores: dict[str, list[float]] = {nome: [] for nome in COMPONENTES_SEARCH}
        self._restauracoes: list[tuple[object, str, bool, object | None]] = []

    def _envolver(self, objeto: object, atributo: str, componente: str) -> None:
        original = getattr(objeto, atributo)
        tinha_proprio = hasattr(objeto, "__dict__") and atributo in vars(objeto)
        proprio = vars(objeto).get(atributo) if hasattr(objeto, "__dict__") else None
        self._restauracoes.append((objeto, atributo, tinha_proprio, proprio))

        def cronometrado(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            comecou = self.relogio()
            try:
                return original(*args, **kwargs)
            finally:
                if self._atual is not None:
                    gasto = (self.relogio() - comecou) * 1000.0
                    self._atual[componente] = self._atual.get(componente, 0.0) + gasto

        setattr(objeto, atributo, cronometrado)

    def __enter__(self) -> "_DecompositorSearch":
        self._envolver(self.busca.embedder, "embed_consulta", "encoder")
        self._envolver(self.busca.store, "buscar_denso", "denso")
        self._envolver(self.busca.store, "buscar_lexical", "bm25")
        self._envolver(self.busca, "_nome_por_chunk", "nome")
        return self

    def __exit__(self, *_exc) -> None:  # noqa: ANN002
        for objeto, atributo, tinha_proprio, proprio in reversed(self._restauracoes):
            if tinha_proprio:
                setattr(objeto, atributo, proprio)
            else:
                delattr(objeto, atributo)
        self._restauracoes.clear()
        self._atual = None

    def iniciar(self) -> None:
        if self._atual is not None:
            raise RuntimeError("decomposição de search já iniciada")
        self._atual = {}

    def encerrar(self, total_ms: float) -> None:
        if self._atual is None:
            raise RuntimeError("decomposição de search não iniciada")
        for nome in COMPONENTES_SEARCH[:-1]:
            if nome in self._atual:
                self._valores[nome].append(self._atual[nome])
        medido = sum(self._atual.values())
        self._valores["fusão+hidratação"].append(max(0.0, total_ms - medido))
        self._atual = None

    def amostras(self) -> tuple[Amostra, ...]:
        return tuple(
            Amostra(nome, tuple(self._valores[nome]))
            for nome in COMPONENTES_SEARCH
            if self._valores[nome]
        )


@dataclass(frozen=True)
class Medicao:
    """As amostras e o que mais precisa ser dito sobre elas para não enganarem."""

    amostras: tuple[Amostra, ...]
    rodadas: int
    braco: str = "search"
    """Qual braço de busca esta passada mediu. Um por passada, ver `medir`."""
    componentes_search: tuple[Amostra, ...] = ()
    vizinhos_vazios: int = 0
    vizinhos_medidos: int = 0

    @property
    def vizinhos_uteis(self) -> int:
        return self.vizinhos_medidos - self.vizinhos_vazios

    def deriva(self) -> list[float]:
        """p50 do braço de busca em cada rodada, na ordem em que rodaram.

        Existe porque a maior fonte de variação desta medição não é a consulta
        nem o índice: é o **estado térmico da máquina**. O mesmo código, no
        mesmo índice, mediu p95 de 1 916 ms com o notebook frio e 2 877 ms
        depois de minutos de reranking — 1,5x, sem uma linha mudar.

        Uma p50 agregada esconde isso inteiro. Três p50 em ordem crescente
        mostram o processador descendo de frequência enquanto a medição corre, e
        é a diferença entre "o código piorou" e "a máquina esquentou" — que uma
        porta de latência não pode confundir.
        """
        do_braco = next((a for a in self.amostras if a.operacao == self.braco), None)
        if do_braco is None or self.rodadas < 2:
            return []
        por_rodada = len(do_braco.ms) // self.rodadas
        if por_rodada < 2:
            return []
        return [
            percentil(do_braco.ms[i * por_rodada : (i + 1) * por_rodada], 0.50)
            for i in range(self.rodadas)
        ]


def medir(  # noqa: ANN001
    recursos,
    consultas,
    *,
    rodadas: int = RODADAS,
    busca=None,
    rotulo: str = "search",
    decompor_search: bool = False,
) -> Medicao:
    """Mede as operações sobre as consultas do conjunto dourado.

    As consultas são as **reais**, e não strings sintéticas, porque a cauda de
    latência deste sistema é de consulta e não de rodada: uma pergunta com sigla
    rara casa pouco no bm25 e muito no denso, e o custo não é o mesmo. Uma
    string inventada mediria a máquina, não o uso.

    `read_note` e `neighbors` recebem ids e caminhos vindos do `search` da mesma
    consulta — que é a sequência que um cliente MCP realmente faz. Sortear um id
    do índice mediria um cache frio que o uso real não paga.

`busca` é **passada**, não deduzida da base. A primeira versão media
    `recursos.busca` e a chamava de "search": como a base corporativa configura
    reranking, o braço rotulado "sem rerank" saiu 6,6× mais lento que a linha de
    base do ROADMAP e o rótulo mentia. Rótulo de braço tem que descrever o
    braço, não o que a configuração calhou de ter.

    **Um braço por passada, e isso é medição e não arrumação.** A versão que
    media os dois no mesmo laço deu `search` a 4.394 ms; medido sozinho, o mesmo
    braço no mesmo índice dá 2.877 ms. São 53% de diferença, e a causa é o
    cross-encoder: num CPU de 15 W ele satura o pacote térmico e o braço barato
    paga a conta do caro. Instrumento cujo braço barato depende de qual outro
    braço rodou junto não mede nada — e o pior é que o número contaminado é
    plausível, então passaria.
    """
    busca = busca if busca is not None else recursos.busca
    store = recursos.store
    from segundocerebro.retrieve.grafo import vizinhos as andar_no_grafo

    # O aquecimento roda o mesmo braço que será medido. Importa mais no braço
    # com reranker: o cross-encoder abre na primeira consulta e leva ~6 s, que
    # entraria como outlier no máximo e no desvio sem mover a mediana — e por
    # isso passaria despercebido.
    for consulta in consultas[:AQUECIMENTO]:
        busca.buscar_chunks(consulta, K_PADRAO)

    tempos: dict[str, list[float]] = {op: [] for op in OPERACOES}
    tem_grafo = bool(store.paths_com_mencoes())
    vizinhos_vazios = vizinhos_medidos = 0

    decompositor = _DecompositorSearch(busca) if decompor_search else None
    if decompositor is not None:
        decompositor.__enter__()
    try:
        for _ in range(rodadas):
            for consulta in consultas:
                # Cronometrado à mão em vez de por `_cronometrar`, porque aqui o
                # resultado é insumo das duas medições seguintes.
                if decompositor is not None:
                    decompositor.iniciar()
                comecou = time.perf_counter()
                acertos = busca.buscar_chunks(consulta, K_PADRAO)
                total_ms = (time.perf_counter() - comecou) * 1000.0
                tempos[rotulo].append(total_ms)
                if decompositor is not None:
                    decompositor.encerrar(total_ms)
                if not acertos:
                    continue

                alvo = acertos[0]
                # As duas chamadas, na ordem em que `mcp.server.read_note` as faz:
                # ele resolve o trecho e só então busca os vizinhos. Medir só a
                # segunda omitiria uma consulta ao SQLite — pequena, mas a porta
                # existe para descrever a ferramenta, não uma aproximação dela.
                def um_read_note(a=alvo) -> None:
                    store.chunk(a.chunk_id)
                    store.vizinhos(a.chunk_id, JANELA_PADRAO)

                tempos["read_note"].append(_cronometrar(um_read_note))
                if tem_grafo:
                    # Conta os vazios porque `neighbors` rápido e `neighbors` que não
                    # devolve nada são a mesma medição vista de fora — e a segunda
                    # não é uma porta cumprida, é uma porta sem assunto.
                    comecou = time.perf_counter()
                    ligados = andar_no_grafo(store, alvo.path, limite=LIMITE_VIZINHOS)
                    tempos["neighbors"].append((time.perf_counter() - comecou) * 1000.0)
                    vizinhos_medidos += 1
                    vizinhos_vazios += not ligados
    finally:
        if decompositor is not None:
            decompositor.__exit__(None, None, None)

    return Medicao(
        amostras=tuple(Amostra(op, tuple(tempos[op])) for op in OPERACOES if tempos[op]),
        rodadas=rodadas,
        braco=rotulo,
        componentes_search=decompositor.amostras() if decompositor is not None else (),
        vizinhos_vazios=vizinhos_vazios,
        vizinhos_medidos=vizinhos_medidos,
    )


# --- relatório --------------------------------------------------------------


def num(valor: float, casas: int | None = None) -> str:
    """Milissegundos legiveis, com separador de milhar em espaco.

    Espaco e nao ponto porque `1.145 ms` e ambiguo em portugues: le-se tanto
    como 1,145 ms quanto como 1145 ms, e o `ROADMAP.md` tem as duas leituras
    possiveis no mesmo paragrafo. `1 145 ms` nao tem como ser lido errado.

    Espaco **comum**, e nao U+00A0. O inquebravel e a tipografia certa para
    separador de milhar e foi o que entrou aqui por acidente na primeira
    versao; o custo dele e que `grep "2 877"` no relatorio nao acha nada, e
    relatorio que nao se procura por texto nao se confere.

    A casa decimal aparece sozinha abaixo de 10 ms. `read_note` roda em fracoes
    de milissegundo, e arredondar para `0 ms` faz a operacao parecer gratis
    quando o que houve foi a coluna nao ter resolucao para ela.
    """
    if casas is None:
        casas = 1 if abs(valor) < 10 else 0
    return f"{valor:,.{casas}f}".replace(",", " ").replace(".", ",")


def render(  # noqa: ANN001
    medicao: Medicao, ambiente: Ambiente, violacoes, portas: dict, maquina: str, candidatos: int = 0
) -> str:
    amostras = medicao.amostras
    quantos = f", com {candidatos} candidatos" if candidatos else ""
    linhas: list[str] = [
        "# Latência — porta de fase (R9.3)",
        "",
        ambiente.linha() + ".",
        "",
        # `medicao.rodadas` e não a constante do módulo: a primeira versão
        # imprimia "3 rodadas" numa passada de 1. Número de configuração que
        # aparece no relatório tem que ser o que foi para a medição, ou o
        # documento mente sobre o experimento que descreve — a mesma armadilha
        # dos "None candidatos" de 16/08 em `eval.rodar`.
        f"Consultas do conjunto dourado, {medicao.rodadas} rodada(s), {AQUECIMENTO} de aquecimento",
        "descartadas. Percentil por posto mais próximo — o valor é uma medição que",
        "aconteceu, não a média de duas.",
        "",
        f"Braço medido nesta passada: **`{medicao.braco}`**{quantos}. **Um por passada.**",
        "Medir os dois no mesmo laço dava `search` a 4 394 ms; sozinho, o mesmo braço no",
        "mesmo índice dá 2 877 ms — 53% de diferença, porque num CPU de 15 W o",
        "cross-encoder satura o pacote térmico e o braço barato paga a conta do caro.",
        "",
        "O braço é construído aqui, não herdado da base: o rótulo descreve o braço.",
        "",
        "Mede a **recuperação**, não a serialização JSON-RPC do MCP: é a camada que",
        "mudança de ranking move, e a que as portas existem para guardar.",
        "",
        # p99 fora da tabela: com n=186 o posto 99 é o penúltimo maior, ou seja
        # uma amostra só. Publicar isso como percentil sugere uma estabilidade
        # que a medição não tem; `máx` diz a mesma coisa sem fingir.
        "| Operação | n | p50 | p95 | mín | máx | desvio |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for a in amostras:
        linhas.append(
            f"| `{a.operacao}` | {a.n} | {num(a.p50)} ms | **{num(a.p95)} ms** "
            f"| {num(a.minimo)} ms | {num(a.maximo)} ms | {num(a.desvio)} ms |"
        )
    if medicao.componentes_search:
        linhas += [
            "",
            "## Decomposição de `search`",
            "",
            "Os componentes são cronômetros dentro da mesma chamada acima; não são braços",
            "executados à parte. `fusão+hidratação` é o residual por consulta: RRF, ordenação,",
            "leitura dos chunks, colapso de famílias e montagem da resposta.",
            "",
            "| Componente | n | p50 | p95 |",
            "|---|---:|---:|---:|",
        ]
        for componente in medicao.componentes_search:
            linhas.append(
                f"| `{componente.operacao}` | {componente.n} | {num(componente.p50)} ms "
                f"| **{num(componente.p95)} ms** |"
            )
        linhas += [
            "",
            "Percentis de componentes não são aditivos: a consulta que ocupa o p95 de um",
            "componente pode não ser a que ocupa o p95 do total.",
        ]
    deriva = medicao.deriva()
    if deriva:
        sequencia = " → ".join(f"{num(v)} ms" for v in deriva)
        amplitude = (max(deriva) / min(deriva) - 1) * 100 if min(deriva) else 0.0
        linhas += [
            "",
            f"p50 por rodada, na ordem: **{sequencia}** — amplitude de {amplitude:.0f}%.",
            "",
            "A série existe porque a maior fonte de variação desta medição não é a consulta",
            "nem o índice: é o **estado térmico da máquina**. Medido em 24/08/2026, mesmo",
            "código e mesmo índice, a p95 de `search` foi de 1 840 ms com o notebook",
            "descansado a 2 877 ms logo depois de minutos de reranking — 1,6x, sem uma linha",
            "mudar. Uma p50 agregada esconde isso inteiro.",
            "",
            "Amplitude pequena aqui **não** quer dizer medição estável: quer dizer que o",
            "regime não mudou *durante* esta passada. O que muda entre passadas é o que",
            "rodou antes delas — e é por isso que o piso de regressão desta máquina fica na",
            "ponta quente, para não piscar vermelho por causa do ventilador.",
        ]
    if medicao.vizinhos_medidos:
        linhas += [
            "",
            f"`neighbors` devolveu documento ligado em **{medicao.vizinhos_uteis} de "
            f"{medicao.vizinhos_medidos}** chamadas. O resto voltou vazio, que é o caso "
            "honesto e comum — mas conta, porque chamada que não devolve nada é rápida "
            "por não ter assunto, e inflaria a aprovação da porta.",
        ]
    linhas += ["", "## As duas portas", ""]

    produto = limites_de(portas.get("produto", {}))
    piso = limites_de(portas.get("regressao", {}).get(maquina, {}) if maquina else {})
    if not produto and not piso:
        linhas += [
            "Nenhuma porta declarada para esta máquina em `eval/portas-latencia.toml`.",
            "",
        ]
        return "\n".join(linhas)

    linhas += [
        "`produto` é o orçamento da operação completa no cenário de referência; não",
        "reparte tempo entre componentes. `regressão` é o que **esta** máquina fazia quando o",
        "piso foi medido, mais margem: é a porta que pode falhar por culpa de alguém.",
        "",
        f"| Operação | p95 medido | porta de produto | piso de regressão (`{maquina or '—'}`) |",
        "|---|---:|---:|---:|",
    ]
    for a in amostras:
        alvo = produto.get(a.operacao)
        chao = piso.get(a.operacao)
        marca_alvo = "—" if alvo is None else f"{num(float(alvo))} ms ({a.p95 / alvo:.1f}×)"
        if chao is None:
            marca_chao = "—"
        else:
            marca_chao = f"{num(float(chao))} ms" + (" ❌" if a.p95 > chao else " ✅")
        linhas.append(f"| `{a.operacao}` | {num(a.p95)} ms | {marca_alvo} | {marca_chao} |")

    quebras = [v for v in violacoes if v.especie == "regressao"]
    linhas += [""]
    if quebras:
        linhas += [
            f"**{len(quebras)} piso(s) de regressão rompido(s).** Isto é falha, não aviso:",
            "a máquina é a mesma e ficou mais lenta.",
            "",
        ]
        for v in quebras:
            linhas.append(f"- `{v.operacao}`: {num(v.medido)} ms contra {num(v.porta)} ms ({v.fator:.2f}×)")
        linhas.append("")
    else:
        linhas += ["Nenhum piso de regressão rompido.", ""]
    return "\n".join(linhas)


# --- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    """Mede a latência das operações e confere as portas.

        py -m eval.latencia --base padrao --maquina notebook-15w
        py -m eval.latencia --base padrao --maquina notebook-15w --porta
    """
    import argparse
    
    from segundocerebro.config import ErroDeConfig, carregar
    from segundocerebro.logger import get_logger

    from .harness import GOLDEN, carregar_perguntas, entregar, resolver_dourado

    log = get_logger("eval.latencia")

    parser = argparse.ArgumentParser(
        prog="eval.latencia", description="Latência de search/read_note/neighbors, e as portas de R9.3"
    )
    parser.add_argument("--base", help="qual base medir")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--golden", type=Path, help="sobrepõe o conjunto dourado da base")
    parser.add_argument("--maquina", default="", help="nome do piso de regressão em portas-latencia.toml")
    parser.add_argument("--rodadas", type=int, default=RODADAS)
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="mede o braço COM reranking em vez do braço sem. Um braço por passada: "
        "medir os dois no mesmo laço contamina o barato em 53%% nesta máquina",
    )
    parser.add_argument(
        "--decompor-search",
        action="store_true",
        help="mede encoder, denso, bm25, nome e fusão+hidratação dentro do braço search",
    )
    parser.add_argument(
        "--candidatos",
        type=int,
        help="quantos candidatos o reranker reavalia — é o botão de latência dele. "
        "O padrão é o que a base serve",
    )
    parser.add_argument(
        "--porta",
        action="store_true",
        help="sai com código 1 se um piso de regressão for rompido; exige --maquina",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.porta and not args.maquina:
        # Piso sem máquina não é porta, é número solto: o mesmo p95 aprova num
        # desktop e reprova num notebook de 15 W. `--porta` sem `--maquina`
        # produziria um verde ou um vermelho que não significa nada.
        log.error("--porta exige --maquina: piso de regressão é por máquina, não absoluto")
        return 2
    if args.decompor_search and args.rerank:
        log.error("--decompor-search mede o braço search sem reranking; rode um braço por passada")
        return 2

    try:
        conf = carregar(args.config, raiz=REPO)
        base = conf.base(args.base)
    except ErroDeConfig as erro:
        log.error("%s", erro)
        return 2

    implicito = args.golden is None and base.dourado is None
    try:
        dourado, aviso = resolver_dourado(args.golden or base.dourado or GOLDEN, implicito=implicito)
    except FileNotFoundError as erro:
        log.error("%s", erro)
        return 2
    if aviso:
        log.warning("%s", aviso)
    consultas = [p.pergunta for p in carregar_perguntas(dourado)]

    from segundocerebro.index.store import IndiceEmEscrita, recusar_se_indexando
    from segundocerebro.mcp.server import Recursos
    from segundocerebro.retrieve.hybrid import BuscaHibrida

    try:
        recusar_se_indexando(Path(base.indice))
    except IndiceEmEscrita as erro:
        log.error("%s", erro)
        return 4

    # `Recursos` e não uma montagem própria: é o que o servidor MCP usa, e medir
    # outra coisa produziria um número que descreve o eval em vez do produto.
    recursos = Recursos(indice=Path(base.indice), modelo=base.modelo, threads=args.threads, base=base)

    # O braço é **construído**, não herdado: `de_base` traz o reranker que a base
    # configura, e foi assim que a primeira passada rotulou de `search` um braço
    # reranqueado, 6,6x mais lento que a linha de base do ROADMAP.
    embedder = recursos.busca.embedder
    braco = BuscaHibrida.de_base(recursos.store, embedder, base)
    rotulo = "search"
    candidatos_rerank = 0

    if args.rerank:
        from segundocerebro.retrieve.rerank import CANDIDATOS_PARA_RERANK, Reranker

        peso = getattr(base.busca, "rerank", 0.0) or 0.25
        # O padrão é o que **a base** configura, não a constante do módulo. A
        # base corporativa serve 10 candidatos e a constante é 25: usar a
        # constante mediria um reranker 2,5x mais caro que o do servidor, e o
        # piso de regressão sairia alto o bastante para nunca disparar.
        candidatos_rerank = (
            args.candidatos or getattr(base.busca, "rerank_candidatos", 0) or CANDIDATOS_PARA_RERANK
        )
        braco.reranker = Reranker(candidatos=candidatos_rerank, peso=peso, threads=args.threads)
        rotulo = "search+rerank"
    else:
        braco.reranker = None

    estat = recursos.store.estatisticas()
    try:
        medicao = medir(
            recursos,
            consultas,
            rodadas=args.rodadas,
            busca=braco,
            rotulo=rotulo,
            decompor_search=args.decompor_search,
        )
    finally:
        recursos.store.fechar()

    ambiente = Ambiente(
        maquina=args.maquina or "não declarada",
        processador=platform.processor() or platform.machine(),
        nucleos=os.cpu_count() or 0,
        documentos=int(estat["documentos"]),
        chunks=int(estat["chunks"]),
        modelo=base.modelo,
        threads=args.threads,
    )
    portas = carregar_portas()
    violacoes = conferir(medicao.amostras, portas, args.maquina)
    relatorio = render(
        medicao, ambiente, violacoes, portas, args.maquina, candidatos=candidatos_rerank
    )

    entregar(relatorio, args.out)
    if args.out:
        log.info("relatório gravado em %s", args.out)

    for a in medicao.amostras:
        log.info("%-14s p50 %7.1f ms  p95 %7.1f ms  n=%d", a.operacao, a.p50, a.p95, a.n)
    quebras = [v for v in violacoes if v.especie == "regressao"]
    for v in quebras:
        log.error("piso rompido: %s p95 %.1f ms > %.1f ms (%.2f×)", v.operacao, v.medido, v.porta, v.fator)
    return 1 if (args.porta and quebras) else 0


if __name__ == "__main__":
    raise SystemExit(main())
