"""A suíte não entrega estado de um teste para o próximo.

Existe por um incidente com nome e número. Em 28/08/2026 o PR #48 acrescentou um
teste que chamava `aplicar_provider("cuda")` — código de produto, que escreve em
`os.environ`. O teste tinha `monkeypatch.delenv(..., raising=False)` antes, e
isso parece isolamento e não é: o monkeypatch restaura o que **ele** mexeu, e
sobre uma variável ausente ele não registra nada. `SEGUNDOCEREBRO_PROVIDER=cuda`
sobrevivia ao teste, ao módulo e à sessão inteira do pytest.

O sintoma aparecia em outro arquivo: as seis primeiras chamadas a `indexar()`
depois dele — todas em `tests/test_watcher.py`, que vem depois na ordem
alfabética — falhavam com `RuntimeError: Não achei placa NVIDIA`, enquanto o
arquivo passava verde quando rodado sozinho. E o modo de falha era assimétrico
entre os dois setups: no desktop, que tem placa, `diagnosticar()` diz `ok` e a
suíte inteira ficava verde. Quem só roda lá nunca via.

O que este arquivo prova é a **guarda**, não o caso: `ambiente_devolvido`, em
`tests/conftest.py`, tira uma foto de `os.environ` antes de cada teste e a
devolve depois. Os dois testes abaixo são deterministicamente ordenados — pytest
executa na ordem de definição dentro de um módulo — e é essa ordem que constitui
a prova: o primeiro suja, o segundo confere que a sujeira não chegou.
"""

from __future__ import annotations

import os

SENTINELA = "SEGUNDOCEREBRO_TESTE_VAZAMENTO"


def test_um_teste_escreve_no_ambiente_como_o_produto_escreveria() -> None:
    """Escrita direta em `os.environ`, sem monkeypatch — igual à do produto."""
    os.environ[SENTINELA] = "vazou"
    assert os.environ[SENTINELA] == "vazou"


def test_o_teste_seguinte_nao_recebe_o_que_o_anterior_escreveu() -> None:
    assert SENTINELA not in os.environ, (
        "a fixture `ambiente_devolvido` de tests/conftest.py parou de restaurar "
        "`os.environ` — sem ela, escrita de produção dentro de um teste envenena "
        "todos os que rodarem depois, e o sintoma aparece em outro arquivo"
    )


# --------------------------------------------------------------------------- #
# Q17 — arquivo de teste não é módulo de apoio


def test_nenhum_arquivo_de_teste_exporta_infraestrutura() -> None:
    """Nenhum arquivo importa de outro cujo nome comece com `test_`.

    Pacote `Q17`, 30/08/2026. `tests/test_index.py` era um conftest informal:
    exportava `DIM`, `EmbedderFalso`, `chunk` e `corpus` para 18 sítios em 14
    arquivos, três deles em `eval/`. Qualquer refator ali quebrava os quatorze,
    e ninguém abre um arquivo chamado `test_index.py` esperando encontrar a
    infraestrutura da suíte.

    O que resolve não é ter movido os quatro símbolos: é esta varredura, que
    reprova o próximo. Dublê que é classe ou função vai para `tests/falsos.py`;
    fixture vai para um `conftest.py`.
    """
    import ast
    from pathlib import Path

    RAIZ = Path(__file__).resolve().parent.parent
    faltas: list[str] = []
    for pasta in ("tests", "eval"):
        for arquivo in sorted((RAIZ / pasta).rglob("*.py")):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
            for no in ast.walk(arvore):
                # `ast.Import` junto de `ast.ImportFrom`: a primeira versão via só
                # a segunda, e `import tests.test_index as ti` era invisível para
                # ela. Achado por revisão em 30/08/2026 — a mesma classe de novo.
                if isinstance(no, ast.ImportFrom):
                    modulos = [no.module] if no.module else []
                elif isinstance(no, ast.Import):
                    modulos = [a.name for a in no.names]
                else:
                    continue
                for modulo in modulos:
                    alvo = modulo.split(".")[-1]
                    if alvo.startswith("test_") and alvo != arquivo.stem:
                        rel = arquivo.relative_to(RAIZ).as_posix()
                        faltas.append(f"{rel}:{no.lineno} importa `{modulo}`")
    assert not faltas, (
        "arquivo de teste sendo usado como módulo de apoio:\n  "
        + "\n  ".join(faltas)
        + "\n\nDublê que é classe ou função vai para `tests/falsos.py`; "
        "fixture vai para um `conftest.py` (Q17)."
    )
