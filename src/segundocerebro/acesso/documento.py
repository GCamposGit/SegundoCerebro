"""Leitura integral por Parse Store, nunca por concatenação de chunks.

Só documentos conhecidos e com hash. Miss usa o parser isolado existente, com
limites e sem hidratação; não indexa nem escreve no registro. Um parse em curso
por servidor limita o custo de chamadas concorrentes; hits não esperam por ele.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any

from ..config import LimitesDeIndexacao
from ..caminhos import resolver_caminho
from ..index import isolamento, orcamento
from ..index.store import Store
from ..ingest.canonico import ParseCanonico, renderizar
from ..ingest.document import ParseStatus
from ..ingest.ocr import VERSAO as OCR_VERSAO
from ..ingest.parse_cache import canonicos_disponiveis
from ..ingest.parse_store import Chave, ParseStore, chave_de
from ..ingest.parsers import parser_version_for
from ..retrieve.familias import chave_de_familia, versao_de
from .identidade import conferir_base, interpretar, montar_uri
from .original import (
    ErroLeitura, caminho_relativo, conferir_cache, conferir_original, configuracao, localizar,
)
from .pagina_documento import CHARS_PADRAO, decodificar_cursor, paginar
from .registro import Documento, resolver

# Uma chamada interativa não deve iniciar um job de horas. O indexador continua
# disponível para arquivos acima destes tetos, sem alterar a política dele.
MAX_ORIGINAL_MB = 50
TIMEOUT_SEGUNDOS = 60


def _resolver(store: Store, documento: str, base_id: str, cfg=None) -> Documento:
    ref = interpretar(documento)
    erro = ref.erro or conferir_base(ref, base_id)
    if erro:
        raise ErroLeitura("referencia_invalida", erro)
    if ref.caminho:
        ref = replace(ref, caminho=caminho_relativo(ref.caminho))
    doc = resolver(store, ref)
    if doc is None or not doc.doc_id:
        raise ErroLeitura("sem_documento", "Documento sem identidade no índice. Confira list_folder e indexe-o primeiro.")
    if ref.caminho:
        _conferir_ambiguidade(doc, cfg)
    return doc


def _conferir_ambiguidade(doc: Documento, cfg) -> None:
    """Um so_censo de outra raiz não pode virar o arquivo homônimo do índice."""
    for raiz in cfg.roots if cfg else ():
        if raiz.name == doc.raiz:
            continue
        try:
            candidato = localizar(replace(doc, raiz=raiz.name), cfg)
        except ErroLeitura:
            continue  # Link/exclusão não constitui outro documento acessível.
        if candidato is not None and candidato.is_file():
            raise ErroLeitura("caminho_ambiguo", "Há esse caminho em mais de uma raiz. Use o id ou URI do documento indexado; arquivos so_censo precisam de indexação.")


def _obter(indice: Path, doc: Documento) -> tuple[Chave, ParseCanonico] | None:
    ocr = doc.parser.startswith("ocr:")
    for chave, canonico in canonicos_disponiveis(
        indice, doc.sha256, Path(doc.caminho).suffix.lower(), ocr=ocr,
    ):
        if not ocr or canonico.meta.get("fonte") == "ocr":
            return chave, canonico
    return None


def _reler(indice: Path, doc: Documento, base: Any, alvo: Path | None) -> tuple[Chave, ParseCanonico]:
    if alvo is None:
        raise ErroLeitura("cache_ausente", "Parse Store ausente. Configure as raízes desta base para reconstruí-lo do original.")
    extensao = alvo.suffix.lower()
    limites = getattr(base, "limites", LimitesDeIndexacao()).como_mapa()
    limites[extensao] = min(limites.get(extensao, MAX_ORIGINAL_MB), MAX_ORIGINAL_MB)
    ocr = doc.parser.startswith("ocr:")
    resultado = isolamento.parse_isolado(
        str(alvo), allow_hydration=False, retries=0, limites_mb=limites,
        limite_planilha_mb=MAX_ORIGINAL_MB, timeout=TIMEOUT_SEGUNDOS,
        ram_mb=orcamento.derivar(orcamento.medir()).ram_parse_mb, ocr=ocr,
    )
    if resultado.status not in {ParseStatus.OK, ParseStatus.EMPTY} or resultado.doc is None:
        raise ErroLeitura(resultado.status.value, "Não foi possível extrair o original com os limites de leitura. Confira o estado do arquivo; para processamento demorado, use o indexador.")
    if resultado.sha256 != doc.sha256:
        raise ErroLeitura("documento_alterado", "O conteúdo do original mudou. Reindexe e reinicie sem cursor.")
    if ocr and resultado.doc.meta.get("fonte") != "ocr":
        raise ErroLeitura("ocr_indisponivel", "Este documento exige o OCR usado na indexação. Restaure o motor antes de reconstruir o cache.")
    conferir_original(alvo, doc)
    parser = (resultado.doc.meta.get("parser") or OCR_VERSAO) if ocr else parser_version_for(extensao)
    chave = chave_de(doc.sha256, parser, resultado.doc.meta)
    canonico = renderizar(resultado.doc)
    ParseStore(indice).gravar(chave, canonico)
    return chave, canonico


def _metadados(doc: Documento, canonico: ParseCanonico, chave: Chave, base_id: str) -> dict[str, Any]:
    return {
        "id": doc.doc_id, "uri": montar_uri(base_id, doc.doc_id) if base_id else "",
        "arquivo": doc.caminho, "raiz": doc.raiz, "titulo": Path(doc.caminho).stem,
        "caminho_preferido": doc.caminhos[0], "sha256": doc.sha256,
        "mtime": doc.mtime, "indexado_em": doc.indexado_em, "bytes_original": doc.tamanho,
        "total_chars": canonico.chars, "total_blocos": len(canonico.blocos),
        "paginas": doc.paginas or canonico.meta.get("paginas") or None,
        "parser": chave.parser, "rota": chave.rota, "familia_real": doc.familia_real,
        "familia_de_versoes": {"raiz": doc.raiz, "chave": chave_de_familia(doc.caminho)},
        "versao_no_nome": list(versao_de(doc.caminho) or ()) or None,
    }


def _limitacoes(canonico: ParseCanonico) -> list[str]:
    """Expõe limitações conhecidas sem copiar mensagens internas ou caminhos."""
    avisos = {
        "abas_em_digesto": "Há abas representadas por digesto de valores, não por todas as células.",
        "digesto_parcial": "Há digestos parciais; nem todos os valores distintos foram preservados.",
        "truncadas": "O extrator sinalizou conteúdo truncado no original.",
        "sem_valor_em_cache": "Há fórmulas sem valor calculado disponível.",
        "paginas_ocr": "Há páginas sinalizadas para OCR; confira a rota de extração.",
        "aviso": "O extrator sinalizou uma limitação adicional; confira o original.",
    }
    return [mensagem for chave, mensagem in avisos.items() if canonico.meta.get(chave)]


class LeitorDocumento:
    def __init__(self, store: Store, base: Any = None) -> None:
        self.store, self.base = store, base
        self._parse = Lock()

    def _canonico(self, doc: Documento, alvo: Path | None) -> tuple[Chave, ParseCanonico]:
        indice = self.store.diretorio
        existente = _obter(indice, doc)
        if existente:
            return existente
        if not self._parse.acquire(blocking=False):
            raise ErroLeitura("ocupado", "Outra extração está em andamento. Tente novamente após a conclusão.")
        try:
            return _obter(indice, doc) or _reler(indice, doc, self.base, alvo)
        finally:
            self._parse.release()

    def carregar_documento(self, doc: Documento) -> tuple[Chave, ParseCanonico, Path | None]:
        """Canônico completo da versão indexada; mesmos portões de `ler`, sem paginar."""
        cfg = configuracao(self.base)
        conferir_cache(self.store.diretorio, cfg)
        alvo = localizar(doc, cfg)
        estado = conferir_original(alvo, doc)
        chave, canonico = self._canonico(doc, alvo)
        if conferir_original(alvo, doc) != estado:
            raise ErroLeitura("documento_alterado", "O original mudou durante a leitura. Reinicie após reindexar.")
        return chave, canonico, alvo

    def ler(self, documento: str, cursor: str | None = None, max_chars: int = CHARS_PADRAO) -> dict[str, Any]:
        decodificar_cursor(cursor)  # Recusa barata antes de qualquer parse.
        if type(max_chars) is not int or max_chars < 1:
            raise ErroLeitura("orcamento_invalido", "max_chars deve ser um inteiro positivo.")
        base_id = getattr(self.base, "id", "") or ""
        doc = _resolver(self.store, documento, base_id, configuracao(self.base))
        chave, canonico, alvo = self.carregar_documento(doc)
        identidade = json.dumps([str(resolver_caminho(self.store.diretorio)), base_id, doc.raiz,
                                 doc.caminho, doc.sha256, chave.digest(),
                                 conferir_original(alvo, doc)])
        saida = paginar(canonico, identidade, cursor=cursor, max_chars=max_chars)
        saida["documento"] = _metadados(doc, canonico, chave, base_id)
        saida["fronteira"] = "Texto canônico extraído da versão indexada, não reprodução visual do original. Tabelas, imagens e OCR podem ter limitações. Use arquivo/raiz para citar o original."
        saida["original_conferido"] = "tamanho_e_datas" if alvo else "nao_configurado"
        saida["limitacoes_extracao"] = _limitacoes(canonico)
        if doc.digitalizado and canonico.meta.get("fonte") != "ocr":
            saida["aviso_ocr"] = "Há sinal de digitalização; texto nativo pode não cobrir todas as páginas. OCR não foi acionado nesta leitura."
        if not canonico.markdown:
            saida["aviso"] = "Nenhum texto extraído; isto não comprova que o original esteja vazio."
        return saida
