"""Text from OLE compound files (.doc, .ppt) without opening Word/PowerPoint.

Parsers still receive bytes, never a path — `reader.py` is the only place that
touches the filesystem. COM automation is slower, locks the live corpus, and
needs a windowed Office install; this extractor is good enough to make a
`.doc`/`.ppt` searchable and cheap enough to run on thousands of files.

Quality is below native OOXML parsers. That is accepted: the alternative on
this desktop was 13k `sem_parser` rows and a knowledge base that could not
see the bulk of a consulting archive.
"""

from __future__ import annotations

import io
import struct

LETRAS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝàáâãäåæçèéêëìíîïñòóôõöùúûüý0123456789")

ASSINATURA_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
"""Magic do Compound File. Igual à de `natureza.ASSINATURAS`; duplicada para
este módulo não importar o detector — parser não decide natureza."""


def e_ole2(dados: bytes) -> bool:
    """True só pela assinatura. Truncado ou corrompido ainda é 'parece OLE'."""
    return dados.startswith(ASSINATURA_OLE)


def _ole():
    import olefile

    return olefile


def _stream(ole, *nomes: str) -> bytes | None:  # noqa: ANN001
    for nome in nomes:
        if ole.exists(nome):
            return ole.openstream(nome).read()
    return None


def _run_e_texto(run: list[str], minimo: int = 4) -> str | None:
    if len(run) < minimo:
        return None
    texto = "".join(run)
    letras = sum(1 for c in texto if c in LETRAS)
    if letras < minimo or letras / max(1, len(texto)) < 0.35:
        return None
    return texto.strip()


def texto_utf16_de_binario(dados: bytes, *, minimo: int = 4) -> str:
    """Pull UTF-16LE runs that look like language, not structure."""
    partes: list[str] = []
    run: list[str] = []
    i = 0
    n = len(dados)
    while i + 1 < n:
        code = int.from_bytes(dados[i : i + 2], "little")
        if code in (0x07, 0x0B, 0x0C, 0x0D, 0x0A):  # Word paragraph / cell marks
            if run:
                achado = _run_e_texto(run, minimo)
                if achado:
                    partes.append(achado)
                run = []
            i += 2
            continue
        if 32 <= code < 0xD800 or 0xE000 <= code <= 0xFFFD:
            run.append(chr(code))
            i += 2
            continue
        if run:
            achado = _run_e_texto(run, minimo)
            if achado:
                partes.append(achado)
            run = []
        i += 2 if code == 0 or code > 255 else 1
    if run:
        achado = _run_e_texto(run, minimo)
        if achado:
            partes.append(achado)
    return "\n".join(partes)


def texto_de_doc(dados: bytes) -> str:
    if not e_ole2(dados):
        raise ValueError("conteúdo não é OLE2")
    olefile = _ole()
    ole = olefile.OleFileIO(io.BytesIO(dados))
    try:
        stream = _stream(ole, "WordDocument")
        if not stream:
            return ""
        return texto_utf16_de_binario(stream)
    finally:
        ole.close()


# MS-PPT record types that carry visible text.
_PPT_TEXTCHARS = 0x0FA0
_PPT_TEXTBYTES = 0x0FA8
_PPT_CSTRING = 0x0FBA


def _ppt_registros(buf: bytes) -> list[str]:
    partes: list[str] = []
    offset = 0
    n = len(buf)
    while offset + 8 <= n:
        ver_inst, rec_type, rec_len = struct.unpack_from("<HHI", buf, offset)
        offset += 8
        if rec_len < 0 or offset + rec_len > n:
            break
        payload = buf[offset : offset + rec_len]
        offset += rec_len
        rec_ver = ver_inst & 0x000F
        if rec_ver == 0xF:
            partes.extend(_ppt_registros(payload))
            continue
        if rec_type == _PPT_TEXTCHARS or rec_type == _PPT_CSTRING:
            texto = payload.decode("utf-16-le", errors="ignore").strip("\x00").strip()
            if texto:
                partes.append(texto)
        elif rec_type == _PPT_TEXTBYTES:
            texto = payload.decode("latin-1", errors="ignore").strip("\x00").strip()
            if texto:
                partes.append(texto)
    return partes


def texto_de_ppt(dados: bytes) -> str:
    if not e_ole2(dados):
        raise ValueError("conteúdo não é OLE2")
    olefile = _ole()
    ole = olefile.OleFileIO(io.BytesIO(dados))
    try:
        stream = _stream(ole, "PowerPoint Document", "Pictures")
        if not stream:
            # some decks keep a Current User + PowerPoint Document pair
            stream = _stream(ole, "Current User")
            extra = _stream(ole, "PowerPoint Document")
            if extra:
                stream = (stream or b"") + extra
        if not stream:
            return ""
        partes = _ppt_registros(stream)
        if partes:
            return "\n".join(partes)
        return texto_utf16_de_binario(stream)
    finally:
        ole.close()
