"""Módulo e função não crescem sem que alguém escreva por quê.

O `Q3` do guia de engenharia foi rebaixado em 25/08/2026 com o argumento certo —
*"nenhum leigo tropeça em `indexer.py` ter 1.143 linhas"* — e com uma ação que era
só uma frase: *"regra em `colaboracao.md`: novo módulo ≤ ~500 linhas"*. Entre
aquele dia e 29/08 o `indexer.py` foi de 1.143 para **1.753** linhas. Regra
escrita sem quem a confira é conselho, e conselho não segura arquivo que cresce um
pacote por vez.

O custo é nosso, não do usuário, e é real: arquivo grande é o pior caso para
edição por agente — mais contexto queimado por leitura, mais conflito entre os
dois setups, diff que ninguém revisa de verdade. **34 commits deste repositório
passam de 500 linhas alteradas.**

O desenho é o de `SEM_FATIA_PROPRIA` e o de `SEM_FIXTURE_POSSIVEL`: a lacuna
declarada é a única que não vira dívida. As tabelas abaixo são a **escada** —
cada entrada guarda o tamanho medido no dia em que entrou, e só pode diminuir.
Um módulo novo acima do teto reprova; um módulo listado que cresça reprova; e um
que caia abaixo do teto tem de sair da tabela, senão a escada vira teto.

As costuras propostas para cada um dos grandes estão no `ROADMAP.md`, pacote
`Q16`, levantadas em 29/08/2026 — decompor não precisa de releitura, precisa de
um PR.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACOTE = Path(__file__).resolve().parent.parent / "src" / "segundocerebro"

TETO_DE_MODULO = 500
TETO_DE_FUNCAO = 60

ACIMA_DO_TETO: dict[str, int] = {
    "index/indexer.py": 1368,
    "index/store.py": 1425,
    "config.py": 1086,
    "painel/app.py": 929,
    "census.py": 988,
    "index/calibracao.py": 897,
    "ingest/parsers/sheets.py": 870,
    "index/estimativa.py": 691,
    "retrieve/hybrid.py": 657,
    "index/migrar_identidade.py": 601,
}
"""Os módulos que já estavam grandes, com o tamanho de 29/08/2026 como teto.

`indexer.py` chegou aqui com 1.753 e saiu da passada com 1.368: `cli.py`,
`trava.py`, `repesca.py`, `resultado.py` e `travas.py` saíram dele. O resto
espera o `Q16`.

`census.py` (974 → 978) e `sheets.py` (868 → 870) subiram no mesmo dia, e o
teste os pegou: são as três linhas de `# noqa: DTZ00x` com o motivo da hora
local escrito ao lado. Subir o degrau porque a linha nova é justificada é o uso
certo da tabela; subi-lo porque o arquivo cresceu de novo não é, e é essa
diferença que a mensagem de falha obriga alguém a escrever.

`store.py` desceu de 1.274 para 1.137 em 30/08/2026, e o gatilho foi o `J.b1`
precisar de um `CREATE INDEX` num arquivo que a tabela não deixa crescer. `ESQUEMA`
saiu para `index/esquema.py` com os comentários verbatim. É o uso que a escada
espera: quando o arquivo grande precisa de linha nova, o que sai dele é a parte
com razão de mudar própria — não a linha nova que entra."""

FUNCOES_ACIMA_DO_TETO: dict[str, int] = {
    "index/indexer.py::indexar": 1042,
    "painel/app.py::criar_app": 762,
    "index/indexer.py::aplicar": 273,
    "ingest/reader.py::parse_file": 150,
    "mcp/server.py::construir": 144,
    "index/cli.py::construir_parser": 127,
    "census.py::render_markdown": 119,
    "index/indexer.py::main": 101,
    "index/isolamento.py::parse_isolado": 101,
    "mcp/registrar.py::main": 101,
    "index/smoke_cuda.py::main": 89,
    "config_escrita.py::como_toml": 88,
    "painel/app.py::conectar": 87,
    "retrieve/hybrid.py::search": 111,
    "index/indexer.py::embeber_um": 65,
    "index/migrar_identidade.py::_recriar_chunks": 74,
    "index/reconciliar.py::reconciliar": 70,
    "index/store.py::registrar_quarentena": 71,
    "retrieve/hybrid.py::buscar_chunks": 73,
    "acesso/registro.py::estrutura_de": 72,
    "ingest/parsers/sheets.py::_blocos_de_digesto": 83,
    "ingest/report.py::render_markdown": 77,
    "config.py::carregar": 77,
    "census.py::iter_files": 73,
    "ingest/parsers/sheets.py::_emitir_linhas_de_aba": 73,
    "index/esforco.py::aplicar": 71,
    "ingest/converters/libreoffice.py::converter": 72,
    "index/isolamento.py::_limitar_ram_windows": 68,
    "index/smoke_cuda.py::_smoke_rerank": 67,
    "ingest/parsers/text.py::blocos_de_markdown": 64,
    "ingest/parsers/word.py::parse_docx": 63,
    "census.py::main": 61,
}
"""As funções longas, com o tamanho de 29/08/2026 como teto.

