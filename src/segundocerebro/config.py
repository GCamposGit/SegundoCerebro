"""Configuração: uma instalação, N bases.

    py -m segundocerebro.index.indexer --base trabalho
    py -m segundocerebro.mcp.server --base pessoal

Uma **base** é um acervo com raízes próprias, índice próprio e servidor MCP
próprio. A separação é física — dois diretórios de índice, dois processos — e o
motivo está no `ARCHITECTURE.md` §2: um filtro de consulta é um booleano que pode
estar errado, dois diretórios não vazam um no outro. Não implementar base como
filtro (invariante 7).

Ordem de resolução, declarada aqui porque implícita ela vira adivinhação:

    padrão do código → config.toml → ambiente (SEGUNDOCEREBRO_*) → flag de CLI

**O ambiente alcança a classe "grátis" e a seção `[maquina]`, e nada além.**
Parâmetros que mudam o índice — modelo de embedding, tamanhos de chunk — ficam
de fora de propósito: variável de ambiente é justamente o caminho silencioso que
a separação por custo de mudança existe para impedir. Reindexar o corpus completo
mediu ~114 horas nesta máquina em 15/08/2026, e invalida toda medição anterior;
isso não acontece porque alguém exportou uma variável.

`[maquina]` é a exceção porque nada nela muda o **conteúdo** do índice, só a
velocidade com que ele é produzido — e é o que faz o mesmo arquivo servir a um
notebook de 15 W e a um desktop com GPU sem ser editado.

Este módulo é deliberadamente leve — só `tomllib` e `census`, ambos de biblioteca
padrão. Ele é carregado por CLI, servidor e futuro painel antes de qualquer
decisão sobre abrir modelo, e importar `index.embeddings` traria `fastembed` e
`numpy` junto. Por isso os padrões estão espelhados aqui em vez de importados —
e `tests/test_config.py` prova que os espelhos batem com os originais, que é o
que impede as duas cópias de divergirem em silêncio.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .census import DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_GLOBS
from .census import Config as CensoConfig
from .census import RoleExclusion, RootSpec
from .logger import get_logger

log = get_logger("config")

ARQUIVO_PADRAO = Path("config.toml")
CENSO_LEGADO = Path("census.toml")
VERSAO = 1

ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
"""Vira nome de diretório e nome de servidor MCP — daí a restrição."""

BASE_UNICA = "padrao"
"""Id da base sintetizada quando não há `config.toml`."""


class ErroDeConfig(ValueError):
    """Configuração inválida. A mensagem é para o usuário final, em português."""


@dataclass(frozen=True)
class Pesos:
    """Espelha as constantes de `retrieve.hybrid`. Classe grátis: recarrega."""

    denso: float = 1.0
    lexical: float = 0.25
    nome: float = 0.5

    fts_texto: float = 1.0
    fts_trilha: float = 1.0
    fts_caminho: float = 1.0
    """Pesos de coluna do `bm25()`, **dentro** do ranqueador lexical.

    Não são um quarto, quinto e sexto ranqueador: são a distribuição de voz
    entre as três colunas do FTS5 (`texto`, `trilha`, `caminho`) que hoje sai
    1/1/1, o padrão do SQLite. Ficam aqui porque quem lê `[base.pesos]` quer ver
    num lugar só tudo que decide ordem.

    `caminho` é o motivo de existirem (`C3.a`): valendo 1,0, o nome do arquivo
    pontua dentro do bm25 **e** de novo na fusão pelo peso `nome`. O mesmo sinal
    vota duas vezes, e num acervo de nomes ruins (`IMG_2034.pdf`) isso é ruído
    dobrado. Os três em 1,0 preservam o SQL exato que mediu F1 a F4 — ver
    `Store.buscar_lexical`.

    São pesos de consulta: mudá-los **não** reindexa nada."""

    def validar(self, onde: str) -> None:
        for campo, valor in (
            ("denso", self.denso),
            ("lexical", self.lexical),
            ("nome", self.nome),
            ("fts_texto", self.fts_texto),
            ("fts_trilha", self.fts_trilha),
            ("fts_caminho", self.fts_caminho),
        ):
            if valor < 0:
                raise ErroDeConfig(f"{onde}: peso '{campo}' não pode ser negativo ({valor})")
        if not (self.denso or self.lexical or self.nome):
            raise ErroDeConfig(f"{onde}: os três pesos são zero — nenhum ranqueador ficaria ativo")
        if self.lexical and not (self.fts_texto or self.fts_trilha or self.fts_caminho):
            raise ErroDeConfig(
                f"{onde}: o ranqueador lexical está ativo (peso {self.lexical:g}) e as três "
                "colunas do bm25 estão em zero — ele não ordenaria nada"
            )

    @property
    def colunas_fts(self) -> tuple[float, float, float] | None:
        """Os pesos de coluna, ou `None` quando são o padrão do FTS5.

        `None` de propósito, e não `(1.0, 1.0, 1.0)`: manda `buscar_lexical` usar
        o `bm25(chunks_fts)` sem argumento, que é o SQL que produziu todos os
        números de F1 a F4. Configuração intocada mede o caminho já medido."""
        colunas = (self.fts_texto, self.fts_trilha, self.fts_caminho)
        return None if colunas == (1.0, 1.0, 1.0) else colunas


@dataclass(frozen=True)
class Busca:
    """Espelha `retrieve.hybrid` e `mcp.server`. Classe grátis: recarrega."""

    candidatos: int = 200
    k_rrf: int = 60
    k: int = 8
    k_max: int = 50
    janela: int = 1
    janela_max: int = 5
    contexto: int = 1
    """Vizinhos anexados a cada acerto do `search`. Ver `mcp.server`."""
    rerank: float | None = None
    """Voz do cross-encoder na fusão. `None` desliga — e é o padrão.

    **Qualidade**, medida em 16/08/2026 na condição C, varrendo o peso: 0,25 →
    recall@1 **0,678** contra 0,644 sem rerank; 0,5 → 0,644; 1,0 → 0,611; 2,0 →
    0,522; substituindo a ordenação → 0,489. Mesma forma da curva do bm25 — voz
    pequena soma, voz plena afoga o consenso dos outros três.

    **Latência**, medida no mesmo dia sem nada concorrendo: a consulta passa de
    **0,92 s para 6,28 s** de mediana com 10 candidatos, e 15,5 s com 25.

    Daí o padrão desligado, que é julgamento e não medição: 6,8× mais lento por
    3,4 pontos de recall@1 não se paga num laço de agente que faz várias buscas
    por turno. Quem prioriza precisão sobre tempo põe `rerank = 0.25` e ganha os
    3,4 pontos.

    Registro de um erro meu, para não se repetir: documentei "+2,5 s" antes de
    medir no caminho real. Aquele número saiu de um probe com documento sintético
    curto repetido dez vezes; chunk de verdade tem até 1.800 caracteres mais o
    prefixo de nome e trilha, e custa o dobro. **Medir o componente não é medir o
    caminho.**"""
    rerank_candidatos: int = 10
    """Quantos candidatos o cross-encoder reavalia. É o botão de latência: o custo
    é linear neles e independe do tamanho do acervo."""

    def validar(self, onde: str) -> None:
        if self.candidatos < 1:
            raise ErroDeConfig(f"{onde}: 'candidatos' precisa ser ao menos 1")
        if self.k_rrf < 1:
            raise ErroDeConfig(f"{onde}: 'k_rrf' precisa ser ao menos 1")
        if not (1 <= self.k <= self.k_max):
            raise ErroDeConfig(f"{onde}: 'k' ({self.k}) precisa estar entre 1 e k_max ({self.k_max})")
        if not (0 <= self.janela <= self.janela_max):
            raise ErroDeConfig(
                f"{onde}: 'janela' ({self.janela}) precisa estar entre 0 e janela_max ({self.janela_max})"
            )
        if self.contexto < 0:
            raise ErroDeConfig(f"{onde}: 'contexto' não pode ser negativo ({self.contexto})")
        if self.rerank is not None and self.rerank < 0:
            raise ErroDeConfig(f"{onde}: 'rerank' não pode ser negativo ({self.rerank})")
        if self.rerank_candidatos < 1:
            raise ErroDeConfig(
                f"{onde}: 'rerank_candidatos' precisa ser ao menos 1 ({self.rerank_candidatos})"
            )


_ALIAS_LIMITES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pdf", (".pdf",)),
    ("docx", (".docx", ".docm", ".doc")),
    ("pptx", (".pptx", ".pptm", ".ppt")),
    ("xlsx", (".xlsx", ".xlsm", ".xls")),
    ("txt", (".txt",)),
    ("csv", (".csv",)),
    ("md", (".md", ".markdown")),
)


@dataclass(frozen=True)
class LimitesDeIndexacao:
    """Teto de tamanho em disco, em MB, por tipo — o arquivo acima fica `adiado`.

    `0` = sem teto. Não é tamanho de trecho (`chunking.max_chars`): aquele muda
    todos os ids e obriga a reindexar. Isto só recusa dumps caros na porta, o
    mesmo mecanismo das planilhas gigantes. Já indexado não sai sozinho.

    Padrão medido em 22/08/2026 neste desktop: `.txt`/`.csv` em 2 MB. Um CSV
    de dezenas de MB segurou a GPU horas sem a barra andar; um TXT enorme
    virou a maioria dos trechos do índice. PDF/DOCX/PPTX começam sem teto —
    são o acervo, não o dump.
    """

    pdf: float = 0.0
    docx: float = 0.0
    pptx: float = 0.0
    xlsx: float = 0.0
    txt: float = 2.0
    csv: float = 2.0
    md: float = 0.0

    def validar(self, onde: str) -> None:
        for campo in self.__dataclass_fields__:
            valor = getattr(self, campo)
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErroDeConfig(f"{onde}: limite '{campo}' precisa ser um número em MB")
            if valor < 0:
                raise ErroDeConfig(f"{onde}: limite '{campo}' não pode ser negativo ({valor})")

    def como_mapa(self) -> dict[str, float]:
        """Extensão → MB, só o que tem teto. O reader não abre o arquivo acima."""
        saida: dict[str, float] = {}
        for campo, extensoes in _ALIAS_LIMITES:
            mb = float(getattr(self, campo))
            if mb > 0:
                for ext in extensoes:
                    saida[ext] = mb
        return saida

    def como_json(self) -> dict[str, float]:
        return {c: float(getattr(self, c)) for c in self.__dataclass_fields__}


LIMITES_RECOMENDADOS = LimitesDeIndexacao(
    pdf=50.0,
    docx=30.0,
    pptx=50.0,
    xlsx=15.0,
    txt=2.0,
    csv=2.0,
    md=5.0,
)
"""Teto inicial por tipo, em MB. 0 continua sendo sem teto se o usuário apagar.

