"""Testes do diagnóstico operacional somente leitura (FND-08a)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from segundocerebro.index.cuda_runtime import (
    TIMEOUT_SONDA_GPU_S,
    DiagnosticoCuda,
)
from segundocerebro.index.cuda_runtime import listar_gpus as listar_gpus_real
from segundocerebro.index.diagnostico import (
    ItemDiagnostico,
    RelatorioDiagnostico,
    diagnosticar_base,
    main,
)
from segundocerebro.index.integridade import DiagnosticoIntegridade
from segundocerebro.index.trava import TravaDeIndice


@pytest.fixture(autouse=True)
def ambiente_diagnostico_isolado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isola completamente o diagnóstico operacional de hardware e subprocessos lentos.

    Evita chamadas a nvidia-smi, varreduras de pastas do sistema por executáveis
    e imports dinâmicos de DLLs pesadas durante a execução da suíte de testes.
    """
    monkeypatch.setattr("segundocerebro.index.cuda_runtime.listar_gpus", lambda: [])
    monkeypatch.setattr("segundocerebro.index.cuda_runtime._listar_providers", lambda: [])
    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice.encontrar_soffice", lambda: None
    )
    monkeypatch.setattr("segundocerebro.ingest.ocr.backend_disponivel", lambda: None)


def _criar_config_sintetico(tmp_path: Path, nome_base: str = "padrao") -> tuple[Path, Path, Path]:
    """Cria ambiente temporário com config.toml, pasta raiz e pasta de índice."""
    raiz = tmp_path / "acervo"
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "documento.txt").write_text("conteúdo simulado", encoding="utf-8")

    indice = tmp_path / "indice"
    indice.mkdir(parents=True, exist_ok=True)

    caminho_cfg = tmp_path / "config.toml"
    conteudo_cfg = f"""versao = 1

[padrao]
modelo = "e5-large"

[padrao.chunking]
max_chars = 1000
overlap_chars = 200

[[base]]
id = "{nome_base}"
indice = "{indice.as_posix()}"
raizes = [
    {{ nome = "principal", caminho = "{raiz.as_posix()}" }}
]
"""
    caminho_cfg.write_text(conteudo_cfg, encoding="utf-8")
    return caminho_cfg, raiz, indice


def _preparar_indice_minimo(indice: Path, model_id: str = "e5-large") -> None:
    """Gera um registro.db funcional e consistente."""
    reg = indice / "registro.db"
    con = sqlite3.connect(reg)
    con.execute(
        """
        CREATE TABLE documentos (
            path TEXT PRIMARY KEY,
            raiz TEXT NOT NULL,
            tamanho INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            n_chunks INTEGER NOT NULL,
            model_id TEXT,
            chunker TEXT,
            parser TEXT,
            digitalizado INTEGER DEFAULT 0,
            indexado_em TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE chunks (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            trilha TEXT NOT NULL,
            locator TEXT NOT NULL,
            kind TEXT NOT NULL,
            texto TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE execucoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iniciada_em TEXT NOT NULL,
            encerrada_em TEXT,
            model_id TEXT NOT NULL,
            chunker TEXT NOT NULL,
            config TEXT,
            documentos INTEGER,
            chunks INTEGER,
            status TEXT NOT NULL
        )
        """
    )
    con.execute(
        "INSERT INTO documentos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("doc1.txt", "principal", 100, 1.0, "a" * 64, "ok", 1, model_id, "v1", "p1", 0, "agora"),
    )
    con.execute(
        "INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
        ("c1", "doc1.txt", 0, "", "p. 1", "paragrafo", "texto chunk"),
    )
    con.execute(
        "INSERT INTO execucoes VALUES (1, 'inicio', 'fim', ?, 'v1', '{}', 1, 1, 'concluida')",
        (model_id,),
    )
    con.commit()
    con.close()


def test_diagnostico_base_saudavel_retorna_ok(tmp_path: Path) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)

    assert relatorio.status_geral == "saudavel"
    assert relatorio.base == "padrao"
    assert relatorio.duracao_ms >= 0
    codigos = {it.codigo for it in relatorio.itens}
    assert "config_valida" in codigos
    assert "raiz_acessivel" in codigos
    assert "indice_presente" in codigos
    assert "escrita_inativa" in codigos


