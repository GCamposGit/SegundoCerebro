"""A trava exclusiva de um diretório de índice, e o erro de quando ela está ocupada.

Saiu de `indexer.py` em 29/08/2026. O nome do arquivo já morava em `travas.py`
desde o mesmo dia, pelo mesmo motivo — ler a trava não pode custar o encoder — e
aqui fica o protocolo que a escreve e a interpreta: `pid,criação`, PID reciclado,
trava órfã.

`index/retomada.py` e o painel perguntam `ocupada()` sem nenhuma intenção de
indexar; era por isso que a classe precisava sair do módulo do laço.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..logger import get_logger
from .travas import NOME_DA_TRAVA

log = get_logger("index.trava")


class TravaOcupada(RuntimeError):
    """Outro indexador já está escrevendo neste índice."""


class TravaDeIndice:
    """Exclusive lock on an index directory for the duration of a run.

    Two indexers against the same directory corrupt the vector table: SQLite in
    WAL mode tolerates the concurrency, LanceDB does not, and `remover + add`
    interleaved duplicates every vector — measured once as 13.458 vectors for
    7.214 chunks, with nothing raising an error. The lock is cheap and removes
    the whole class of failure.
    """

    def __init__(self, diretorio: Path) -> None:
        self.caminho = Path(diretorio) / NOME_DA_TRAVA

    @staticmethod
    def _criacao(pid: int) -> float | None:
        """Instante em que o processo nasceu, ou `None` se não dá para saber."""
        try:
            import psutil

            return psutil.Process(pid).create_time()
        except Exception:  # noqa: BLE001 — psutil ausente, processo morto, permissão
            return None

    def marca(self) -> str:
        """`pid,criacao` — o par que sobrevive a um reinício.

        **Só o PID não basta**, e o modo de falha é cruel: depois de reiniciar, o
        sistema recicla números, e `os.kill(pid, 0)` num PID reaproveitado
        responde "vivo". O usuário levaria "outro indexador está escrevendo" com
        nenhum indexador rodando, e o conserto — apagar um arquivo de trava que
        ele não sabe que existe — não se adivinha.

        Encontrado por leitura em 16/08/2026, ao especificar a retomada
        automática da F3.5 bloco D. Não tinha mordido ainda porque a máquina não
        havia reiniciado no meio de um run.
        """
        pid = os.getpid()
        criacao = self._criacao(pid)
        return f"{pid},{criacao:.3f}" if criacao is not None else str(pid)

    def _dono(self) -> tuple[int, float | None]:
        bruto = self.caminho.read_text(encoding="utf-8").strip()
        pid_texto, _, criacao_texto = bruto.partition(",")
        pid = int(pid_texto) if pid_texto.isdigit() else 0
        try:
            return pid, float(criacao_texto) if criacao_texto else None
        except ValueError:
            return pid, None

    def _vivo(self, pid: int, criacao: float | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        except Exception:  # noqa: BLE001 — PID recusado sem OSError: supor vivo
            return True
        if criacao is None:
            # Trava do formato antigo, sem instante de criação: não há como
            # distinguir o dono de um PID reciclado, e supor "vivo" é o lado
            # seguro — o preço é uma trava a apagar à mão, e o outro lado seria
            # dois indexadores duplicando cada vetor.
            return True
        atual = self._criacao(pid)
        return atual is None or abs(atual - criacao) < 1.0

    def ocupada(self) -> bool:
        """Há um indexador **vivo** neste índice agora?

        Público porque a retomada precisa saber: base sendo indexada não é base
        pendente, e disparar um segundo indexador é o único jeito conhecido de
        corromper a tabela de vetores.
        """
        if not self.caminho.exists():
            return False
        return self._vivo(*self._dono())

    def __enter__(self) -> "TravaDeIndice":
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid, criacao = self._dono()
            if self._vivo(pid, criacao):
                raise TravaOcupada(
                    f"outro indexador (pid {pid}) está escrevendo em {self.caminho.parent}"
                ) from None
            log.warning("trava órfã do pid %s removida", pid or "?")
            self.caminho.unlink(missing_ok=True)
            fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(self.marca())
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        self.caminho.unlink(missing_ok=True)
