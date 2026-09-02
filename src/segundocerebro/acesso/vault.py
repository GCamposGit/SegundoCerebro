"""Exporta a base (ou uma pasta) como vault Markdown — view one-way, `J.e`.

Comando explícito, destino fora das raízes, wikilinks derivados das menções
que já existem. Re-export sobrescreve o que este programa gravou; edições do
usuário no vault não voltam ao acervo nem ao índice. Incremental: só reescreve
nota cuja chave de parse mudou.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..caminhos import resolver_caminho
from ..index.store import Store
from ..ingest.parse_store import Chave
from ..retrieve.glossario import Glossario
from .documento import LeitorDocumento
from .identidade import montar_uri
from .manifesto import listar, vigentes
from .original import ErroLeitura
from .registro import Documento, mencoes_de_caminhos
from .wikilinks import (
    NOTA_GLOSSARIO,
    aplicar,
    caminho_do_hub,
    markup_de_siglas,
    nota_do_glossario,
    nota_do_hub,
    por_identificador,
)

FORMATO = "je:1"
MANIFESTO = ".segundocerebro-vault.json"
LEIA_ME = "_segundo-cerebro.md"
POLITICAS = ("canonicos", "todos")
AVISO = (
    "View one-way descartável. Edições neste vault não voltam ao acervo nem ao "
    "índice. Re-exportar sobrescreve o que o Segundo Cérebro gravou."
)


class ErroVault(ValueError):
    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo


def conferir_destino(destino: Path, raizes: list[Path]) -> Path:
    """Recusa destino dentro de raiz indexada — a classe que o `J.e` fecha."""
    if not raizes:
        raise ErroVault(
            "sem_raizes",
            "Configure as raízes da base. Sem elas não dá para garantir que o "
            "vault fica fora do acervo.",
        )
    alvo = resolver_caminho(Path(destino).expanduser())
    if alvo.exists() and not alvo.is_dir():
        raise ErroVault("destino_nao_e_pasta", "O destino do vault precisa ser uma pasta.")
    for raiz in raizes:
        pasta = resolver_caminho(Path(raiz).expanduser())
        try:
            dentro = alvo == pasta or alvo.is_relative_to(pasta)
        except ValueError:
            dentro = False
        if dentro:
            raise ErroVault(
                "destino_no_acervo",
                "O destino do vault não pode ficar dentro de uma raiz indexada. "
                "Isso escreveria um derivado no acervo (sync, observador, taxonomia). "
                "Escolha uma pasta fora das raízes.",
            )
    return alvo


def exportar(
    store: Store,
    destino: Path,
    *,
    leitor: LeitorDocumento,
    raizes: list[Path],
    pasta: str = "",
    politica: str = "canonicos",
    recursivo: bool = True,
    base: str = "",
    censo_cfg=None,  # noqa: ANN001
    glossario: Glossario | None = None,
    completo: bool = False,
) -> dict[str, Any]:
    """Grava a view. Destino conferido antes de criar pasta ou escrever nota."""
    if politica not in POLITICAS:
        raise ErroVault("politica_invalida", "politica deve ser canonicos ou todos.")
    alvo = conferir_destino(destino, raizes)
    alvo.mkdir(parents=True, exist_ok=True)
    documentos, _erros = listar(store, pasta, recursivo=recursivo, censo_cfg=censo_cfg)
    prontos, omitidos = _carregar(leitor, _escolher(documentos, politica))
    glossario = glossario or Glossario.vazio()
    arquivos = _renderizar(store, prontos, glossario, base)
    antigo = _ler_manifesto(alvo)
    escritos, reusados, removidos = _aplicar(alvo, arquivos, antigo, completo)
    _gravar_manifesto(alvo, pasta, politica, {rel: chave for rel, (_t, chave) in arquivos.items()})
    return _envelope(
        alvo, pasta, politica, escritos, reusados, removidos, omitidos, prontos, documentos,
    )


def _escolher(documentos: list[Documento], politica: str) -> list[Documento]:
    if politica == "canonicos":
        canonico = vigentes(documentos)
        return [d for d in documentos if (d.raiz, d.caminho) in canonico]
    return list(documentos)


def _carregar(
    leitor: LeitorDocumento, escolhidos: list[Documento],
) -> tuple[list[tuple[Documento, str, Chave]], list[dict[str, str]]]:
    prontos: list[tuple[Documento, str, Chave]] = []
    omitidos: list[dict[str, str]] = []
    for doc in escolhidos:
        if not doc.doc_id:
            omitidos.append({"arquivo": doc.caminho, "raiz": doc.raiz,
                             "motivo": doc.sem_id or "sem identidade no índice"})
            continue
        try:
            chave, canonico, _alvo = leitor.carregar_documento(doc)
        except ErroLeitura as erro:
            omitidos.append({"arquivo": doc.caminho, "raiz": doc.raiz,
                             "motivo": str(erro), "codigo": erro.codigo, "id": doc.doc_id})
            continue
        prontos.append((doc, canonico.markdown, chave))
    return prontos, omitidos


def _nota_relativa(doc: Documento, ocupados: set[str]) -> str:
    partes = doc.caminho.replace("\\", "/").split("/")
    nome = partes[-1]
    stem = nome.rsplit(".", 1)[0] if "." in nome else nome
    rel = "/".join((*partes[:-1], f"{stem}.md")) if partes[:-1] else f"{stem}.md"
    reservados = {LEIA_ME, NOTA_GLOSSARIO, MANIFESTO}
    if rel in ocupados or rel in reservados or rel.startswith("_grafo/"):
        rel = "/".join((*partes[:-1], f"{stem}-{doc.doc_id}.md")) if partes[:-1] else f"{stem}-{doc.doc_id}.md"
    ocupados.add(rel)
    return rel


def _data(mtime: float) -> str:
    if not mtime:
        return ""
    return datetime.fromtimestamp(mtime, tz=timezone.utc).date().isoformat()


def _yaml(valor: str) -> str:
    if (not valor or valor[0] in "-?:{}[]&*!|>%@`'\""
            or any(c in valor for c in ":#\n")
            or valor.lower() in {"true", "false", "null", "yes", "no"}):
        return json.dumps(valor, ensure_ascii=False)
    return valor


def _frontmatter(doc: Documento, chave: Chave, base: str) -> str:
    tags = [p for p in doc.caminho.replace("\\", "/").split("/")[:-1] if p]
    linhas = ["---", f"doc_id: {doc.doc_id}"]
    if base and doc.doc_id:
        linhas.append(f"uri: {montar_uri(base, doc.doc_id)}")
    linhas.extend([
        f"arquivo: {_yaml(doc.caminho)}",
        f"raiz: {_yaml(doc.raiz)}",
        f"sha256: {doc.sha256}",
    ])
    if doc.mtime:
        linhas.append(f"mtime: {_data(doc.mtime)}")
    linhas.extend([
        f"parser: {_yaml(chave.parser)}",
        f"rota: {_yaml(chave.rota)}",
        "view: one-way",
    ])
    if tags:
        linhas.append("tags:")
        for tag in tags:
            linhas.append(f"  - {_yaml(tag)}")
    linhas.extend(["---", ""])
    return "\n".join(linhas)


def _leia_me() -> str:
    return (
        "---\nview: one-way\n---\n\n"
        "# Vault exportado pelo Segundo Cérebro\n\n"
        f"{AVISO}\n\n"
        "O original continua sendo a fonte: abra, envie e cite o arquivo de lá.\n\n"
        "Gerado por `py -m segundocerebro.acesso.exportar`.\n"
    )


def _chave_texto(texto: str) -> str:
    return sha256(texto.encode("utf-8")).hexdigest()[:32]


def _renderizar(
    store: Store,
    prontos: list[tuple[Documento, str, Chave]],
    glossario: Glossario,
    base: str,
) -> dict[str, tuple[str, str]]:
    ocupados: set[str] = set()
    notas = {doc.caminho: _nota_relativa(doc, ocupados) for doc, _md, _ch in prontos}
    mencoes = mencoes_de_caminhos(store, [doc.caminho for doc, _md, _ch in prontos])
    mapa = por_identificador(mencoes)
    arquivos: dict[str, tuple[str, str]] = {}
    arquivos[LEIA_ME] = (_leia_me(), _chave_texto(_leia_me()))
    ocorrencias: dict[str, list[str]] = {}
    for doc, markdown, chave in prontos:
        rel = notas[doc.caminho]
        siglas = markup_de_siglas(markdown, glossario)
        for sigla, _markup in siglas:
            ocorrencias.setdefault(sigla, []).append(rel)
        corpo = aplicar(markdown, doc.caminho, mapa, mencoes.get(doc.caminho, ()), siglas)
        texto = _frontmatter(doc, chave, base) + corpo.rstrip() + "\n"
        arquivos[rel] = (texto, _chave_texto(texto))
    for (tipo, valor), caminhos in sorted(mapa.items()):
        rel = caminho_do_hub(valor)
        alvos = [notas[c] for c in caminhos if c in notas]
        texto = nota_do_hub(tipo, valor, alvos)
        arquivos[rel] = (texto, _chave_texto(texto))
    glossario_md = nota_do_glossario(glossario, ocorrencias)
    if glossario_md:
        arquivos[NOTA_GLOSSARIO] = (glossario_md, _chave_texto(glossario_md))
    return arquivos


def _ler_manifesto(destino: Path) -> dict[str, str]:
    caminho = destino / MANIFESTO
    if not caminho.is_file():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if dados.get("formato") != FORMATO or not isinstance(dados.get("arquivos"), dict):
        return {}
    return {str(k): str(v) for k, v in dados["arquivos"].items()}


def _gravar_atomico(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8", newline="\n")
    os.replace(tmp, caminho)


def _aplicar(
    destino: Path,
    arquivos: dict[str, tuple[str, str]],
    antigo: dict[str, str],
    completo: bool,
) -> tuple[list[str], list[str], list[str]]:
    escritos: list[str] = []
    reusados: list[str] = []
    for rel, (texto, chave) in arquivos.items():
        alvo = destino / Path(*rel.split("/"))
        if (not completo and antigo.get(rel) == chave and alvo.is_file()):
            reusados.append(rel)
            continue
        _gravar_atomico(alvo, texto)
        escritos.append(rel)
    removidos: list[str] = []
    for rel in antigo:
        if rel in arquivos:
            continue
        alvo = destino / Path(*rel.split("/"))
        if alvo.is_file():
            alvo.unlink()
            removidos.append(rel)
    return sorted(escritos), sorted(reusados), sorted(removidos)


def _gravar_manifesto(destino: Path, pasta: str, politica: str, arquivos: dict[str, str]) -> None:
    payload = {
        "formato": FORMATO,
        "aviso": AVISO,
        "pasta": pasta,
        "politica": politica,
        "arquivos": dict(sorted(arquivos.items())),
    }
    texto = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    caminho = destino / MANIFESTO
    if caminho.is_file() and caminho.read_text(encoding="utf-8") == texto:
        return
    _gravar_atomico(caminho, texto)


def _envelope(
    destino: Path, pasta: str, politica: str,
    escritos: list[str], reusados: list[str], removidos: list[str],
    omitidos: list[dict[str, str]],
    prontos: list[tuple[Documento, str, Chave]],
    documentos: list[Documento],
) -> dict[str, Any]:
    saida: dict[str, Any] = {
        "destino": str(destino),
        "pasta": pasta.replace("\\", "/").strip().strip("/") or "(raiz da base)",
        "politica": politica,
        "escritos": escritos,
        "reusados": reusados,
        "removidos": removidos,
        "omitidos": omitidos,
        "notas": len(prontos),
        "completo": True,
        "fronteira": AVISO,
    }
    if not documentos:
        saida["aviso"] = "nenhum documento encontrado sob esta pasta."
    elif not prontos:
        saida["aviso"] = (
            "nenhum documento desta seleção tem texto canônico disponível. "
            "Indexe os arquivos so_censo antes de exportar."
        )
    return saida
