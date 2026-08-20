"""Query expansion over a per-base acronym dictionary.

    DPA            -> DPA acordo de proteção de dados
    acordo de ...  -> acordo de proteção de dados DPA

Existe porque num acervo corporativo a pergunta e o documento raramente escolhem
a mesma forma: quem pergunta escreve a sigla e o contrato escreve o nome por
extenso, ou o contrário. O ranqueador lexical casa termo com termo e não tem como
saber que as duas formas são a mesma coisa; o denso às vezes sabe, e é justamente
por isso que ele **não** recebe a expansão — ver `expandir`.

O dicionário **nasce vazio e é do usuário**. Um glossário embutido com as siglas
de uma empresa seria peso morto para qualquer outra, e adivinhar expansão erra
para pior: injeta termo genérico no ranqueador que existe para casamento exato.
Daí o arquivo por base, no molde do conjunto dourado (`config.Base.dourado`) — e
não uma seção do `config.toml`, porque isto é dado que cresce com o uso, não
configuração que alguém revisa.

Formato, TOML, uma linha por sigla:

    [termos]
    DPA = "acordo de proteção de dados"
    CGI = ["Comitê de Governança de IA", "comitê de IA"]

Uma sigla pode ter mais de um significado, e é por isso que o valor aceita lista:
`SST` não quer dizer a mesma coisa em duas empresas, nem às vezes na mesma.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..logger import get_logger
from .nomes import normalizar, tokenizar

log = get_logger("retrieve.glossario")


class ErroDeGlossario(ValueError):
    """Glossário que não pôde ser gravado. A mensagem é para o usuário final."""


def _contem(tokens: Sequence[str], alvo: Sequence[str]) -> bool:
    """`alvo` aparece em `tokens` como sequência contígua.

    Por token e não por substring, e contíguo e não por conjunto, porque os dois
    atalhos erram em direções opostas neste acervo. Substring casaria `PL` dentro
    de "plano". Conjunto casaria "acordo de dados" com uma pergunta que diz
    "acordo" numa frase e "dados" em outra.

    Por sequência de tokens e não por texto cru é também o que faz sigla com hífen
    funcionar: `PO-VCE-007` e `CT-VCE-2024-0142` tokenizam em duas e três partes, e comparar
    o texto normalizado exigiria que a pergunta repetisse a pontuação exata.
    """
    if not alvo:
        return False
    return any(
        list(tokens[i : i + len(alvo)]) == list(alvo)
        for i in range(len(tokens) - len(alvo) + 1)
    )

MAX_TERMOS_POR_CONSULTA = 8
"""Teto de expansões acrescentadas a uma consulta.

