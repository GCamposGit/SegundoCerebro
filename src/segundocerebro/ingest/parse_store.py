"""O parse store — a representação canônica no disco, uma vez por documento.

`J.a`. Hoje todo rebuild de vetores paga o parse de novo: OCR, LibreOffice,
recálculo de planilha, tudo. O store transforma isso em investimento único por
documento, e ao mesmo tempo é o que habilita as tools de leitura integral
(`get_document`, `pack_folder`) — três consumidores, um parse.

**O que é a chave, e por que ela tem quatro partes.** A especificação propõe
`(hash, parser_version, rota)`. Três rotas do produto saem do nosso controle:
`converters/libreoffice.py` é binário externo, `ocr.py` é motor de ML, e o
recálculo de planilha é o mesmo LibreOffice. Sem a **versão do motor** na chave,
um upgrade de sistema deixa o cache servindo o parse velho para sempre — e a
mitigação que a especificação propõe (regra de PR no bump de `parser_version`)
**não dispara**, porque ninguém commitou nada. O sintoma é conteúdo desatualizado
servido com confiança, que é o pior deste repositório
(`docs/plano-pacote-j.md` §3.6).

**Uma entrada é um arquivo, e isso é escolha de atomicidade.** A especificação
propõe dois — `.md.zst` e `.json`. Dois arquivos não têm escrita atômica
conjunta: `kill -9` entre o primeiro `os.replace` e o segundo deixa Markdown sem
estrutura, e o critério de aceite do `J.a` exige justamente sobreviver a
interrupção sem corromper entradas. Um arquivo, um `os.replace`, e o problema não
existe. O Markdown continua sendo a renderização e os blocos a estrutura — o que
muda é o empacotamento, que a especificação declara não-normativo.

**`zlib` e não `zstd`, e o número é o argumento.** A especificação pede zstd
("texto comprime 5–20×"), que é dependência nova. Medido em 31/08/2026 sobre o
texto extraído do acervo corporativo real — 4.000 chunks, 4,45 MB:

| | |
|---|---:|
| `zlib` nível 6 | 0,81 MB — **5,5×** |
| `zlib` nível 9 | 0,80 MB — 5,6× |
| store completo do acervo (98.326 chunks, 87,5 M chars) | **~16 MB** |

Já está dentro da faixa que a especificação declara, com **zero** dependência
nova. Para um produto cuja régua é *um leigo apontando uma pasta*, uma extensão
nativa a menos na instalação vale mais que o dobro de compressão num artefato de
16 MB que é descartável por construção. Nível 6 e não 9: 1% de disco não paga o
tempo de CPU por documento.

**O store é 100% derivado e descartável.** Apagá-lo não perde dado nenhum do
usuário; qualquer entrada se regenera do original. Nenhum fluxo pode tratá-lo
como fonte primária — e ele vive **dentro do diretório do índice**, nunca nas
pastas do acervo (invariante 1 do pacote J, e do repositório antes dele).
"""

from __future__ import annotations

import json
import os
import shutil
import time
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256 as _sha256
from pathlib import Path

from ..logger import get_logger
from .canonico import VERSAO_CANONICA, BlocoCanonico, ParseCanonico

log = get_logger("ingest.parse_store")

PASTA = "parse_store"
SUFIXO = ".canon.zz"
NIVEL_ZLIB = 6
CARENCIA_PADRAO_DIAS = 14

ROTA_NATIVA = "nativo"
ROTA_LIBREOFFICE = "libreoffice"
ROTA_OCR = "ocr"


@dataclass(frozen=True)
class Chave:
    """O que identifica uma entrada. Mesma chave ⇒ mesmos bytes."""

    sha256: str
    parser: str
    rota: str = ROTA_NATIVA
    motor: str = ""
    """Assinatura do motor externo. Vazia na rota nativa, onde não há motor."""

    def digest(self) -> str:
        cru = "\x00".join([self.sha256, self.parser, self.rota, self.motor, VERSAO_CANONICA])
        return _sha256(cru.encode("utf-8")).hexdigest()[:32]

    @property
    def valida(self) -> bool:
        return bool(self.sha256 and self.parser)


_ASSINATURAS: dict[str, str] = {}