def test_diagnostico_detecta_config_inexistente(tmp_path: Path) -> None:
    cfg_path = tmp_path / "inexistente.toml"
    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)

    assert relatorio.status_geral == "inoperante"
    item = next(it for it in relatorio.itens if it.codigo == "config_invalida")
    assert item.severidade == "erro"
    assert "não foi encontrado" in item.mensagem
    assert "config.example.toml" in item.acao


def test_diagnostico_detecta_config_malformada(tmp_path: Path) -> None:
    cfg_path = tmp_path / "invalido.toml"
    cfg_path.write_text("[[[secao_invalida:::", encoding="utf-8")

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)
    assert relatorio.status_geral == "inoperante"
    item = next(it for it in relatorio.itens if it.codigo == "config_invalida")
    assert item.severidade == "erro"


def test_diagnostico_detecta_base_inexistente(tmp_path: Path) -> None:
    cfg_path, _, _ = _criar_config_sintetico(tmp_path, nome_base="minha_base")

    relatorio = diagnosticar_base("outra_base", caminho_config=cfg_path)
    assert relatorio.status_geral == "inoperante"
    item = next(it for it in relatorio.itens if it.codigo == "base_inexistente")
    assert item.severidade == "erro"
    assert "outra_base" in item.mensagem


def test_diagnostico_detecta_raiz_inacessivel(tmp_path: Path) -> None:
    cfg_path, raiz, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    # Remove o arquivo e a pasta raiz
    (raiz / "documento.txt").unlink()
    raiz.rmdir()

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)
    assert relatorio.status_geral == "inoperante"
    item = next(it for it in relatorio.itens if it.codigo == "raiz_inacessivel")
    assert item.severidade == "erro"
    assert "não existe" in item.mensagem


def test_diagnostico_detecta_indice_ausente(tmp_path: Path) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    # Não cria registro.db
    assert not (indice / "registro.db").exists()

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)
    # Índice ausente é aviso de prontidão, não erro fatal de configuração
    assert relatorio.status_geral == "atencao"
    item = next(it for it in relatorio.itens if it.codigo == "indice_ausente")
    assert item.severidade == "aviso"
    assert "segundocerebro.index.indexer" in item.acao


def test_diagnostico_detecta_escrita_ativa(tmp_path: Path) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    trava = TravaDeIndice(indice)
    with trava:
        relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)

    assert any(it.codigo == "escrita_ativa" for it in relatorio.itens)
    item = next(it for it in relatorio.itens if it.codigo == "escrita_ativa")
    assert item.severidade == "aviso"
    assert "indexação viva" in item.mensagem


def test_diagnostico_detecta_modelo_divergente(tmp_path: Path) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    # Grava o índice com modelo diferente do config ("e5-large")
    _preparar_indice_minimo(indice, model_id="modelo-legado")

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)
    assert any(it.codigo == "modelo_divergente" for it in relatorio.itens)
    item = next(it for it in relatorio.itens if it.codigo == "modelo_divergente")
    assert item.severidade == "aviso"
    assert "modelo-legado" in item.mensagem


def test_diagnostico_detecta_modelo_incompativel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    monkeypatch.setattr(
        "segundocerebro.index.diagnostico.diagnosticar_cuda",
        lambda **_k: DiagnosticoCuda(False, "sem_gpu", "GPU não encontrada"),
    )

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)
    assert relatorio.status_geral == "inoperante"
    item = next(it for it in relatorio.itens if it.codigo == "modelo_incompativel")
    assert item.severidade == "erro"


def test_sonda_gpu_tem_timeout_e_falha_fechada(monkeypatch: pytest.MonkeyPatch) -> None:
    observado: dict[str, float] = {}

    def travar(*_args: object, **kwargs: object) -> None:
        observado["timeout"] = float(kwargs["timeout"])
        raise subprocess.TimeoutExpired("nvidia-smi", kwargs["timeout"])

    monkeypatch.setattr("segundocerebro.index.cuda_runtime.subprocess.run", travar)

    assert listar_gpus_real() == []
    assert observado["timeout"] == TIMEOUT_SONDA_GPU_S