Sem teto, uma pergunta cheia de siglas viraria uma consulta de cinquenta termos,
e o `OR` do FTS5 recuperaria meio acervo — o ranqueador lexical perde
exatamente a precisão que ele existe para dar. O teto é sobre a consulta inteira,
não por sigla."""


@dataclass(frozen=True)
class Glossario:
    """Sigla → formas por extenso, e o caminho de volta.

    `termos` é a **única fonte de verdade**, com a sigla exatamente como o usuário
    a escreveu: é ela que a tela mostra e que o arquivo guarda. Os dois índices de
    busca são derivados dela na construção — derivar em vez de guardar em paralelo
    é o que impede a tela e a recuperação de discordarem.
    """

    termos: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Sigla como escrita → formas por extenso. O que a tela lista e o arquivo guarda."""
    expansoes: dict[str, tuple[str, ...]] = field(init=False, repr=False)
    """Derivado: sigla **normalizada** → formas. Quem pergunta escreve `dpa` tanto
    quanto `DPA`, e um índice sensível a caixa erraria metade das vezes."""
    siglas: dict[str, tuple[str, ...]] = field(init=False, repr=False)
    """Derivado: forma por extenso normalizada → **todas** as siglas que a nomeiam.

    Todas, e não a primeira: `dezembro` é `Dez` e é `Dec`, e qual delas está no
    documento é justamente o que não se sabe ao perguntar. Guardar só a primeira
    perdia silenciosamente a que importava — foi o que aconteceu com a `g032`, cuja
    fonte se chama `Apresentação IA CGI Dec-2025.pptx`."""

    def __post_init__(self) -> None:
        expansoes: dict[str, tuple[str, ...]] = {}
        acumulado: dict[str, list[str]] = {}
        for sigla, formas in self.termos.items():
            expansoes[normalizar(sigla)] = formas
            for forma in formas:
                acumulado.setdefault(normalizar(forma), []).append(sigla)
        object.__setattr__(self, "expansoes", expansoes)
        object.__setattr__(self, "siglas", {f: tuple(s) for f, s in acumulado.items()})

    def __bool__(self) -> bool:
        return bool(self.termos)

    @classmethod
    def vazio(cls) -> "Glossario":
        return cls()

    @classmethod
    def de_arquivo(cls, caminho: Path) -> "Glossario":
        """Arquivo ausente devolve glossário vazio, não erro.

        A recuperação funciona sem glossário; deixar de responder porque um
        arquivo opcional não existe seria trocar uma perda de precisão por uma
        falha total. O mesmo vale para TOML quebrado: a tela do painel escreve
        aqui, e um erro de escrita não pode derrubar a busca.
        """
        if not caminho.exists():
            log.debug("sem glossário em %s", caminho)
            return cls.vazio()
        try:
            with caminho.open("rb") as fh:
                dados = tomllib.load(fh)
        except tomllib.TOMLDecodeError as erro:
            log.error("glossário inválido em %s (%s) — seguindo sem ele", caminho, erro)
            return cls.vazio()
        return cls.de_dicionario(dados.get("termos") or {}, onde=str(caminho))

    @classmethod
    def de_dicionario(cls, termos: dict[str, object], *, onde: str = "glossário") -> "Glossario":
        limpos: dict[str, tuple[str, ...]] = {}
        for sigla, valor in termos.items():
            formas = [valor] if isinstance(valor, str) else list(valor)
            limpas = tuple(f.strip() for f in formas if isinstance(f, str) and f.strip())
            if not limpas:
                log.warning("%s: '%s' não tem forma por extenso — ignorada", onde, sigla)
                continue
            limpos[sigla.strip()] = limpas
        return cls(limpos)

    def com(self, sigla: str, formas: Sequence[str]) -> "Glossario":
        """Devolve um glossário novo com a entrada acrescentada ou substituída.

        Substitui em vez de acumular: quem corrige uma sigla que ficou errada
        espera que a errada saia. Quem quer dois significados manda os dois na
        mesma chamada — é o que o valor em lista existe para dizer.
        """
        limpas = tuple(f.strip() for f in formas if f and f.strip())
        if not sigla.strip() or not limpas:
            raise ValueError("sigla e ao menos uma forma por extenso")
        # Casar pela forma normalizada: corrigir `dpa` tem que substituir o `DPA`
        # que já está lá, não criar uma segunda entrada que o TOML aceita e a
        # busca lê como duas.
        alvo = normalizar(sigla)
        sobrevivem = {s: f for s, f in self.termos.items() if normalizar(s) != alvo}
        return Glossario({**sobrevivem, sigla.strip(): limpas})

    def gravar(self, caminho: Path) -> None:
        """Escrita atômica, como `config.gravar` — mesma razão e mesmo padrão."""
        try:
            import tomli_w
        except ModuleNotFoundError as erro:  # pragma: no cover - ambiente sem o escritor
            raise ErroDeGlossario(
                "gravar o glossário exige o pacote 'tomli-w' (pip install tomli-w)"
            ) from erro

        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = caminho.with_suffix(caminho.suffix + ".tmp")
        with temporario.open("wb") as fh:
            tomli_w.dump({"termos": {s: list(f) for s, f in self.termos.items()}}, fh)
        temporario.replace(caminho)

    def expandir(self, consulta: str) -> str:
        """Devolve a consulta com as formas equivalentes anexadas.

        Anexa, nunca substitui: a forma que o usuário escolheu é a que tem mais
        chance de estar no documento, e trocá-la por outra apostaria contra ele.

        Termo já presente na consulta não é reanexado — repetir não muda o `OR`
        do FTS5 e só gastaria o teto.
        """
        if not self.termos:
            return consulta

        tokens = tokenizar(consulta)
        presentes = set(tokens)
        acrescimos: list[str] = []

        for sigla, formas in self.termos.items():
            if not _contem(tokens, tokenizar(sigla)):
                continue
            acrescimos += [f for f in formas if not _contem(tokens, tokenizar(f))]

        for forma_normal, siglas in self.siglas.items():
            if not _contem(tokens, tokenizar(forma_normal)):
                continue
            acrescimos += [s for s in siglas if not set(tokenizar(s)) <= presentes]

        if not acrescimos:
            return consulta

        # dict.fromkeys em vez de set: a ordem importa para o teto cortar sempre
        # os mesmos termos, ou a mesma pergunta mediria diferente entre rodadas.
        unicos = list(dict.fromkeys(acrescimos))[:MAX_TERMOS_POR_CONSULTA]
        return consulta + " " + " ".join(unicos)