def assinatura_do_motor(rota: str) -> str:
    """A versão do motor externo desta rota, cacheada por processo.

    Nativa não tem motor: `parser_version` já cobre tudo que decide a saída.

    Para o LibreOffice a assinatura é **tamanho e mtime do binário**, não
    `soffice --version`: perguntar a versão custa subir o processo, e um upgrade
    de sistema muda os dois de qualquer forma. A consequência é honesta e vale
    dizer: duas máquinas com a mesma versão do LibreOffice podem ter assinaturas
    diferentes, e aí a segunda paga um miss. Miss é custo; parse velho servido
    com confiança é defeito.

    Para o OCR entra o backend que respondeu ao probe — o mesmo `ocr:1` com dois
    backends produz texto diferente, e é o backend que decide.
    """
    if rota in _ASSINATURAS:
        return _ASSINATURAS[rota]

    assinatura = ""
    if rota == ROTA_LIBREOFFICE:
        from .converters.libreoffice import encontrar_soffice

        caminho = encontrar_soffice()
        if caminho:
            try:
                st = os.stat(caminho)
                assinatura = f"soffice:{st.st_size}:{int(st.st_mtime)}"
            except OSError as erro:  # noqa: BLE001 — sem assinatura o miss é o padrão seguro
                log.debug("assinatura do soffice não lida: %s", erro)
    elif rota == ROTA_OCR:
        from .ocr import VERSAO, backend_disponivel

        assinatura = f"{VERSAO}:{backend_disponivel() or 'sem-backend'}"

    _ASSINATURAS[rota] = assinatura
    return assinatura


def rota_de(meta: dict[str, str]) -> str:
    """Qual rota produziu este `ParsedDoc`, lida do `meta` que ela mesma grava."""
    if meta.get("fonte") == "ocr":
        return ROTA_OCR
    if meta.get("convertido_de") or meta.get("convertido") or meta.get("recalculado"):
        return ROTA_LIBREOFFICE
    return ROTA_NATIVA


def chave_de(sha256: str, parser: str, meta: dict[str, str] | None = None) -> Chave:
    """A chave de um parse, com a rota e o motor derivados do próprio `meta`."""
    rota = rota_de(meta or {})
    return Chave(sha256=sha256, parser=parser, rota=rota, motor=assinatura_do_motor(rota))


