"""Dense embeddings, local, on CPU. No API, ever (invariant 1).

Two things this module exists to get right:

**The model is a swappable part with a fingerprint.** Measured on this machine,
MiniLM-L12 indexes the corpus in ~2h and e5-large in ~39h, so development runs
on MiniLM and the final choice comes out of the eval. Switching models changes
every vector, so `model_id` carries the dense model, its dimension **and the
fastembed version** — 0.8.0 changed e5-large pooling from CLS to mean, which
silently changes vectors produced by the same model name. The indexer stores
`model_id` per document and re-embeds anything that does not match.

**Query and passage are not encoded the same way.** e5 requires the `query: `
and `passage: ` prefixes, and fastembed does **not** add them: its
`query_embed` is a plain alias for `embed`. Omitting them costs precision
silently. MiniLM and mpnet take no prefix, so the prefix belongs to the model
spec, not to the call site.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import fastembed
import numpy as np

from ..logger import get_logger

log = get_logger("index.embeddings")

CACHE_PADRAO = Path("models")
CARACTERES_POR_TOKEN = 4
"""Estimativa de emergência, só quando o tokenizador real não está acessível.

Conservadora de propósito: 4,49 é a medida em português (`ARCHITECTURE.md`), e
arredondar para baixo superestima o número de tokens, que erra para o lado de
cortar cedo demais em vez de estourar a janela em silêncio."""

MARGEM_TOKENS = 24
"""Folga sobre a janela do modelo: tokens especiais e prefixo de consulta."""


@dataclass(frozen=True)
class ModelSpec:
    id: str
    """Short name used in `model_id` and in the config file."""

    nome: str
    """Name in the fastembed catalogue."""

    dim: int
    max_tokens: int = 512
    """Janela **real** do encoder, que não é a mesma coisa que a janela do
    transformer por baixo dele.

    Medido em 13/08/2026: o `config.json` do MiniLM declara 512 posições, mas o
    `tokenizer_config.json` trunca em 128, e é a truncagem que vale — o que passa
    de 128 é descartado antes de virar vetor. Assumir 512 para todo modelo fez o
    chunker calibrar para 488 tokens enquanto o encoder lia 128, e 80,7% do texto
    indexado nunca chegou ao vetor. Ver `docs/truncagem-silenciosa.md`.

    Preencher com o valor conferido no pacote do modelo, nunca com o padrão."""

    prefixo_passagem: str = ""
    prefixo_consulta: str = ""
    chunks_por_segundo: float = 0.0
    """Measured on an i7-1355U with threads=10 — used to estimate wall clock."""


MODELOS: dict[str, ModelSpec] = {
    "minilm": ModelSpec(
        id="minilm",
        nome="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dim=384,
        max_tokens=128,  # tokenizer_config.json: max_length 128, e não os 512 do config.json
        chunks_por_segundo=13.22,
    ),
    "mpnet": ModelSpec(
        id="mpnet",
        nome="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        dim=768,
        max_tokens=512,
        chunks_por_segundo=2.10,
    ),
    "e5-large": ModelSpec(
        id="e5-large",
        nome="intfloat/multilingual-e5-large",
        dim=1024,
        max_tokens=512,
        prefixo_passagem="passage: ",
        prefixo_consulta="query: ",
        chunks_por_segundo=0.63,
    ),
}

MODELO_PADRAO = "e5-large"
"""Escolhido em 13/08/2026 pelo critério de melhor resultado de longo prazo,
inclusive com o acervo crescendo — e não pelo de custo de experimento.

É o **único treinado para recuperação** no catálogo do `fastembed`: prefixos
assimétricos `query:` e `passage:`, que é a tarefa real. MiniLM e mpnet são
modelos de paráfrase, treinados em similaridade simétrica entre frases; escolher
o mpnet por ser rápido repetiria o erro que acabamos de diagnosticar, com
contabilidade melhor.