`indexar` com 1.042 linhas e 24 parâmetros e `criar_app` com 815 são as duas que
importam; as outras 24 estão entre 60 e 150 e são leitura linear. `main` do
indexador caiu de 224 para 101 quando o `argparse` saiu para `cli.py`, e
`construir_parser` é o que ele virou — 124 das suas 127 linhas são
`add_argument`, que não decompõe em nada mais legível.

`construir` desceu de 148 para 144 em 30/08/2026: as duas tools do `J.c-mapa`
custavam duas linhas nela, e `_instrucoes` — a única parte com razão de mudar
própria, o que o cliente lê para escolher **entre bases** — saiu antes. As tools
mesmas nasceram em `mcp/leitura.py`, que é o que a tabela força e o que evita a
função de 200 linhas com quatro descriptions dentro."""


def _modulos() -> dict[str, int]:
    return {
        arquivo.relative_to(PACOTE).as_posix(): len(
            arquivo.read_text(encoding="utf-8").splitlines()
        )
        for arquivo in PACOTE.rglob("*.py")
    }


def _funcoes() -> dict[str, int]:
    achadas: dict[str, int] = {}
    for arquivo in PACOTE.rglob("*.py"):
        rel = arquivo.relative_to(PACOTE).as_posix()
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
        for no in ast.walk(arvore):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fim = getattr(no, "end_lineno", no.lineno)
                achadas[f"{rel}::{no.name}"] = fim - no.lineno + 1
    return achadas


def test_modulo_novo_nao_nasce_grande() -> None:
    novos = sorted(
        f"{nome} ({tam} linhas)"
        for nome, tam in _modulos().items()
        if tam > TETO_DE_MODULO and nome not in ACIMA_DO_TETO
    )
    assert not novos, (
        f"módulo acima de {TETO_DE_MODULO} linhas que não estava declarado: {novos}. "
        "Decomponha, ou acrescente a ACIMA_DO_TETO com o motivo escrito."
    )


def test_modulo_grande_so_diminui() -> None:
    tamanhos = _modulos()
    cresceram = sorted(
        f"{nome}: {tamanhos[nome]} linhas, teto declarado {teto}"
        for nome, teto in ACIMA_DO_TETO.items()
        if tamanhos.get(nome, 0) > teto
    )
    assert not cresceram, (
        f"módulo já grande que cresceu: {cresceram}. A tabela é escada, não teto — "
        "acrescente o que for novo em arquivo próprio."
    )


def test_a_escada_nao_guarda_degrau_ja_vencido() -> None:
    tamanhos = _modulos()
    resolvidos = sorted(
        f"{nome} ({tamanhos.get(nome, 0)} linhas)"
        for nome in ACIMA_DO_TETO
        if tamanhos.get(nome, 0) <= TETO_DE_MODULO
    )
    assert not resolvidos, f"{resolvidos} já cabe no teto — tirar de ACIMA_DO_TETO"

    sumiram = sorted(nome for nome in ACIMA_DO_TETO if nome not in tamanhos)
    assert not sumiram, f"{sumiram} não existe mais — tirar de ACIMA_DO_TETO"


def test_funcao_nova_nao_nasce_longa() -> None:
    novas = sorted(
        f"{nome} ({tam} linhas)"
        for nome, tam in _funcoes().items()
        if tam > TETO_DE_FUNCAO and nome not in FUNCOES_ACIMA_DO_TETO
    )
    assert not novas, (
        f"função acima de {TETO_DE_FUNCAO} linhas que não estava declarada: {novas}. "
        "Extraia, ou acrescente a FUNCOES_ACIMA_DO_TETO com o motivo escrito."
    )


def test_funcao_longa_so_diminui() -> None:
    tamanhos = _funcoes()
    cresceram = sorted(
        f"{nome}: {tamanhos[nome]} linhas, teto declarado {teto}"
        for nome, teto in FUNCOES_ACIMA_DO_TETO.items()
        if tamanhos.get(nome, 0) > teto
    )
    assert not cresceram, f"função já longa que cresceu: {cresceram}"
