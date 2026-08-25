"""Reexporta o construtor de CFB, que mudou de casa em 25/08/2026 (`E1.d`).

O conteúdo está em [`eval/gerador/cfb.py`](../eval/gerador/cfb.py). O motivo da
mudança: o gerador sintético passou a precisar do mesmo construtor para emitir
`.msg`, `.doc` e `.ppt` no corpus, e duplicar 260 linhas de escritor de formato
binário é como duas implementações divergem sem ninguém notar.

Este arquivo continua existindo porque o pacote **`F4-L` é do desktop** e declara
`tests/cfb.py` na lista de paths que ele toca (`ROADMAP.md`). Apagá-lo faria o PR
dele quebrar por um motivo que não é dele. Quem for estender a fixture: estenda
`eval/gerador/cfb.py`, e este arquivo segue valendo.
"""

from eval.gerador.cfb import *  # noqa: F403
from eval.gerador.cfb import escrever_cfb, filetime, msg_de  # noqa: F401