Pesa a favor do e5 exatamente o que `docs/escala-f0.md` mediu: escala degrada
**ranqueamento**, não recuperação — recall@10 cai 5% com 7,7× mais documentos
enquanto o MRR cai 13% e o multi-hop 57%. Ranqueamento é o que o objetivo de
treino compra.

O MiniLM fica registrado e **inadequado a este acervo**: janela de 128 tokens dá
orçamento de 104, uns 470 caracteres de chunk. Chunk desse tamanho mudaria também
o índice lexical e levaria embora as medições de `bm25` que sobreviveram à
truncagem silenciosa.

O mpnet fica como dublê rápido: janela de 512 igual à do e5, logo **mesmo
chunking**, útil para validar o pipeline sem esperar horas. Não serve de proxy de
qualidade — objetivo de treino diferente."""


@dataclass(frozen=True)
class Vetor:
    """One dense vector, already normalised for cosine via inner product."""

    valores: np.ndarray

    def __len__(self) -> int:
        return len(self.valores)


def normalizar(v: np.ndarray) -> np.ndarray:
    norma = float(np.linalg.norm(v))
    return v / norma if norma else v


class Embedder:
    """Wraps one dense model. The only place that turns text into vectors."""

    def __init__(
        self,
        modelo: str = MODELO_PADRAO,
        *,
        threads: int | None = 10,
        cache_dir: Path = CACHE_PADRAO,
        lazy: bool = True,
    ) -> None:
        if modelo not in MODELOS:
            raise ValueError(f"modelo desconhecido: {modelo}. Disponíveis: {', '.join(MODELOS)}")
        self.spec = MODELOS[modelo]
        self._threads = threads
        self._cache_dir = cache_dir
        self._modelo = None
        self._contador = None
        if not lazy:
            self._carregar()

    def _carregar(self):  # noqa: ANN202
        if self._modelo is None:
            from fastembed import TextEmbedding

            log.info("carregando %s (%d dim)", self.spec.nome, self.spec.dim)
            kwargs: dict = {
                "cache_dir": str(self._cache_dir),
                "threads": self._threads,
            }
            # Hardware does not enter model_id. CUDA is opt-in; empty is CPU
            # (F6-C). Leaving providers unset used to let ORT pick CUDA on a
            # gpu wheel — the opposite of "CPU is the default".
            from .cuda_runtime import diagnosticar, preparar, provider_pedido

            if provider_pedido() == "cuda":
                diag = diagnosticar(modelo=self.spec.id)
                if not diag.ok:
                    raise RuntimeError(diag.mensagem)
                preparar()
                kwargs["providers"] = ["CUDAExecutionProvider"]
            else:
                kwargs["providers"] = ["CPUExecutionProvider"]
            try:
                self._modelo = TextEmbedding(self.spec.nome, **kwargs)
            except RuntimeError:
                raise
            except Exception as erro:  # noqa: BLE001
                if kwargs.get("providers") == ["CUDAExecutionProvider"]:
                    raise RuntimeError(
                        "O CUDA não carregou neste computador. Tire "
                        "SEGUNDOCEREBRO_PROVIDER=cuda para indexar na CPU — "
                        f"é o padrão. Detalhe: {erro}"
                    ) from erro
                raise
        return self._modelo

    @property
    def model_id(self) -> str:
        """Fingerprint of everything that changes the vectors."""
        return f"{self.spec.id}:{self.spec.dim}:fastembed{fastembed.__version__}"

    @property
    def dim(self) -> int:
        return self.spec.dim

    @property
    def orcamento_tokens(self) -> int:
        """Tokens available for a chunk, with margin for the contextual header.

        The encoder truncates at `max_tokens` without saying so, so the chunker
        needs the real budget instead of a character approximation.
        """
        return self.spec.max_tokens - MARGEM_TOKENS

    def _tokenizador_de_contagem(self):  # noqa: ANN202
        """Cópia do tokenizador com a truncagem desligada, só para contar.

        O tokenizador que o fastembed expõe vem com `truncation` ligada na janela
        do modelo, e `encode()` devolve no máximo esse tanto de ids. Usá-lo para
        contar não conta: satura. Como o chunker pergunta justamente "isto passa
        da janela?", a resposta era sempre "não" e o orçamento nunca era
        aplicado.

        Desligar a truncagem no objeto compartilhado consertaria a contagem e
        quebraria a inferência — o encoder receberia sequências acima da janela.
        Por isso a cópia, feita uma vez e guardada.
        """
        if self._contador is None:
            tokenizador = getattr(getattr(self._carregar(), "model", None), "tokenizer", None)
            if tokenizador is None:  # runtime sem tokenizador exposto
                return None
            try:
                from tokenizers import Tokenizer

                copia = Tokenizer.from_str(tokenizador.to_str())
                copia.no_truncation()
                copia.no_padding()
                self._contador = copia
            except Exception:  # noqa: BLE001 — sem cópia, é melhor estimar que saturar
                log.warning("tokenizador não pôde ser copiado; contagem cai para estimativa")
                return None
        return self._contador

    def contar_tokens(self, texto: str) -> int:
        """Token count from the model's own tokenizer — no estimate by characters."""
        tokenizador = self._tokenizador_de_contagem()
        if tokenizador is None:
            return len(texto) // CARACTERES_POR_TOKEN
        return len(tokenizador.encode(texto, add_special_tokens=False).ids)

    def embed_passagens(
        self,
        textos: Sequence[str],
        batch_size: int = 32,
        ao_progresso: Callable[[int, int], None] | None = None,
        ritmo: float = 1.0,
    ) -> list[np.ndarray]:
        """Embed chunks for indexing.

        `ao_progresso(feitos, total)` runs at each batch boundary so the
        indexer can publish the bar and honour cancel *during* a large file,
        not only after it. Consuming the generator in one list comprehension
        is what froze the bar for four hours on a 68 MB CSV.

        `ritmo` 1.0 = a GPU/CPU no máximo; 0.4 = trabalha 40% do tempo e
        descansa o resto. É o que impede o modo leve/normal de cravar 100%
        numa placa só, sem mudar o `model_id`.
        """
        if not textos:
            return []
        prefixados = [self.spec.prefixo_passagem + t for t in textos]
        modelo = self._carregar()
        bruto: list[np.ndarray] = []
        total = len(prefixados)
        t_lote = time.perf_counter()
        for i, v in enumerate(modelo.embed(prefixados, batch_size=batch_size), start=1):
            bruto.append(np.asarray(v, dtype=np.float32))
            if i % batch_size == 0 or i == total:
                if ao_progresso is not None:
                    ao_progresso(i, total)
                if ritmo < 0.999:
                    from .esforco import dormir_ritmo

                    dormir_ritmo(time.perf_counter() - t_lote, ritmo)
                t_lote = time.perf_counter()
        ruins = sum(1 for v in bruto if not np.isfinite(v).all())
        if ruins:
            raise RuntimeError(
                f"{ruins}/{len(bruto)} vetores com NaN/Inf — no Maxwell o MiniLM "
                "quantizado (onnx-Q) faz isso no CUDA; e5-large (model.onnx) é o teste que vale"
            )
        return [normalizar(v) for v in bruto]

    def embed_consulta(self, texto: str) -> np.ndarray:
        """Embed one query. Asymmetric: uses the query prefix, not the passage one."""
        modelo = self._carregar()
        vetor = next(iter(modelo.embed([self.spec.prefixo_consulta + texto])))
        return normalizar(np.asarray(vetor, dtype=np.float32))

    def estimar_horas(self, n_chunks: int) -> float:
        if not self.spec.chunks_por_segundo:
            return 0.0
        return n_chunks / self.spec.chunks_por_segundo / 3600


def modelos_disponiveis() -> Iterable[tuple[str, ModelSpec]]:
    return sorted(MODELOS.items(), key=lambda kv: -kv[1].chunks_por_segundo)
