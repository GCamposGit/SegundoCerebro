"""Prévia de uma pasta antes de indexar — "isso vai demorar quanto?".

O estágio 0 do painel pergunta isso **antes** do compromisso, não depois. É
barato: só metadados, nenhuma abertura de arquivo. E é o que transforma "indexar"
de um salto no escuro em uma decisão informada.

Duas coisas que esta prévia tem que acertar, e as duas são lições pagas:

1. **O mesmo filtro do indexador.** A contagem tem que ser a dos arquivos que
   `iter_files` entrega com as exclusões padrão, não a de tudo que existe na
   pasta. Contar 3.154 quando o indexador processa 1.601 é o erro que reportou
   45% onde o real era 91%, cometido na F1 — e aqui ele apareceria como uma
   estimativa três vezes maior que a verdade.
2. **Placeholder é contado, nunca lido.** `iter_files` olha atributo de nuvem e
   não toca em conteúdo. Ler um byte de placeholder do SharePoint dispara o
   download do arquivo inteiro, e uma pasta sincronizada de 17 GB baixaria
   sozinha durante o que o usuário achou que era uma prévia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..census import DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_GLOBS, Config, RootSpec, iter_files
from ..index.estimativa import Faixa, faixa_humana, peso_de
from ..ingest.parsers import supported_extensions
from ..logger import get_logger

log = get_logger("painel.censo")

TETO_DE_ARQUIVOS = 200_000
"""Trava de segurança: uma raiz apontada por engano para `C:\\` não pode
transformar a prévia em varredura de disco inteiro."""


@dataclass
class Formato:
    extensao: str
    arquivos: int = 0
    bytes: int = 0
    segundos: float = 0.0

    @property
    def tem_parser(self) -> bool:
        # Com ponto: `supported_extensions()` fala a língua de
        # `os.path.splitext`, e comparar "md" contra ".md" dava zero legíveis num
        # acervo inteiro de Markdown. Pego pelo teste, não pela leitura.
        return f".{self.extensao}" in supported_extensions()


@dataclass
class Previa:
    arquivos: int = 0
    bytes: int = 0
    placeholders: int = 0
    segundos: float = 0.0
    formatos: dict[str, Formato] = field(default_factory=dict)
    raizes_ausentes: list[str] = field(default_factory=list)
    truncada: bool = False

    @property
    def legiveis(self) -> int:
        """Quantos o indexador consegue ler hoje. O resto vira `sem_parser`."""
        return sum(f.arquivos for f in self.formatos.values() if f.tem_parser)

    def como_json(self) -> dict:
        ordenados = sorted(self.formatos.values(), key=lambda f: -f.arquivos)
        # Faixa larga de propósito: sem nenhuma medição desta máquina, a semente
        # é tudo o que há, e ela erra. Estreitar aqui seria fingir precisão.
        faixa = Faixa(self.segundos, self.segundos * 2.0)
        return {
            "arquivos": self.arquivos,
            "legiveis": self.legiveis,
            "bytes": self.bytes,
            "placeholders": self.placeholders,
            "estimativa": faixa_humana(faixa),
            "estimativa_segundos": round(self.segundos),
            "truncada": self.truncada,
            "raizes_ausentes": self.raizes_ausentes,
            "formatos": [
                {
                    "extensao": f.extensao or "(sem extensão)",
                    "arquivos": f.arquivos,
                    "bytes": f.bytes,
                    "tem_parser": f.tem_parser,
                }
                for f in ordenados[:12]
            ],
        }


def prever(caminhos: list[str], *, teto: int = TETO_DE_ARQUIVOS) -> Previa:
    """Percorre as pastas contando metadado. Nunca abre arquivo."""
    previa = Previa()
    raizes = []
    for i, bruto in enumerate(caminhos, start=1):
        caminho = Path(bruto).expanduser()
        if not caminho.is_dir():
            previa.raizes_ausentes.append(bruto)
            continue
        raizes.append(RootSpec(name=caminho.name or f"raiz{i}", path=caminho))

    if not raizes:
        return previa

    cfg = Config(roots=raizes)
    cfg.exclude_dirs = DEFAULT_EXCLUDE_DIRS
    cfg.exclude_globs = DEFAULT_EXCLUDE_GLOBS

    for root in raizes:
        for entrada in iter_files(root, cfg):
            if previa.arquivos >= teto:
                previa.truncada = True
                log.warning("prévia truncada em %d arquivos", teto)
                return previa
            extensao = entrada.rel.rsplit(".", 1)[-1].lower() if "." in entrada.rel else ""
            formato = previa.formatos.setdefault(extensao, Formato(extensao))
            formato.arquivos += 1
            formato.bytes += entrada.size
            previa.arquivos += 1
            previa.bytes += entrada.size
            if entrada.cloud_only:
                previa.placeholders += 1
            if formato.tem_parser:
                # Só o que tem parser custa tempo de indexação; o resto é
                # registrado como `sem_parser` em custo praticamente zero.
                custo = peso_de(entrada.rel, entrada.size)
                formato.segundos += custo
                previa.segundos += custo
    return previa
