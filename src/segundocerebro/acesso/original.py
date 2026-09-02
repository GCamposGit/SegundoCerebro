"""Fronteira de leitura sob demanda: somente originais conhecidos desta base.

O registro autoriza a identidade, a configuração autoriza a raiz e o reader
continua sendo o único portão que abre bytes. Nunca se aceita um caminho
absoluto vindo do cliente. As verificações cobrem links estáveis; a pasta local
não é uma sandbox contra alguém que a modifique concorrentemente com malícia.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ..census import Config
from ..caminhos import resolver_caminho
from .registro import Documento


class ErroLeitura(ValueError):
    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo


def caminho_relativo(caminho: str) -> str:
    normal = caminho.replace("\\", "/")
    if normal.startswith("./"):
        normal = normal[2:]
    if (not normal or "\x00" in normal or ":" in normal
            or PureWindowsPath(normal).drive or normal.startswith("/")
            or any(p in {"", ".", ".."} for p in normal.split("/"))):
        raise ErroLeitura("caminho_invalido", "Use o caminho relativo devolvido por list_folder.")
    return normal


def configuracao(base: Any) -> Config | None:
    return base.censo() if callable(getattr(base, "censo", None)) else None


def conferir_cache(indice: Path, cfg: Config | None) -> None:
    """Mesmo o descarte de cache corrompido não pode escrever no acervo."""
    resolvido = resolver_caminho(indice)
    cache = resolver_caminho(indice / "parse_store")
    if not cache.is_relative_to(resolvido):
        raise ErroLeitura("cache_inseguro", "O Parse Store deve ficar dentro do índice.")
    if cfg and any(cache.is_relative_to(resolver_caminho(r.path)) for r in cfg.roots):
        raise ErroLeitura("cache_no_acervo", "Mova o diretório do índice para fora das raízes do acervo.")


def localizar(doc: Documento, cfg: Config | None) -> Path | None:
    relativo = caminho_relativo(doc.caminho)
    if cfg is None or not cfg.roots:
        return None  # Cache da versão indexada pode ser lido sem original.
    raizes = [r for r in cfg.roots if r.name == doc.raiz]
    if len(raizes) != 1:
        raise ErroLeitura("raiz_indisponivel", "A raiz deste documento não está configurada nesta base.")
    partes = PurePosixPath(relativo)
    if (any(cfg.excluded_dir(p) for p in partes.parts[:-1])
            or cfg.excluded_file(partes.name, str(partes.parent) if partes.parent != PurePosixPath('.') else "")):
        raise ErroLeitura("documento_excluido", "O documento está excluído pela configuração atual.")
    raiz = resolver_caminho(raizes[0].path)
    caminho = raiz
    for parte in partes.parts:
        caminho = caminho / parte
        if caminho.is_symlink() or caminho.is_junction():
            raise ErroLeitura("link_recusado", "O caminho contém link ou junction não enumerado pelo censo.")
    alvo = resolver_caminho(caminho)
    if not alvo.is_relative_to(raiz):
        raise ErroLeitura("fora_da_base", "O caminho aponta para fora da raiz autorizada.")
    return alvo


def conferir_original(alvo: Path | None, doc: Documento) -> str:
    """Stat, não hidratação. A leitura serve a versão indexada, não uma cópia ao vivo."""
    if alvo is None:
        return "sem_raizes"
    st = alvo.stat()
    if not alvo.is_file():
        raise ErroLeitura("original_indisponivel", "O original não é um arquivo regular.")
    if st.st_size != doc.tamanho or st.st_mtime != doc.mtime:
        raise ErroLeitura("documento_alterado", "O original mudou desde a indexação. Reindexe e reinicie sem cursor.")
    return f"{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}"
