"""J.e: vault one-way fora das raízes, re-export idêntico, incremental no que mudou."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from segundocerebro.acesso.documento import LeitorDocumento
from segundocerebro.acesso.exportar import main as exportar_cli
from segundocerebro.acesso.vault import ErroVault, conferir_destino, exportar
from segundocerebro.census import Config as CensoConfig
from segundocerebro.census import RootSpec
from segundocerebro.ingest.canonico import renderizar
from segundocerebro.ingest.document import Block, ParsedDoc
from segundocerebro.ingest.parse_store import Chave, ParseStore
from segundocerebro.ingest.parsers import parser_version_for
from segundocerebro.retrieve.glossario import Glossario

from tests.falsos import config_de_raiz

PROJETO = "Projetos/Gama"


def _foto(pasta: Path, *, com_mtime: bool = True) -> dict[str, tuple[int, str] | str]:
    saida: dict[str, tuple[int, str] | str] = {}
    if not pasta.exists():
        return saida
    for arquivo in pasta.rglob("*"):
        if arquivo.is_file():
            digest = sha256(arquivo.read_bytes()).hexdigest()
            rel = arquivo.relative_to(pasta).as_posix()
            saida[rel] = (arquivo.stat().st_mtime_ns, digest) if com_mtime else digest
    return saida


def _gravar(store, caminho: str, texto: str, mtime: float) -> str:
    canonico = renderizar(ParsedDoc(caminho, (Block(("VCE",), texto),)))
    digest = sha256(f"{caminho}\n{texto}".encode()).hexdigest()
    ParseStore(store.diretorio).gravar(Chave(digest, parser_version_for(".md")), canonico)
    store.registrar_documento(
        path=caminho, raiz="acervo", tamanho=len(texto), mtime=mtime, sha256=digest,
        status="ok", n_chunks=0, model_id="falso:8", parser=parser_version_for(".md"),
    )
    return canonico.markdown


def _projeto(store, n: int = 4) -> dict[str, str]:
    textos: dict[str, str] = {}
    for i in range(n):
        vigente = f"{PROJETO}/NN-VCE-{i:03d}.md"
        textos[vigente] = _gravar(
            store, vigente, f"canônico {i} da Várzea Clara Energia e a ISO 42001", 400.0 + i,
        )
        store.registrar_mencoes(vigente, [("norma", "ISO 42001", ""), ("codigo", f"NN-VCE-{i:03d}", "")])
        if i < 2:
            antigo = f"{PROJETO}/NN-VCE-{i:03d}_v0.md"
            textos[antigo] = _gravar(store, antigo, f"rascunho {i} que o vault canônico omite", 100.0)
    store.commit()
    return textos


def _exportar(store, dest: Path, raiz: Path, **kwargs):
    return exportar(
        store, dest, leitor=LeitorDocumento(store), raizes=[raiz],
        pasta=kwargs.pop("pasta", PROJETO), **kwargs,
    )


def test_recusa_destino_dentro_da_raiz(tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    (raiz / "sub").mkdir()
    conferir_destino(tmp_path / "vault", [raiz])
    with pytest.raises(ErroVault) as erro:
        conferir_destino(raiz, [raiz])
    assert erro.value.codigo == "destino_no_acervo"
    with pytest.raises(ErroVault) as erro:
        conferir_destino(raiz / "sub", [raiz])
    assert erro.value.codigo == "destino_no_acervo"
    with pytest.raises(ErroVault) as erro:
        conferir_destino(raiz / "vault-novo", [raiz])
    assert erro.value.codigo == "destino_no_acervo"


def test_recusa_sem_raizes(tmp_path: Path) -> None:
    with pytest.raises(ErroVault) as erro:
        conferir_destino(tmp_path / "vault", [])
    assert erro.value.codigo == "sem_raizes"


def test_nao_escreve_na_raiz_indexada(store, tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    decoy = raiz / "nota.md"
    decoy.write_text("original da VCE, não tocar", encoding="utf-8")
    antes = _foto(raiz)
    _projeto(store)
    _exportar(store, tmp_path / "vault", raiz)
    assert _foto(raiz) == antes
    assert decoy.read_text(encoding="utf-8") == "original da VCE, não tocar"


def test_reexport_idêntico_depois_de_apagar(store, tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    dest = tmp_path / "vault"
    _projeto(store)
    _exportar(store, dest, raiz)
    primeira = _foto(dest, com_mtime=False)
    for arquivo in dest.rglob("*"):
        if arquivo.is_file():
            arquivo.unlink()
    for pasta in sorted((p for p in dest.rglob("*") if p.is_dir()), reverse=True):
        pasta.rmdir()
    _exportar(store, dest, raiz)
    assert _foto(dest, com_mtime=False) == primeira


def test_incremental_so_o_que_mudou(store, tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    dest = tmp_path / "vault"
    _projeto(store, n=3)
    primeira = _exportar(store, dest, raiz)
    assert primeira["escritos"]
    assert not primeira["reusados"]
    foto = _foto(dest)
    segunda = _exportar(store, dest, raiz)
    assert not segunda["escritos"]
    assert segunda["reusados"]
    assert _foto(dest) == foto

    _gravar(store, f"{PROJETO}/NN-VCE-001.md", "canônico 1 da Várzea Clara Energia agora com CT-VCE-2024-0142", 500.0)
    store.registrar_mencoes(
        f"{PROJETO}/NN-VCE-001.md",
        [("norma", "ISO 42001", ""), ("codigo", "CT-VCE-2024-0142", "")],
    )
    store.commit()
    terceira = _exportar(store, dest, raiz)
    assert any("NN-VCE-001" in n for n in terceira["escritos"])
    assert f"{PROJETO}/NN-VCE-000.md" not in terceira["escritos"]
    depois = _foto(dest)
    iguais = [rel for rel, par in foto.items() if depois.get(rel) == par]
    assert f"{PROJETO}/NN-VCE-000.md" in iguais


def test_canonicos_omite_rascunho_e_so_censo(store, tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    (raiz / PROJETO).mkdir(parents=True)
    (raiz / PROJETO / "Novo.txt").write_text("ainda não indexado", encoding="utf-8")
    _projeto(store, n=3)
    saida = _exportar(
        store, tmp_path / "vault", raiz, politica="canonicos",
        censo_cfg=CensoConfig(roots=[RootSpec(name="acervo", path=raiz)]),
    )
    nomes = " ".join(saida["escritos"])
    assert "NN-VCE-000.md" in nomes
    assert "_v0" not in nomes
    assert "Novo.txt" not in nomes
    assert any("Novo.txt" in o["arquivo"] for o in saida["omitidos"])


def test_wikilinks_e_frontmatter(store, tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    dest = tmp_path / "vault"
    _projeto(store, n=3)
    _exportar(store, dest, raiz)
    nota = (dest / "Projetos" / "Gama" / "NN-VCE-000.md").read_text(encoding="utf-8")
    assert nota.startswith("---\n")
    assert "doc_id:" in nota
    assert "arquivo: Projetos/Gama/NN-VCE-000.md" in nota
    assert "view: one-way" in nota
    assert "[[_grafo/ISO 42001|ISO 42001]]" in nota
    hub = (dest / "_grafo" / "ISO 42001.md").read_text(encoding="utf-8")
    assert "[[Projetos/Gama/NN-VCE-000]]" in hub or "NN-VCE-000" in hub
    leia = (dest / "_segundo-cerebro.md").read_text(encoding="utf-8")
    assert "não voltam" in leia
    manifesto = json.loads((dest / ".segundocerebro-vault.json").read_text(encoding="utf-8"))
    assert manifesto["formato"] == "je:1"
    assert "timestamp" not in manifesto and "gerado_em" not in manifesto


def test_glossario_vira_wikilink(store, tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    dest = tmp_path / "vault"
    _gravar(store, f"{PROJETO}/politica.md", "O DPA da VCE cobre o acordo.", 10.0)
    _gravar(store, f"{PROJETO}/contrato.md", "Assinado o DPA em anexo.", 11.0)
    store.commit()
    glossario = Glossario.de_dicionario({"DPA": "acordo de proteção de dados"})
    _exportar(store, dest, raiz, glossario=glossario)
    politica = (dest / "Projetos" / "Gama" / "politica.md").read_text(encoding="utf-8")
    assert "[[glossario#DPA|DPA]]" in politica
    assert "# DPA" in (dest / "glossario.md").read_text(encoding="utf-8")


def test_nao_envolve_identificador_dentro_de_code_fence(store, tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    dest = tmp_path / "vault"
    _gravar(store, f"{PROJETO}/a.md", "texto ISO 42001\n```\nISO 42001\n```\n", 1.0)
    _gravar(store, f"{PROJETO}/b.md", "outra ISO 42001", 2.0)
    store.registrar_mencoes(f"{PROJETO}/a.md", [("norma", "ISO 42001", "")])
    store.registrar_mencoes(f"{PROJETO}/b.md", [("norma", "ISO 42001", "")])
    store.commit()
    _exportar(store, dest, raiz)
    corpo = (dest / "Projetos" / "Gama" / "a.md").read_text(encoding="utf-8")
    fence = corpo.split("```", 2)[1]
    assert "[[" not in fence
    assert "[[_grafo/ISO 42001|ISO 42001]]" in corpo.split("```")[0]


def test_identificador_sozinho_nao_inventa_aresta(store, tmp_path: Path) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    dest = tmp_path / "vault"
    _gravar(store, f"{PROJETO}/unico.md", "só este cita CT-VCE-2024-0142", 1.0)
    store.registrar_mencoes(f"{PROJETO}/unico.md", [("codigo", "CT-VCE-2024-0142", "")])
    store.commit()
    _exportar(store, dest, raiz)
    corpo = (dest / "Projetos" / "Gama" / "unico.md").read_text(encoding="utf-8")
    assert "[[" not in corpo.split("---", 2)[-1]
    assert not (dest / "_grafo").exists()


def test_cli_recusa_destino_no_acervo(store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = tmp_path / "acervo"
    raiz.mkdir()
    _projeto(store, n=1)

    class _Base:
        id = "vce"
        indice = store.diretorio
        glossario = None

        def censo(self):  # noqa: ANN202
            return config_de_raiz(raiz, "acervo")

    class _Conf:
        def base(self, _id=None, **_k):  # noqa: ANN001, ANN202
            return _Base()

    monkeypatch.setattr("segundocerebro.acesso.exportar.carregar", lambda *_a, **_k: _Conf())
    codigo = exportar_cli(["--destino", str(raiz / "vault")])
    assert codigo == 2
    assert not (raiz / "vault").exists()