def test_diagnostico_detecta_parser_indisponivel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    def quebrar_soffice() -> None:
        raise PermissionError("acesso negado ao binário")

    monkeypatch.setattr(
        "segundocerebro.ingest.converters.libreoffice.encontrar_soffice",
        quebrar_soffice,
    )

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)
    item = next(it for it in relatorio.itens if it.codigo == "parser_indisponivel")
    assert item.severidade == "aviso"
    assert "acesso negado" in item.mensagem


def test_diagnostico_profundo_detecta_divergencia_integridade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    resultado_integro = DiagnosticoIntegridade(
        integro=True,
        status="ok",
        chunks_sqlite=1,
        vetores_lancedb=1,
        orfaos=0,
        faltantes=0,
        duplicados=0,
        modelos_divergentes=0,
        pendentes_rascunho=0,
        lancedb_disponivel=True,
    )

    resultado_divergente = DiagnosticoIntegridade(
        integro=False,
        status="divergente",
        chunks_sqlite=1,
        vetores_lancedb=0,
        orfaos=0,
        faltantes=1,
        duplicados=0,
        modelos_divergentes=0,
        pendentes_rascunho=0,
        lancedb_disponivel=True,
        detalhe="Discrepância simulada",
    )

    # Diagnóstico rápido: não executa checagem profunda
    relatorio_rapido = diagnosticar_base("padrao", caminho_config=cfg_path, profundo=False)
    assert not any(it.codigo.startswith("integridade_") for it in relatorio_rapido.itens)

    # Diagnóstico profundo íntegro
    monkeypatch.setattr(
        "segundocerebro.index.diagnostico_integridade.diagnosticar_integridade",
        lambda _store, **_k: resultado_integro,
    )
    relatorio_ok = diagnosticar_base("padrao", caminho_config=cfg_path, profundo=True)
    item_ok = next(it for it in relatorio_ok.itens if it.codigo == "integridade_ok")
    assert item_ok.severidade == "ok"
    assert relatorio_ok.status_geral == "saudavel"

    # Diagnóstico profundo divergente
    monkeypatch.setattr(
        "segundocerebro.index.diagnostico_integridade.diagnosticar_integridade",
        lambda _store, **_k: resultado_divergente,
    )
    relatorio_profundo = diagnosticar_base("padrao", caminho_config=cfg_path, profundo=True)
    item_integridade = next(
        it for it in relatorio_profundo.itens if it.codigo == "integridade_divergente"
    )
    assert item_integridade.severidade == "erro"
    assert relatorio_profundo.status_geral == "inoperante"


def test_diagnostico_profundo_nao_abre_store_gravavel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)
    resultado = DiagnosticoIntegridade(True, "ok", 1, 1, 0, 0, 0, 0, 0, True)

    def gravacao_proibida(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Store gravável foi instanciado")

    monkeypatch.setattr("segundocerebro.index.store.Store.__init__", gravacao_proibida)
    monkeypatch.setattr(
        "segundocerebro.index.diagnostico_integridade.diagnosticar_integridade",
        lambda _store, **_k: resultado,
    )

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path, profundo=True)
    assert relatorio.status_geral == "saudavel"


