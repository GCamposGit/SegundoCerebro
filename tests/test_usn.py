"""R5.1: catch-up from the USN journal, without a live watcher.

The class is "events while the process was off". Watchdog cannot see them.
A fake journal proves the contract on every CI OS; a real NTFS journal
proves we actually talk to the volume — mock of the ioctl would be the
F3.5-D failure mode again.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from segundocerebro.index.usn import (
    FILE_ATTRIBUTE_DIRECTORY,
    Cursor,
    EstadoVolume,
    Journal,
    Registro,
    disponivel,
    parse_registros,
    varrer,
)
from tests.falsos import FonteFalsa


def _raiz(tmp_path: Path) -> tuple[Path, Path, FonteFalsa]:
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    indice = tmp_path / "indice"
    indice.mkdir()
    fonte = FonteFalsa(journal=Journal(journal_id=1, first_usn=0, next_usn=10))
    return raiz, indice, fonte


def test_parse_v2_com_nome() -> None:
    nome = "a.txt".encode("utf-16-le")
    rec_len = (60 + len(nome) + 7) & ~7
    buf = bytearray(rec_len)
    struct.pack_into("<IHH", buf, 0, rec_len, 2, 0)
    struct.pack_into("<Q", buf, 8, 42)
    struct.pack_into("<I", buf, 40, 0x100)
    struct.pack_into("<I", buf, 52, 0x20)
    struct.pack_into("<HH", buf, 56, len(nome), 60)
    buf[60 : 60 + len(nome)] = nome
    recs, nxt = parse_registros(struct.pack("<q", 99) + bytes(buf))
    assert nxt == 99
    assert recs[0].frn == 42
    assert recs[0].name == "a.txt"
    assert recs[0].reason == 0x100


def test_parse_v3_sem_nome_como_o_ioctl_nao_privilegiado() -> None:
    """Unprivileged V3 records arrive with FileNameLength=0. Path is OpenFileById."""
    buf = bytearray(80)
    struct.pack_into("<IHH", buf, 0, 80, 3, 0)
    struct.pack_into("<Q", buf, 8, 7)
    struct.pack_into("<I", buf, 56, 0x100)
    struct.pack_into("<I", buf, 68, 0x20)
    struct.pack_into("<HH", buf, 72, 0, 76)
    recs, _nxt = parse_registros(struct.pack("<q", 1) + bytes(buf))
    assert recs[0].name == ""
    assert recs[0].frn == 7
    assert recs[0].attrs == 0x20


def test_parse_pula_versao_desconhecida() -> None:
    buf = bytearray(60)
    struct.pack_into("<IHH", buf, 0, 60, 4, 0)
    recs, nxt = parse_registros(struct.pack("<q", 5) + bytes(buf))
    assert recs == []
    assert nxt == 5


def test_cursor_nao_arredonda_journal_id(tmp_path: Path) -> None:
    """journal_id > 2^53. A JSON number would round and skip the wrong records."""
    jid = 133360880118351860
    Cursor(volumes={"C:\\": EstadoVolume(jid, 10)}).gravar(tmp_path)
    de_volta = Cursor.carregar(tmp_path)
    assert de_volta.volumes["C:\\"].journal_id == jid
    bruto = (tmp_path / "usn.json").read_text(encoding="utf-8")
    assert "133360880118351860" in bruto


def test_primeira_subida_nao_repete_o_journal(tmp_path: Path) -> None:
    raiz, indice, fonte = _raiz(tmp_path)
    alvo = raiz / "nota.txt"
    alvo.write_text("PO-VCE-007\n", encoding="utf-8")
    fonte.registros = [Registro(frn=1, reason=0x100, attrs=0x20)]
    fonte.caminhos = {1: alvo}
    assert varrer([raiz], indice, fonte=fonte) == []
    cursor = Cursor.carregar(indice)
    assert cursor.volumes[fonte.volume].next_usn == 10


def test_mil_alteracoes_com_observador_desligado_voltam(tmp_path: Path) -> None:
    """Aceite do dossiê: 1k files change while off → catch-up recovers all."""
    raiz, indice, fonte = _raiz(tmp_path)
    varrer([raiz], indice, fonte=fonte)

    caminhos: dict[int, Path] = {}
    registros: list[Registro] = []
    for i in range(1000):
        alvo = raiz / f"vce-usn-{i:04d}.txt"
        alvo.write_text(f"PO-VCE-{i:04d}\n", encoding="utf-8")
        caminhos[i] = alvo
        registros.append(Registro(frn=i, reason=0x100, attrs=0x20))
    fonte.registros = registros
    fonte.caminhos = caminhos
    fonte.journal = Journal(journal_id=1, first_usn=0, next_usn=20)

    achados = varrer([raiz], indice, fonte=fonte)
    nomes = {p.name for p in achados}
    assert len(nomes) == 1000
    assert "vce-usn-0000.txt" in nomes
    assert "vce-usn-0999.txt" in nomes


def test_journal_recriado_nao_mente(tmp_path: Path) -> None:
    raiz, indice, fonte = _raiz(tmp_path)
    alvo = raiz / "nota.txt"
    alvo.write_text("x\n", encoding="utf-8")
    varrer([raiz], indice, fonte=fonte)
    fonte.journal = Journal(journal_id=2, first_usn=0, next_usn=50)
    fonte.registros = [Registro(frn=1, reason=0x100, attrs=0x20)]
    fonte.caminhos = {1: alvo}
    assert varrer([raiz], indice, fonte=fonte) == []
    assert Cursor.carregar(indice).volumes[fonte.volume].journal_id == 2


def test_journal_expirado_nao_mente(tmp_path: Path) -> None:
    raiz, indice, fonte = _raiz(tmp_path)
    varrer([raiz], indice, fonte=fonte)
    fonte.expirado = True
    fonte.journal = Journal(journal_id=1, first_usn=99, next_usn=100)
    assert varrer([raiz], indice, fonte=fonte) == []
    assert Cursor.carregar(indice).volumes[fonte.volume].next_usn == 100


def test_diretorio_nao_vira_candidato(tmp_path: Path) -> None:
    raiz, indice, fonte = _raiz(tmp_path)
    varrer([raiz], indice, fonte=fonte)
    fonte.registros = [Registro(frn=1, reason=0x100, attrs=FILE_ATTRIBUTE_DIRECTORY)]
    fonte.caminhos = {1: raiz}
    fonte.journal = Journal(journal_id=1, first_usn=0, next_usn=20)
    assert varrer([raiz], indice, fonte=fonte) == []


def test_arquivo_fora_da_raiz_e_ignorado(tmp_path: Path) -> None:
    raiz, indice, fonte = _raiz(tmp_path)
    varrer([raiz], indice, fonte=fonte)
    fora = tmp_path / "lado.txt"
    fora.write_text("x\n", encoding="utf-8")
    fonte.registros = [Registro(frn=1, reason=0x100, attrs=0x20)]
    fonte.caminhos = {1: fora}
    fonte.journal = Journal(journal_id=1, first_usn=0, next_usn=20)
    assert varrer([raiz], indice, fonte=fonte) == []


@pytest.mark.skipif(os.name == "nt", reason="o no-op é o caminho POSIX")
def test_sem_nt_varrer_e_vazio(tmp_path: Path) -> None:
    assert varrer([tmp_path], tmp_path) == []


@pytest.mark.skipif(os.name != "nt", reason="journal USN é Windows/NTFS")
def test_journal_real_recupera_mil_arquivos(tmp_path: Path) -> None:
    if not disponivel(tmp_path):
        pytest.skip("volume sem journal USN legível")
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    indice = tmp_path / "indice"
    indice.mkdir()
    varrer([raiz], indice)

    esperados = []
    for i in range(1000):
        alvo = raiz / f"vce-usn-{i:04d}.txt"
        alvo.write_text(f"PO-VCE-{i:04d}\n", encoding="utf-8")
        esperados.append(alvo.name)

    achados = {p.name for p in varrer([raiz], indice)}
    faltando = [n for n in esperados if n not in achados]
    assert not faltando, f"USN perdeu {len(faltando)} de 1000: {faltando[:5]}"


@pytest.mark.skipif(os.name != "nt", reason="journal USN é Windows/NTFS")
def test_journal_real_nao_mente_apagado(tmp_path: Path) -> None:
    """Unprivileged records have no name. OpenFileById of a delete fails — we
    must not invent a path, and must not claim the delete was recovered."""
    if not disponivel(tmp_path):
        pytest.skip("volume sem journal USN legível")
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    indice = tmp_path / "indice"
    indice.mkdir()
    varrer([raiz], indice)

    vivo = raiz / "vivo-vce.txt"
    morto = raiz / "morto-vce.txt"
    vivo.write_text("PO-VCE-007\n", encoding="utf-8")
    morto.write_text("CT-VCE-2024-0142\n", encoding="utf-8")
    morto.unlink()

    achados = {p.name for p in varrer([raiz], indice)}
    assert "vivo-vce.txt" in achados
    assert "morto-vce.txt" not in achados
