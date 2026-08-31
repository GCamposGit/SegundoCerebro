"""Os nomes dos dois arquivos de trava — e nada mais neste módulo.

Um módulo com duas strings existe por um motivo medido. `store.py` já explicava a
duplicação: *"eval e a suíte precisam consultar a trava **sem** importar o
indexador (GPU, encoder, laço)"*. A regra estava escrita e o painel a violava —
`painel/app.py` fazia `from ..index.indexer import NOME_DA_TRAVA` e
`from ..index.watcher import NOME_DA_TRAVA`, e cada um desses dois imports
arrasta `index/embeddings.py`, que importa `fastembed` no topo. Importar
`segundocerebro.painel.app` custava **1,08 s** e carregava o encoder inteiro para
ler o nome de um arquivo.

O custo não é estético. O painel é o que a invariante 6 mantém fora do caminho de
consulta, e é o primeiro degrau de quem instala do zero: o estágio 0 da `F6-B`
abre o painel antes de existir índice, encoder ou modelo baixado.

Além do custo, a constante estava escrita duas vezes com o mesmo valor
(`store.py` e `indexer.py`) sem nada conferindo que continuassem iguais — a mesma
forma de defeito que as três listas de extensão OLE legado.
"""

from __future__ import annotations

NOME_DA_TRAVA = "indexacao.lock"
"""Marca que um indexador está escrevendo neste diretório de índice.

Escrita por `index.indexer.TravaDeIndice`, lida por `index.store.indexacao_viva`
(que só confere se o PID está vivo — para recusar a suíte basta isso) e pelo
painel, que desabilita "Medir" enquanto ela existe: medir contra um índice em
reescrita mede um alvo em movimento."""

NOME_DO_OBSERVADOR = "watcher.lock"
"""Marca que um observador (`index.watcher`) está de pé sobre esta base.

Arquivo diferente do de cima de propósito: indexar e observar são exclusivos
entre si por outro motivo e em outro momento, e um nome só faria o painel
confundir "está indexando agora" com "tem watcher ligado desde ontem"."""
