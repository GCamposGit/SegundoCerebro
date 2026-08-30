"""Reranking com cross-encoder — a maior alavanca de precisão da F2.

Bi-encoder para revocação, cross-encoder para precisão. O primeiro comprime
consulta e passagem em vetores separados e compara por cosseno; o segundo vê o
**par junto** e julga relevância. É a diferença entre "a resposta está no top-50"
e "a resposta está em 1º".

O caso que motivou, medido na condição C (`docs/portas-f1-condicao-c.md`): a
pergunta `g036` — "Qual empresa propôs a implantação de IA?" — falha numa pasta
com cinco propostas concorrentes que dizem coisas parecidas. Famílias de versão
não resolvem (não são versões uma da outra) e peso de fusão não resolve (o sinal
é a mesma similaridade para todas). Discriminar irmãos é trabalho de
cross-encoder.

**Correção de 16/08/2026 — o `bge-reranker-v2-m3` não está no fastembed.** O
ROADMAP e o `ARCHITECTURE.md` o nomeiam desde o começo; o catálogo do
`TextCrossEncoder` (0.8.0) não o tem. É o mesmo erro que já custou dois dias com
o BGE-M3 denso, e a lição repetida: **conferir o catálogo antes de escrever o
plano**.

O que existe, e por que sobra um:

| Modelo | Tamanho | Licença | Serve? |
|---|---|---|---|
| `ms-marco-MiniLM-L-6/L-12` | 0,08–0,12 GB | apache-2.0 | Não — treinado só em inglês |
| `jina-reranker-v1-*-en` | 0,13–0,15 GB | apache-2.0 | Não — inglês |
| `jina-reranker-v2-base-multilingual` | 1,11 GB | **cc-by-nc-4.0** | Não — não comercial |
| `BAAI/bge-reranker-base` | 1,04 GB | **mit** | Sim, e é o único |

O jina multilíngue cai pelo mesmo critério que reprovou o `jina-embeddings-v3`
como denso: licença não comercial é impedimento para o uso corporativo que a F5
prevê, não detalhe a resolver depois.

**Rota de volta**, se a qualidade em português não fechar: `bge-reranker-v2-m3`
de verdade via `FlagEmbedding`, que é PyTorch em vez de ONNX — ~2,5 GB de torch e
inferência mais lenta em CPU. A decisão fica para quando houver número.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Sequence, TypeVar

from ..logger import get_logger

log = get_logger("retrieve.rerank")

MODELO_PADRAO = "BAAI/bge-reranker-base"
CACHE_PADRAO = Path("models")

CANDIDATOS_PARA_RERANK = 25
"""Quantos candidatos o cross-encoder reavalia.