def test_diagnostico_profundo_e_adiado_durante_escrita(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    def nao_deveria_abrir(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("integridade abriu durante escrita")

    monkeypatch.setattr(
        "segundocerebro.index.diagnostico_integridade.diagnosticar_integridade",
        nao_deveria_abrir,
    )
    with TravaDeIndice(indice):
        relatorio = diagnosticar_base("padrao", caminho_config=cfg_path, profundo=True)

    assert relatorio.status_geral == "atencao"
    assert any(it.codigo == "integridade_adiada" for it in relatorio.itens)


def test_diagnostico_profundo_propaga_cancelamento_e_progresso(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)
    eventos: list[tuple[int, int]] = []
    cancelado = DiagnosticoIntegridade(False, "cancelado", 1, -1, 0, 0, 0, 0, 0, True)

    def verificar(_store: object, **kwargs: object) -> DiagnosticoIntegridade:
        cancelar = kwargs["cancelar"]
        progresso = kwargs["progresso"]
        assert callable(cancelar) and cancelar()
        assert callable(progresso)
        progresso(4, 8)
        return cancelado

    monkeypatch.setattr(
        "segundocerebro.index.diagnostico_integridade.diagnosticar_integridade",
        verificar,
    )
    relatorio = diagnosticar_base(
        "padrao",
        caminho_config=cfg_path,
        profundo=True,
        cancelar=lambda: True,
        progresso=lambda atual, total: eventos.append((atual, total)),
    )

    assert relatorio.status_geral == "atencao"
    assert eventos == [(4, 8)]
    assert any(it.codigo == "integridade_cancelada" for it in relatorio.itens)


def test_diagnostico_nunca_importa_encoder_nem_le_conteudo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A regra de ouro: diagnóstico operacional deve ser rápido e leve."""
    cfg_path, raiz, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    monkeypatch.setitem(sys.modules, "fastembed", None)
    monkeypatch.setitem(sys.modules, "fastembed.embedding", None)
    documento = raiz / "documento.txt"
    abrir_original = Path.open

    def abrir_sem_original(self: Path, *args: object, **kwargs: object):
        if self == documento:
            raise AssertionError("diagnóstico abriu conteúdo da origem")
        return abrir_original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", abrir_sem_original)

    # Executa diagnóstico — não deve lançar falha de import do fastembed
    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)
    assert relatorio.status_geral == "saudavel"


def test_diagnostico_erro_interno_retorna_inoperante(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path, _, _ = _criar_config_sintetico(tmp_path)

    def crash(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("falha imprevista na raiz")

    monkeypatch.setattr(
        "segundocerebro.index.diagnostico._conferir_raizes",
        crash,
    )

    relatorio = diagnosticar_base("padrao", caminho_config=cfg_path)
    assert relatorio.status_geral == "inoperante"
    item = next(it for it in relatorio.itens if it.codigo == "erro_interno")
    assert item.severidade == "erro"
    assert "falha imprevista na raiz" in item.mensagem


def test_exportar_suporte_anonimiza_caminhos_e_segredos() -> None:
    relatorio = RelatorioDiagnostico(
        base="confidencial",
        status_geral="atencao",
        itens=[
            ItemDiagnostico(
                codigo="caminho_sensivel",
                severidade="aviso",
                mensagem=r"Falha no arquivo C:\Users\usuario\AcervoSintetico\config.toml",
                acao=r"Consulte /home/usuario/projetos/arquivo.pdf",
                evidencia={
                    "consulta": "contrato secreto",
                    "token": "sk-segredosegredo",
                },
            )
        ],
    )
    anonimizado = relatorio.exportar_suporte()

    assert "usuario" not in anonimizado.lower()
    assert r"C:\Users" not in anonimizado
    assert "/home" not in anonimizado
    assert "contrato secreto" not in anonimizado
    assert "sk-segredosegredo" not in anonimizado
    assert "confidencial" not in anonimizado
    assert "<DIR_PRIVADO>" in anonimizado


def test_cli_diagnosticar_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg_path, _, indice = _criar_config_sintetico(tmp_path)
    _preparar_indice_minimo(indice)

    # Executa CLI em modo texto
    codigo = main(["--config", str(cfg_path), "--base", "padrao"])
    assert codigo == 0
    saida = capsys.readouterr().out
    assert "Diagnóstico da base 'padrao': ✅ SAUDÁVEL" in saida

    # Executa CLI em modo JSON
    codigo_json = main(["--config", str(cfg_path), "--base", "padrao", "--json"])
    assert codigo_json == 0
    saida_json = capsys.readouterr().out
    dados = json.loads(saida_json)
    assert dados["base"] == "padrao"
    assert dados["status_geral"] == "saudavel"

    # Executa CLI em modo exportar-suporte
    codigo_sup = main(["--config", str(cfg_path), "--base", "padrao", "--exportar-suporte"])
    assert codigo_sup == 0
    saida_sup = capsys.readouterr().out
    assert "status_geral" in saida_sup


def test_cli_modulo_help_nao_sonda_hardware() -> None:
    """O comando documentado em docs/comecar.md tem de responder sem nvidia-smi."""
    proc = subprocess.run(
        [sys.executable, "-m", "segundocerebro.index.diagnostico", "--help"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--profundo" in proc.stdout
    assert "--exportar-suporte" in proc.stdout