class ParseStore:
    """Única porta de leitura e escrita da representação canônica."""

    def __init__(self, diretorio_do_indice: Path) -> None:
        self.raiz = Path(diretorio_do_indice) / PASTA

    def caminho(self, chave: Chave) -> Path:
        d = chave.digest()
        return self.raiz / d[:2] / f"{d}{SUFIXO}"

    # --- leitura ----------------------------------------------------------

    def obter(self, chave: Chave) -> ParseCanonico | None:
        """Hit ou `None`. Entrada corrompida é **miss**, não exceção.

        O store é derivado e regenerável, então uma entrada ilegível — disco com
        setor ruim, escrita interrompida por uma versão antiga sem `os.replace` —
        não pode derrubar a passada. Ela é apagada e a passada reparseia: é a
        única reação que preserva o acervo.
        """
        if not chave.valida:
            return None
        alvo = self.caminho(chave)
        try:
            dados = json.loads(zlib.decompress(alvo.read_bytes()).decode("utf-8"))
        except FileNotFoundError:
            return None
        except (zlib.error, UnicodeDecodeError, json.JSONDecodeError, OSError) as erro:
            log.warning("entrada ilegível em %s (%s) — apagando e reparseando", alvo.name, erro)
            alvo.unlink(missing_ok=True)
            return None
        return ParseCanonico(
            markdown=dados["markdown"],
            blocos=tuple(
                BlocoCanonico(
                    trilha=tuple(b["trilha"]),
                    inicio=int(b["inicio"]),
                    fim=int(b["fim"]),
                    kind=b.get("kind", "texto"),
                    locator=b.get("locator", ""),
                )
                for b in dados.get("blocos", ())
            ),
            meta=dict(dados.get("meta", {})),
        )

    # --- escrita ----------------------------------------------------------

    def gravar(self, chave: Chave, canonico: ParseCanonico) -> Path | None:
        """Escrita atômica: temp no mesmo diretório, depois `os.replace`.

        Mesmo diretório porque `os.replace` só é atômico dentro do mesmo volume,
        e `%TEMP%` pode estar em outro disco. Devolve `None` quando a chave é
        inválida — parse sem hash não tem identidade, e gravar sob chave
        incompleta criaria entrada que nenhum `obter` encontra.
        """
        if not chave.valida:
            return None
        alvo = self.caminho(chave)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        corpo = {
            # O `sha256` vai no corpo, e não só no `meta` do parser: é o GC que o
            # lê para saber se o conteúdo ainda está no censo, e `meta` é o que o
            # parser resolveu escrever — depender dele faria o GC preservar tudo
            # de um parser que não escreve hash, o que é vazamento de disco, ou
            # apagar tudo, o que é pior.
            "sha256": chave.sha256,
            "markdown": canonico.markdown,
            "blocos": [
                {
                    "trilha": list(b.trilha),
                    "inicio": b.inicio,
                    "fim": b.fim,
                    "kind": b.kind,
                    "locator": b.locator,
                }
                for b in canonico.blocos
            ],
            "meta": dict(sorted(canonico.meta.items())),
        }
        # `sort_keys` e separadores fixos: sem eles a mesma entrada gravada por
        # duas versões do Python produziria bytes diferentes, e a byte-identidade
        # que o `J.a` promete cairia por causa da serialização, não do parse.
        cru = json.dumps(corpo, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        temporario = alvo.with_suffix(alvo.suffix + f".tmp{os.getpid()}")
        temporario.write_bytes(zlib.compress(cru.encode("utf-8"), NIVEL_ZLIB))
        os.replace(temporario, alvo)
        return alvo

    # --- manutenção -------------------------------------------------------

    def invalidar(self, chave: Chave) -> bool:
        alvo = self.caminho(chave)
        if not alvo.exists():
            return False
        alvo.unlink()
        return True

    def apagar_tudo(self) -> None:
        """O store é descartável — e provar isso exige poder descartá-lo."""
        shutil.rmtree(self.raiz, ignore_errors=True)

    def entradas(self) -> Iterable[Path]:
        if not self.raiz.exists():
            return ()
        return sorted(self.raiz.rglob(f"*{SUFIXO}"))

    def estatisticas(self) -> dict[str, int]:
        arquivos = list(self.entradas())
        return {
            "entradas": len(arquivos),
            "bytes": sum(a.stat().st_size for a in arquivos),
        }

    def gc(self, hashes_vivos: Iterable[str], carencia_dias: int = CARENCIA_PADRAO_DIAS) -> int:
        """Remove entrada cujo conteúdo sumiu do censo há mais que a carência.

        **Censo vazio é recusado, não obedecido.** Um `hashes_vivos` vazio
        significa quase sempre "o censo não rodou" — e obedecer apagaria o store
        inteiro em silêncio, que é a classe de defeito que este repositório já
        pagou duas vezes: regra de exclusão que não casa com nada falha em
        silêncio, e menos arquivo é justamente o que se pediu
        (`docs/duas-falhas-silenciosas.md`).

        A carência sai do **mtime da entrada**, não de estado próprio: entrada
        gravada agora nunca é coletada, e a janela protege o caso "o censo de
        ontem rodou parcial porque a pasta de rede estava fora".

        O GC compara `sha256`, não digest de chave, porque é o conteúdo que sumiu
        do acervo — as entradas de outras rotas do mesmo conteúdo somem juntas.
        """
        vivos = {h for h in hashes_vivos if h}
        if not vivos:
            log.warning("gc recusado: censo vazio apagaria o store inteiro")
            return 0

        prefixos_vivos = {h[:32] for h in vivos}
        limite = time.time() - carencia_dias * 86400
        removidas = 0
        for arquivo in list(self.entradas()):
            try:
                if arquivo.stat().st_mtime > limite:
                    continue
                if self._sha_da_entrada(arquivo, prefixos_vivos):
                    continue
                arquivo.unlink()
                removidas += 1
            except OSError as erro:  # noqa: BLE001 — GC não derruba passada
                log.debug("gc não removeu %s: %s", arquivo.name, erro)
        if removidas:
            log.info("gc: %d entrada(s) removida(s) do parse store", removidas)
        return removidas

    def _sha_da_entrada(self, arquivo: Path, prefixos_vivos: set[str]) -> bool:
        """O conteúdo desta entrada ainda está no censo?

        A entrada guarda o `sha256` no corpo, gravado por `gravar`. Quando não
        guarda — entrada de uma versão anterior —, o GC a **preserva**: apagar o
        que não se consegue identificar é o oposto de conservador, e o custo de
        errar para o lado de guardar é disco, não acervo.
        """
        try:
            dados = json.loads(zlib.decompress(arquivo.read_bytes()).decode("utf-8"))
        except Exception as erro:  # noqa: BLE001 — entrada ilegível é lixo, e sai
            log.debug("gc: entrada ilegível %s (%s)", arquivo.name, erro)
            return False
        sha = str(dados.get("sha256") or dados.get("meta", {}).get("sha256", ""))
        if not sha:
            return True
        return sha[:32] in prefixos_vivos
