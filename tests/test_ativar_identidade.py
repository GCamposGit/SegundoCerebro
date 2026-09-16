"""FND-01b: ativar o índice migrado aponta `indice` sem reescrever o config."""

from __future__ import annotations

from pathlib import Path

import pytest

from segundocerebro.config import carregar
from segundocerebro.index.ativar_identidade import AtivacaoRecusada, ativar, main
from segundocerebro.index.backup_manifesto import BackupRecusado
from segundocerebro.index.migrar_identidade import migrar
from segundocerebro.index.ocorrencia import usa_ocorrencia
from segundocerebro.index.store import Store

from tests.test_migrar_identidade import _legado


def _config(tmp_path: Path, indice_rel: str = "index") -> Path:
    raiz = tmp_path / "docs"
    raiz.mkdir()
    (raiz / "nota.md").write_text("texto", encoding="utf-8")
    texto = f"""versao = 1
# comentario que a ativação não pode apagar

[[base]]
id = "padrao"
indice = "{indice_rel}"
raizes = [
    {{ nome = "principal", caminho = "{raiz.as_posix()}" }},
]

[[base]]
id = "arquivo"
indice = "outro"
raizes = [
    {{ nome = "principal", caminho = "{raiz.as_posix()}" }},
]
"""
    caminho = tmp_path / "config.toml"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def test_ativar_aponta_indice_preserva_comentario_e_outra_base(tmp_path: Path) -> None:
    origem = _legado(tmp_path)
    destino = tmp_path / "novo"
    migrar(origem, destino)
    config = _config(tmp_path, "index")
    (tmp_path / "index").mkdir()

    anterior = ativar(config, destino)

    assert anterior == (tmp_path / "index").resolve()
    texto = config.read_text(encoding="utf-8")
    assert "comentario que a ativação não pode apagar" in texto
    conf = carregar(config, validar=True)
    assert conf.base("padrao").indice.resolve() == destino.resolve()
    assert conf.base("arquivo").indice == tmp_path / "outro"
    store = Store(destino, 8)
    try:
        assert usa_ocorrencia(store.con)
    finally:
        store.fechar()


def test_ativar_e_idempotente(tmp_path: Path) -> None:
    origem = _legado(tmp_path)
    destino = tmp_path / "novo"
    migrar(origem, destino)
    config = _config(tmp_path, "novo")

    primeira = ativar(config, destino)
    segunda = ativar(config, destino)

    assert primeira == segunda == destino.resolve()


def test_ativar_recusa_destino_legado(tmp_path: Path) -> None:
    legado = _legado(tmp_path)
    config = _config(tmp_path)
    with pytest.raises(AtivacaoRecusada, match="schema legado"):
        ativar(config, legado)
    assert 'indice = "index"' in config.read_text(encoding="utf-8")


def test_ativar_recusa_destino_ausente(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(BackupRecusado):
        ativar(config, tmp_path / "inexistente")


def test_cli_recusa_com_codigo_2(tmp_path: Path) -> None:
    config = _config(tmp_path)
    codigo = main(["--config", str(config), "--destino", str(tmp_path / "falha")])
    assert codigo == 2