**É o botão de latência, e o único que importa.** O custo é linear no número de
pares e não depende de quantos documentos o índice tem: reranquear 25 custa o
mesmo num acervo de mil ou de um milhão. Recall@25 já está em 0,93 na condição C,
então o poço quase sempre contém a resposta — o trabalho é ordenar dentro dele, e
alargá-lo rende pouco e custa proporcional."""


def texto_para_rerank(path: str, trilha: str, texto: str) -> str:
    """O que o cross-encoder deve ler: nome do arquivo + trilha + trecho.

    **Medido em 16/08/2026, e foi a diferença entre inútil e útil.** A primeira
    integração entregava só o texto do trecho, e o resultado foi pior que
    aleatório: recall@1 caiu de 0,644 para 0,222, com 29 de 45 perguntas piorando.

    A causa não era o modelo. Neste acervo o **nome do arquivo é o sinal mais
    forte** — a F0 mediu o baseline por nome em recall@1 0,467, acima do bm25
    sobre conteúdo — e o cross-encoder nunca o via. O caso `g008` mostra o
    mecanismo: a pergunta é "que alternativas de equipe avaliamos", o documento
    certo se chama `Alternativas de Equipe.docx`, e seu primeiro trecho começa
    com "Tenho uma verba de R$20.000 por mês". Julgando só o conteúdo, o
    reranker mandou o documento certo do 1º para o 10º lugar — e estava
    tecnicamente certo sobre o texto que leu.

    Espelha `ChunkConfig.embedding_text`, de propósito: o denso e o reranker
    devem julgar a mesma coisa, ou um desfaz o trabalho do outro.
    """
    nome = Path(path).stem.replace("_", " ")
    cabecalho = [p for p in (" ".join(nome.split()), trilha) if p]
    if not cabecalho:
        return texto
    return " > ".join(cabecalho) + "\n---\n" + texto


T = TypeVar("T")


class Reranker:
    """Cross-encoder local. Invariante 1: nenhuma chamada a API, nunca."""

    def __init__(
        self,
        modelo: str = MODELO_PADRAO,
        *,
        threads: int | None = 10,
        cache_dir: Path = CACHE_PADRAO,
        candidatos: int = CANDIDATOS_PARA_RERANK,
        peso: float | None = None,
        lazy: bool = True,
    ) -> None:
        self.modelo = modelo
        self.candidatos = candidatos
        self.peso = peso
        """Voz do reranker na fusão. `None` = ele **substitui** a ordenação.

        Medido em 16/08/2026: substituir perde. O cross-encoder sozinho descarta
        o consenso de três ranqueadores que já concordaram, e neste acervo esse
        consenso vale mais que o julgamento dele — recall@1 cai de 0,644 para
        0,489. Com peso, ele vira o **quarto ranqueador** e é fundido por posição
        como os outros, que é o mesmo argumento que justificou o RRF no projeto:
        pontuações de escalas diferentes não se comparam, posições se comparam."""
        self._threads = threads
        self._cache_dir = cache_dir
        self._encoder = None
        if not lazy:
            self._carregar()

    def _carregar(self):  # noqa: ANN202
        if self._encoder is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            log.info("carregando reranker %s", self.modelo)
            t0 = time.perf_counter()
            self._encoder = TextCrossEncoder(
                self.modelo, cache_dir=str(self._cache_dir), threads=self._threads
            )
            log.info("reranker pronto em %.1fs", time.perf_counter() - t0)
        return self._encoder

    @property
    def id(self) -> str:
        """Impressão digital para o relatório de ablação."""
        import fastembed

        voz = "substitui" if self.peso is None else f"peso{self.peso:g}"
        return f"{self.modelo}@{self.candidatos}:{voz}:fastembed{fastembed.__version__}"

    def pontuar(self, consulta: str, textos: Sequence[str]) -> list[float]:
        if not textos:
            return []
        return list(self._carregar().rerank(consulta, list(textos)))

    def reordenar(self, consulta: str, itens: Sequence[T], texto_de) -> list[T]:  # noqa: ANN001
        """Reordena os primeiros `candidatos`; o resto segue intacto atrás.

        A cauda não é descartada nem reordenada de graça: reranquear tudo custaria
        proporcional ao poço, e o poço existe para revocação, não para exibição.
        """
        cabeca, cauda = list(itens[: self.candidatos]), list(itens[self.candidatos :])
        if len(cabeca) < 2:
            return list(itens)

        scores = self.pontuar(consulta, [texto_de(i) for i in cabeca])
        por_score = sorted(range(len(cabeca)), key=lambda i: (-scores[i], i))

        if self.peso is None:
            return [cabeca[i] for i in por_score] + cauda

        # Import tardio: `hybrid` importa `texto_para_rerank` daqui, e no topo
        # isto fecharia um ciclo. A função é a mesma de propósito — o reranker
        # entra na fusão pela mesma porta que denso, bm25 e nome.
        from .hybrid import rrf

        original = [str(i) for i in range(len(cabeca))]
        pontos = rrf([original, [str(i) for i in por_score]], pesos=[1.0, self.peso])
        ordem = sorted(range(len(cabeca)), key=lambda i: (-pontos[str(i)], i))
        return [cabeca[i] for i in ordem] + cauda