Nascem preenchidos no painel e em bases novas desta máquina. Um CSV enorme
segura a GPU horas; PDF/DOCX/PPTX têm teto alto porque são o acervo, não o dump.
O usuário ajusta uma vez; a próxima base nesta máquina herda."""


@dataclass(frozen=True)
class Chunking:
    """Espelha `ingest.chunking.ChunkConfig`.

    Classe **cara**: mexer aqui muda todos os ids de chunk e obriga a reindexar.
    Uma medição de antes deixa de ser comparável com uma de depois — por isso
    nada disto é alcançável por variável de ambiente.
    """

    max_chars: int = 1800
    min_chars: int = 250
    overlap_chars: int = 200

    def validar(self, onde: str) -> None:
        if self.min_chars >= self.max_chars:
            raise ErroDeConfig(f"{onde}: 'min_chars' ({self.min_chars}) >= 'max_chars' ({self.max_chars})")
        if not (0 <= self.overlap_chars < self.max_chars):
            raise ErroDeConfig(
                f"{onde}: 'overlap_chars' ({self.overlap_chars}) precisa ser menor que 'max_chars'"
            )


PERFIS = ("leve", "normal", "maximo")
"""Esforço ao indexar. Não é backend: `gpu` era eixo misturado e virou alias."""

ALIAS_PERFIL = {"completo": "normal", "gpu": "maximo"}
"""Nomes antigos do `[maquina] perfil`. `completo` era o normal; `gpu` não é esforço."""

FRACAO_CPU = {"leve": 0.25, "normal": 0.50, "maximo": 1.00}
"""Fração dos núcleos lógicos. Leve e normal nunca ficam com 100% se houver o que deixar."""


def normalizar_perfil(perfil: str) -> str:
    """`leve` / `normal` / `maximo`. Aceita os nomes velhos para não quebrar config.toml."""
    p = (perfil or "normal").strip().lower()
    return ALIAS_PERFIL.get(p, p)


def nucleos_para(perfil: str, nucleos: int | None = None) -> int:
    """Quantos núcleos o indexador pode usar neste perfil.

    Flexível entre um notebook de 2 núcleos e um i7 de 20 fios: a conta é
    fração, não número mágico. Com 2+ núcleos, leve e normal deixam pelo menos
    um de fora — é o que impede a máquina de ir a 100% de CPU.
    """
    n = nucleos if nucleos is not None else (os.cpu_count() or 4)
    n = max(1, int(n))
    perfil = normalizar_perfil(perfil)
    if n <= 1 or perfil == "maximo":
        return n
    fracao = FRACAO_CPU.get(perfil, FRACAO_CPU["normal"])
    usados = max(1, round(n * fracao))
    return min(usados, n - 1)


@dataclass(frozen=True)
class Maquina:
    """Com quanta força executar — propriedade do computador, não do acervo.

    Fica fora da base de propósito: o mesmo `config.toml` acompanha o acervo
    entre máquinas, e um notebook de 15 W e um desktop com GPU precisam de
    valores diferentes sem editar o arquivo compartilhado. Daí também os
    sobrescritos por ambiente — é assim que a mesma configuração versionada roda
    nos dois lugares.

    Nada aqui muda o conteúdo do índice: hardware muda velocidade, nunca
    conteúdo (`ARCHITECTURE.md` §4). Por isso `model_id` não carrega o provider —
    se carregasse, copiar o índice para outra máquina dispararia reembedding de
    tudo.
    """

    perfil: str = "normal"
    threads: int | None = None
    """`None` deixa o perfil decidir. Explícito vence o perfil."""
    lote: int = 32
    provider: str = ""
    """Vazio = deixa o runtime escolher. `cuda` exige `onnxruntime-gpu`."""
    limites: LimitesDeIndexacao = LIMITES_RECOMENDADOS
    """Cortes padrão desta máquina. Bases novas herdam; cada base pode sobrescrever."""

    def threads_efetivos(self, nucleos: int | None = None) -> int:
        """Leve ~25%, normal ~50%, máximo 100%. Explícito em `threads` vence.

        Medido em 15/08/2026: 11 h de parada em 46 h de indexação, porque a
        alternativa a parar era o notebook travar. Um indexador que não sabe
        ficar em segundo plano é um indexador que o usuário desliga.
        """
        if self.threads is not None:
            return self.threads
        return nucleos_para(self.perfil, nucleos)

    def validar(self) -> None:
        perfil = normalizar_perfil(self.perfil)
        if perfil not in PERFIS:
            raise ErroDeConfig(
                f"perfil de máquina desconhecido: '{self.perfil}' (use {', '.join(PERFIS)})"
            )
        if self.threads is not None and self.threads < 1:
            raise ErroDeConfig(f"[maquina]: 'threads' precisa ser ao menos 1 ({self.threads})")
        if self.lote < 1:
            raise ErroDeConfig(f"[maquina]: 'lote' precisa ser ao menos 1 ({self.lote})")
        self.limites.validar("[maquina.limites]")


@dataclass(frozen=True)
class Base:
    """Um acervo: raízes, índice e servidor MCP próprios."""

    id: str
    nome: str = ""
    descricao: str = ""
    indice: Path = Path("index")
    modelo: str = "e5-large"
    dourado: Path | None = None
    """Conjunto dourado desta base. `None` = o padrão do eval.

    Arquivo por base, e não um filtro sobre um arquivo comum, pelo mesmo motivo
    da invariante 7: medir a recuperação de um acervo contra as perguntas de
    outro produz um número que parece válido e não é. Um campo pode vir vazio ou
    errado; dois arquivos não se misturam. O campo `base` de cada pergunta existe
    como **conferência** — pega o caso de apontar o arquivo errado — não como a
    fronteira.
    """
    glossario: Path | None = None
    """Glossário de siglas desta base. `None` = nenhum, e é o padrão.

    Arquivo, e não uma seção deste TOML, pelo mesmo motivo do `dourado`: é dado
    que **cresce com o uso**, não configuração que alguém revisa. `gravar()`
    reescreve este arquivo inteiro a cada ajuste do painel, e um dicionário
    morando aqui dentro estaria a um defeito de distância de ser perdido.

    Nasce vazio de propósito. Medido em 18/08/2026
    (`docs/ablacao-glossario.md`): o grupo de entradas **genéricas** — mês
    abreviado, que serviria a qualquer acervo — mediu **zero** ganho, e o grupo
    específico da empresa produziu o ganho inteiro (+0,033 de nDCG@5, +0,153 de
    MRR nas perguntas escritas de memória). Um dicionário embutido seria peso
    morto; o que vale é o do dono do acervo.
    """
    raizes: tuple[RootSpec, ...] = ()
    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDE_DIRS
    exclude_globs: tuple[str, ...] = DEFAULT_EXCLUDE_GLOBS
    exclude_roles: tuple[RoleExclusion, ...] = ()
    """Exclusão por papel: padrão de nome com escopo de pasta. Ver
    `census.RoleExclusion` — existe porque glob solto casa pelo nome em qualquer
    lugar da raiz, e um arquivo de papel redundante dentro de uma pasta pode ser
    a única cópia fora dela."""
    pesos: Pesos = Pesos()
    busca: Busca = Busca()
    chunking: Chunking = Chunking()
    limites: LimitesDeIndexacao = LimitesDeIndexacao()
    """Teto de MB por tipo ao indexar. Não herda de chunking e não muda ids."""

    @property
    def titulo(self) -> str:
        return self.nome or self.id

    @property
    def servidor(self) -> str:
        """Nome do servidor MCP. Com base única, o nome histórico é preservado."""
        return "segundocerebro" if self.id == BASE_UNICA else f"segundocerebro-{self.id}"

    @property
    def registro(self) -> Path:
        return self.indice / "registro.db"

    @property
    def indexada(self) -> bool:
        return self.registro.exists()

    def censo(self) -> CensoConfig:
        """Ponte para o censo e o indexador, que já falam `census.Config`."""
        cfg = CensoConfig(roots=list(self.raizes))
        cfg.exclude_dirs = self.exclude_dirs
        cfg.exclude_globs = self.exclude_globs
        cfg.role_exclusions = self.exclude_roles
        return cfg

    def validar(self) -> None:
        onde = f"base '{self.id}'"
        if not ID_VALIDO.match(self.id):
            raise ErroDeConfig(
                f"id de base inválido: '{self.id}' — use minúsculas, dígitos, '-' ou '_', "
                "começando por letra ou dígito (o id vira nome de pasta e de servidor MCP)"
            )
        self.pesos.validar(onde)
        self.busca.validar(onde)
        self.chunking.validar(onde)
        self.limites.validar(onde)


@dataclass(frozen=True)
class Config:
    bases: tuple[Base, ...]
    maquina: Maquina = Maquina()
    caminho: Path | None = None
    """De onde veio. `None` quando sintetizada — o painel precisa saber para
    escrever no lugar certo em vez de inventar um arquivo."""

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(b.id for b in self.bases)

    def base(self, id: str | None = None, *, ambiente: Mapping[str, str] | None = None) -> Base:
        """Resolve qual base usar: argumento explícito → ambiente → única.

        Com duas bases e nenhuma escolha, isto **falha** em vez de assumir a
        primeira. Indexar a base pessoal por cima do índice de trabalho é caro de
        descobrir e caro de desfazer; a ambiguidade é que é erro, não a omissão.
        """
        ambiente = os.environ if ambiente is None else ambiente
        escolhido = id or ambiente.get("SEGUNDOCEREBRO_BASE") or None

        if escolhido:
            for b in self.bases:
                if b.id == escolhido:
                    return b
            raise ErroDeConfig(
                f"base '{escolhido}' não existe. Configuradas: {', '.join(self.ids) or 'nenhuma'}"
            )

        if len(self.bases) == 1:
            return self.bases[0]
        raise ErroDeConfig(
            f"há {len(self.bases)} bases configuradas ({', '.join(self.ids)}) e nenhuma foi escolhida "
            "— use --base ou SEGUNDOCEREBRO_BASE"
        )

    def validar(self) -> None:
        if not self.bases:
            raise ErroDeConfig("nenhuma base configurada")
        self.maquina.validar()
        for b in self.bases:
            b.validar()

        vistos: dict[str, str] = {}
        for b in self.bases:
            if b.id in vistos:
                raise ErroDeConfig(f"id de base repetido: '{b.id}'")
            vistos[b.id] = b.id

        # Invariante 7: a fronteira é o diretório. Duas bases no mesmo índice, ou
        # uma dentro da outra, desfazem o isolamento sem nenhum sintoma visível.
        resolvidos = [(b, b.indice.resolve()) for b in self.bases]
        for i, (a, caminho_a) in enumerate(resolvidos):
            for outra, caminho_b in resolvidos[i + 1 :]:
                if caminho_a == caminho_b:
                    raise ErroDeConfig(
                        f"bases '{a.id}' e '{outra.id}' apontam para o mesmo índice ({caminho_a}) "
                        "— o isolamento entre bases é o diretório, e ele não pode ser compartilhado"
                    )
                if _contido_em(caminho_a, caminho_b) or _contido_em(caminho_b, caminho_a):
                    raise ErroDeConfig(
                        f"o índice da base '{a.id}' ({caminho_a}) e o da base '{outra.id}' "
                        f"({caminho_b}) estão um dentro do outro — apagar o de fora levaria o "
                        "de dentro junto. Use diretórios irmãos, por exemplo 'index' e "
                        f"'index-{outra.id}'"
                    )

        # Mesmo motivo do índice: duas bases medindo contra o mesmo conjunto
        # dourado produzem dois números que parecem válidos e comparáveis.
        dourados: dict[Path, str] = {}
        for b in self.bases:
            if b.dourado is None:
                continue
            resolvido = b.dourado.resolve()
            if resolvido in dourados:
                raise ErroDeConfig(
                    f"bases '{dourados[resolvido]}' e '{b.id}' apontam para o mesmo conjunto "
                    f"dourado ({resolvido}) — métrica é por base, e não se agrega entre bases"
                )
            dourados[resolvido] = b.id

        _avisar_raizes_sobrepostas(self.bases)


def _contido_em(interno: Path, externo: Path) -> bool:
    return interno != externo and externo in interno.parents


def _avisar_raizes_sobrepostas(bases: tuple[Base, ...]) -> None:
    """Legítimo e caro: o documento é indexado e embeddado uma vez por base."""
    for i, a in enumerate(bases):
        for outra in bases[i + 1 :]:
            for ra in a.raizes:
                for rb in outra.raizes:
                    ca, cb = Path(ra.path).resolve(), Path(rb.path).resolve()
                    if ca == cb or _contido_em(ca, cb) or _contido_em(cb, ca):
                        log.warning(
                            "raiz sobreposta entre as bases '%s' e '%s' (%s / %s) — "
                            "os documentos em comum serão indexados nas duas",
                            a.id,
                            outra.id,
                            ca,
                            cb,
                        )


# --------------------------------------------------------------------------- #
# Leitura


def _raizes(dados: Any, onde: str) -> tuple[RootSpec, ...]:
    if dados is None:
        return ()
    if not isinstance(dados, list):
        raise ErroDeConfig(f"{onde}: 'raizes' precisa ser uma lista")
    saida: list[RootSpec] = []
    for i, entrada in enumerate(dados, start=1):
        if not isinstance(entrada, dict) or "caminho" not in entrada:
            raise ErroDeConfig(f"{onde}: raiz #{i} precisa de 'caminho'")
        saida.append(
            RootSpec(name=entrada.get("nome") or f"raiz{i}", path=Path(entrada["caminho"]))
        )
    return tuple(saida)


def _secao(fonte: Mapping[str, Any], chave: str, herdado, tipo):  # noqa: ANN001, ANN202
    """Herda de `[padrao]` e sobrescreve só as chaves presentes na base."""
    bruto = fonte.get(chave)
    if bruto is None:
        return herdado
    if not isinstance(bruto, dict):
        raise ErroDeConfig(f"'{chave}' precisa ser uma seção, não {type(bruto).__name__}")
    conhecidos = {f for f in tipo.__dataclass_fields__}
    desconhecidos = set(bruto) - conhecidos
    if desconhecidos:
        raise ErroDeConfig(
            f"em '{chave}', chave desconhecida: {', '.join(sorted(desconhecidos))} "
            f"(conhecidas: {', '.join(sorted(conhecidos))})"
        )
    return replace(herdado, **bruto)


CHAVES_DE_EXCLUDE = ("dirs", "globs", "papel")


def _papeis(bruto: Any, onde: str) -> tuple[RoleExclusion, ...]:  # noqa: ANN401
    """`papel` é uma lista de regras `{ dirs, globs }`.

    Aceita as duas escritas que o TOML permite para a mesma coisa: tabela em
    linha dentro de `[base.exclude]`, ou `[[base.exclude.papel]]` repetido.
    """
    if bruto is None:
        return ()
    if isinstance(bruto, Mapping):
        bruto = [bruto]
    if not isinstance(bruto, list):
        raise ErroDeConfig(f"em {onde}, 'papel' precisa ser uma lista de regras")
    regras = []
    for i, item in enumerate(bruto, start=1):
        if not isinstance(item, Mapping):
            raise ErroDeConfig(f"em {onde}, a regra de papel #{i} não é uma tabela")
        desconhecidas = set(item) - {"dirs", "globs"}
        if desconhecidas:
            raise ErroDeConfig(
                f"em {onde}, na regra de papel #{i}, chave desconhecida: "
                f"{', '.join(sorted(desconhecidas))} (conhecidas: dirs, globs)"
            )
        globs = tuple(str(g) for g in item.get("globs", ()))
        if not globs:
            # Sem glob a regra não exclui nada, e uma regra que não faz nada é
            # pior que erro: parece proteção e não é.
            raise ErroDeConfig(f"em {onde}, a regra de papel #{i} não declara 'globs'")
        regras.append(RoleExclusion(globs=globs, dirs=tuple(str(d) for d in item.get("dirs", ()))))
    return tuple(regras)


def _excludes(  # noqa: ANN202
    fonte: Mapping[str, Any],
    atuais: tuple[tuple[str, ...], tuple[str, ...], tuple[RoleExclusion, ...]],
    onde: str = "[exclude]",
):
    """Somam-se às exclusões técnicas padrão, nunca as substituem."""
    dirs, globs, papeis = atuais
    bruto = fonte.get("exclude")
    if not bruto:
        return dirs, globs, papeis
    desconhecidas = set(bruto) - set(CHAVES_DE_EXCLUDE)
    if desconhecidas:
        raise ErroDeConfig(
            f"em {onde}, chave desconhecida em 'exclude': {', '.join(sorted(desconhecidas))} "
            f"(conhecidas: {', '.join(CHAVES_DE_EXCLUDE)})"
        )
    if "dirs" in bruto:
        dirs = dirs + tuple(bruto["dirs"])
    if "globs" in bruto:
        globs = globs + tuple(bruto["globs"])
    papeis = papeis + _papeis(bruto.get("papel"), onde)
    return dirs, globs, papeis


def _base_de(dados: Mapping[str, Any], padrao: Base, indice: int) -> Base:
    id_ = dados.get("id")
    if not id_:
        raise ErroDeConfig(f"a base #{indice} não tem 'id'")

    dirs, globs, papeis = _excludes(
        dados,
        (padrao.exclude_dirs, padrao.exclude_globs, padrao.exclude_roles),
        f"base '{id_}'",
    )
    return Base(
        id=str(id_),
        nome=str(dados.get("nome", "")),
        descricao=str(dados.get("descricao", "")),
        indice=Path(dados["indice"]) if "indice" in dados else Path("index") / str(id_),
        modelo=str(dados.get("modelo", padrao.modelo)),
        dourado=Path(dados["dourado"]) if "dourado" in dados else None,
        glossario=Path(dados["glossario"]) if "glossario" in dados else None,
        raizes=_raizes(dados.get("raizes"), f"base '{id_}'"),
        exclude_dirs=dirs,
        exclude_globs=globs,
        exclude_roles=papeis,
        pesos=_secao(dados, "pesos", padrao.pesos, Pesos),
        busca=_secao(dados, "busca", padrao.busca, Busca),
        chunking=_secao(dados, "chunking", padrao.chunking, Chunking),
        limites=_secao(dados, "limites", padrao.limites, LimitesDeIndexacao),
    )


def _num(ambiente: Mapping[str, str], chave: str, conversor):  # noqa: ANN001, ANN202
    bruto = ambiente.get(chave)
    if bruto is None:
        return None
    try:
        return conversor(bruto)
    except ValueError as erro:
        raise ErroDeConfig(f"{chave}={bruto!r} não é um número válido") from erro


def _aplicar_ambiente(base: Base, ambiente: Mapping[str, str]) -> Base:
    """Só a classe grátis. Ver o docstring do módulo."""
    pesos, busca = base.pesos, base.busca

    for chave, campo in (
        ("SEGUNDOCEREBRO_PESO_DENSO", "denso"),
        ("SEGUNDOCEREBRO_PESO_LEXICAL", "lexical"),
        ("SEGUNDOCEREBRO_PESO_NOME", "nome"),
    ):
        valor = _num(ambiente, chave, float)
        if valor is not None:
            pesos = replace(pesos, **{campo: valor})

    for chave, campo in (
        ("SEGUNDOCEREBRO_CANDIDATOS", "candidatos"),
        ("SEGUNDOCEREBRO_K_RRF", "k_rrf"),
        ("SEGUNDOCEREBRO_K", "k"),
    ):
        valor = _num(ambiente, chave, int)
        if valor is not None:
            busca = replace(busca, **{campo: valor})

    return replace(base, pesos=pesos, busca=busca)


def _maquina(dados: Mapping[str, Any], ambiente: Mapping[str, str]) -> Maquina:
    """`[maquina]` do arquivo, depois o ambiente por cima.

    O ambiente alcança tudo aqui — ao contrário dos parâmetros de índice — porque
    nada nesta seção muda o conteúdo do índice, só a velocidade com que ele é
    produzido. É o mecanismo que faz o mesmo `config.toml` servir ao notebook e
    ao desktop com GPU.
    """
    bruto = dict(dados) if dados else {}
    limites_bruto = bruto.pop("limites", None)
    m = _secao({"maquina": bruto}, "maquina", Maquina(), Maquina) if bruto else Maquina()
    if limites_bruto is not None:
        m = replace(
            m,
            limites=_secao({"limites": limites_bruto}, "limites", m.limites, LimitesDeIndexacao),
        )
    m = replace(m, perfil=normalizar_perfil(m.perfil))

    perfil = ambiente.get("SEGUNDOCEREBRO_PERFIL")
    if perfil:
        m = replace(m, perfil=normalizar_perfil(perfil))
    provider = ambiente.get("SEGUNDOCEREBRO_PROVIDER")
    if provider:
        m = replace(m, provider=provider)
    for chave, campo in (("SEGUNDOCEREBRO_THREADS", "threads"), ("SEGUNDOCEREBRO_LOTE", "lote")):
        valor = _num(ambiente, chave, int)
        if valor is not None:
            m = replace(m, **{campo: valor})
    return m


def _do_censo(caminho: Path) -> Config:
    """Continuidade: o `census.toml` de hoje vira uma base só, sem reindexar.

    O índice em `index/` continua valendo. Ninguém reindexa por causa da F3.5.
    """
    from .census import load_config

    censo = load_config(caminho)
    base = _resolver(
        Base(
            id=BASE_UNICA,
            nome="Base padrão",
            indice=Path("index"),
            raizes=tuple(censo.roots),
            exclude_dirs=tuple(censo.exclude_dirs),
            exclude_globs=tuple(censo.exclude_globs),
            exclude_roles=tuple(censo.role_exclusions),
        ),
        caminho.parent,
    )
    log.info("sem config.toml — base única sintetizada de %s", caminho)
    return Config(bases=(base,), caminho=None)


def como_toml(cfg: Config, raiz: Path | None = None) -> dict[str, Any]:
    """Configuração como dados prontos para serialização.

    `raiz` reescreve como relativo tudo que estiver abaixo dela — simetria de
    `_resolver`, que ancora na leitura. Sem isso, salvar pelo painel converteria
    `indice = "index"` em caminho absoluto desta máquina e o par
    `config.toml` + `index/` deixaria de poder ser copiado para outro
    computador, que é justamente o fluxo da F3.6.

    Só o que difere do padrão é escrito. Um arquivo que repete todos os valores
    embutidos vira uma cópia congelada: no dia em que um padrão do código mudar,
    a configuração antiga silenciosamente continua no valor velho, e ninguém
    descobre porque o arquivo "não foi alterado". Omitir é o que deixa o padrão
    ser padrão.
    """

    def diferenca(objeto, referencia) -> dict[str, Any]:  # noqa: ANN001
        return {
            campo: getattr(objeto, campo)
            for campo in objeto.__dataclass_fields__
            if getattr(objeto, campo) != getattr(referencia, campo)
        }

    def caminho(p: Path) -> str:
        if raiz is not None:
            try:
                return str(p.relative_to(raiz))
            except ValueError:
                pass  # fora da árvore do config: absoluto é a resposta certa
        return str(p)

    dados: dict[str, Any] = {"versao": VERSAO}

    maquina = diferenca(cfg.maquina, Maquina())
    if "limites" in maquina:
        lim = diferenca(cfg.maquina.limites, Maquina().limites)
        if lim:
            maquina["limites"] = lim
        else:
            del maquina["limites"]
    if maquina:
        dados["maquina"] = {k: v for k, v in maquina.items() if v is not None}

    bases: list[dict[str, Any]] = []
    for b in cfg.bases:
        entrada: dict[str, Any] = {"id": b.id}
        for campo in ("nome", "descricao", "modelo"):
            if getattr(b, campo):
                entrada[campo] = getattr(b, campo)
        entrada["indice"] = caminho(b.indice)
        if b.dourado is not None:
            entrada["dourado"] = caminho(b.dourado)
        if b.glossario is not None:
            entrada["glossario"] = caminho(b.glossario)
        if b.raizes:
            entrada["raizes"] = [{"nome": r.name, "caminho": caminho(Path(r.path))} for r in b.raizes]

        extras_dirs = tuple(d for d in b.exclude_dirs if d not in DEFAULT_EXCLUDE_DIRS)
        extras_globs = tuple(g for g in b.exclude_globs if g not in DEFAULT_EXCLUDE_GLOBS)
        if extras_dirs or extras_globs or b.exclude_roles:
            entrada["exclude"] = {}
            if extras_dirs:
                entrada["exclude"]["dirs"] = list(extras_dirs)
            if extras_globs:
                entrada["exclude"]["globs"] = list(extras_globs)
            if b.exclude_roles:
                entrada["exclude"]["papel"] = [
                    {"dirs": list(r.dirs), "globs": list(r.globs)} if r.dirs else {"globs": list(r.globs)}
                    for r in b.exclude_roles
                ]

        for chave, valor, referencia in (
            ("pesos", b.pesos, Pesos()),
            ("busca", b.busca, Busca()),
            ("chunking", b.chunking, Chunking()),
            ("limites", b.limites, LimitesDeIndexacao()),
        ):
            secao = diferenca(valor, referencia)
            if secao:
                entrada[chave] = secao
        bases.append(entrada)

    dados["base"] = bases
    return dados


def gravar(cfg: Config, caminho: Path) -> None:
    """Grava a configuração, de forma que reler devolva o mesmo objeto.

    É a metade que falta para o painel: a invariante 4 exige medir antes de
    salvar, e salvar exige escrever. O `tomli_w` entra aqui e só aqui — escapar
    caminho do Windows à mão é onde escritor de TOML caseiro erra, e um erro
    desses corrompe a configuração do usuário em silêncio.

    Escrita atômica: um `.tmp` ao lado e um `replace`. Configuração meio escrita
    por queda de energia é pior que configuração velha.
    """
    try:
        import tomli_w
    except ModuleNotFoundError as erro:  # pragma: no cover - depende do ambiente
        raise ErroDeConfig(
            "gravar configuração exige o pacote `tomli-w` (pip install tomli-w) — "
            "ele não é necessário para consultar, só para o painel"
        ) from erro

    cfg.validar()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    with temporario.open("wb") as fh:
        tomli_w.dump(como_toml(cfg, caminho.parent), fh)
    temporario.replace(caminho)


def _resolver(base: Base, raiz: Path) -> Base:
    """Caminho relativo vale a partir do arquivo de configuração, não do CWD.

    Descoberto em 15/08/2026 pelos testes do painel. Um `indice = "index"` cujo
    significado muda conforme o diretório de onde se roda o comando é o pior modo
    de falha que este projeto conhece: silencioso. O servidor abriria um índice
    vazio — ou criaria um — e o sintoma seria "a busca não acha nada", que aponta
    para o ranqueador em vez de para o caminho.

    Também é o que torna a configuração portátil junto com o acervo: o par
    `config.toml` + `index/` pode ser copiado inteiro para outra máquina.
    """

    def ancorar(p: Path | None) -> Path | None:
        if p is None:
            return None
        return p if p.is_absolute() else raiz / p

    return replace(
        base,
        indice=ancorar(base.indice),
        dourado=ancorar(base.dourado),
        glossario=ancorar(base.glossario),
        raizes=tuple(
            RootSpec(name=r.name, path=ancorar(Path(r.path))) for r in base.raizes
        ),
    )


def _finalizar(cfg: Config, ambiente: Mapping[str, str], validar: bool) -> Config:
    cfg = replace(
        cfg,
        bases=tuple(_aplicar_ambiente(b, ambiente) for b in cfg.bases),
        maquina=_maquina({}, ambiente),
    )
    if validar:
        cfg.validar()
    return cfg


def carregar(
    caminho: Path | None = None,
    *,
    ambiente: Mapping[str, str] | None = None,
    validar: bool = True,
    raiz: Path | None = None,
) -> Config:
    """Lê a configuração, aplica ambiente e valida.

    Sem `caminho`: `SEGUNDOCEREBRO_CONFIG`, depois `config.toml`, depois o
    `census.toml` legado, depois os padrões do código. `raiz` diz onde procurar
    quando o processo não roda do diretório do repositório.

    Um `census.toml` **passado explicitamente** também é aceito, e não por
    tolerância: `--config census.toml` está nos comandos documentados do
    `CLAUDE.md` e do `docs/estado-f1.md`. Uma migração que exige reescrever a
    documentação para continuar rodando o que já rodava é uma migração que
    ninguém faz.
    """
    ambiente = os.environ if ambiente is None else ambiente
    onde = raiz or Path(".")

    if caminho is None:
        do_ambiente = ambiente.get("SEGUNDOCEREBRO_CONFIG")
        if do_ambiente:
            caminho = Path(do_ambiente)
        elif (onde / ARQUIVO_PADRAO).exists():
            caminho = onde / ARQUIVO_PADRAO
        elif (onde / CENSO_LEGADO).exists():
            return _finalizar(_do_censo(onde / CENSO_LEGADO), ambiente, validar)
        else:
            return _finalizar(
                Config(bases=(Base(id=BASE_UNICA, nome="Base padrão"),), caminho=None),
                ambiente,
                validar,
            )

    if not caminho.exists():
        raise ErroDeConfig(f"configuração não encontrada: {caminho}")

    with caminho.open("rb") as fh:  # arquivo de configuração, não conteúdo do corpus
        dados = tomllib.load(fh)

    versao = int(dados.get("versao", VERSAO))
    if versao > VERSAO:
        raise ErroDeConfig(
            f"{caminho} declara versão {versao}, e esta instalação entende até {VERSAO}"
        )

    padrao_bruto = dados.get("padrao", {})
    dirs, globs, papeis = _excludes(
        padrao_bruto, (DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_GLOBS, ()), "[padrao]"
    )
    padrao = Base(
        id=BASE_UNICA,
        modelo=str(padrao_bruto.get("modelo", Base.modelo)),
        exclude_dirs=dirs,
        exclude_globs=globs,
        exclude_roles=papeis,
        pesos=_secao(padrao_bruto, "pesos", Pesos(), Pesos),
        busca=_secao(padrao_bruto, "busca", Busca(), Busca),
        chunking=_secao(padrao_bruto, "chunking", Chunking(), Chunking),
        limites=_secao(padrao_bruto, "limites", LimitesDeIndexacao(), LimitesDeIndexacao),
    )

    brutas = dados.get("base", [])
    if not brutas:
        if "roots" in dados:  # census.toml legado, apontado à mão
            return _finalizar(_do_censo(caminho), ambiente, validar)
        raise ErroDeConfig(f"{caminho} não declara nenhuma [[base]]")

    raiz_do_arquivo = caminho.parent
    bases = tuple(
        _aplicar_ambiente(_resolver(_base_de(bruta, padrao, i), raiz_do_arquivo), ambiente)
        for i, bruta in enumerate(brutas, start=1)
    )
    cfg = Config(bases=bases, maquina=_maquina(dados.get("maquina", {}), ambiente), caminho=caminho)
    if validar:
        cfg.validar()
    return cfg
