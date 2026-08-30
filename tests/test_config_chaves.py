"""A porta de entrada da configuração não aceita em silêncio o que não entende.

Pacote `Q11`, 29/08/2026. `_secao` já recusava chave desconhecida dentro de
`pesos`, `busca`, `chunking`, `limites`, `[maquina]` e `exclude`; **fora dessas
seis o silêncio era total** — chave direto num `[[base]]`, seção de topo
inventada, chave em `[indexacao]`, chave em `[padrao]` e chave extra numa
entrada de `raizes` eram lidas e descartadas.

Este arquivo é a **classe generalizada** do pacote, e são duas metades que se
apoiam. Nenhuma das duas repete uma lista escrita à mão:

1. `test_chave_inventada_recusada_em_todo_nivel` percorre os níveis de
   aninhamento e exige que uma chave inventada levante em cada um. Os níveis de
   seção saem de `Base.__dataclass_fields__` — seção nova nasce coberta.
2. `test_*_declara_o_que_le` compara a lista **declarada** (`CHAVES_DE_BASE`,
   `CHAVES_DE_TOPO`, `CHAVES_DE_RAIZ`) contra as chaves que a função leitora
   realmente lê, derivadas do AST do próprio `config.py`. Chave nova no leitor
   sem entrar na lista viraria "desconhecida" para o usuário — que é o defeito
   oposto e igualmente silencioso. Chave declarada que ninguém lê é declaração
   morta.

A varredura de AST é o mesmo instrumento de `tests/test_pacote.py`, e pela mesma
razão: a lista que importa é a que o código executa, não a que alguém lembrou de
atualizar.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from segundocerebro import config as mod
from segundocerebro.config import (
    CHAVES_DE_BASE,
    CHAVES_DE_PADRAO,
    CHAVES_DE_RAIZ,
    CHAVES_DE_TOPO,
    CHAVES_DE_TOPO_LEGADO,
    Base,
    ErroDeConfig,
    Indexacao,
    carregar,
)

SEM_AMBIENTE: dict[str, str] = {}
INVENTADA = "chave_que_ninguem_le"


def escrever(tmp_path: Path, texto: str) -> Path:
    caminho = tmp_path / "config.toml"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


BASE_MINIMA = """
versao = 1

[[base]]
id = "padrao"
indice = "index"
"""


# --------------------------------------------------------------------------- #
# 1. Todo nível de aninhamento recusa chave inventada


def _secoes_de_base() -> tuple[str, ...]:
    """As seções aninhadas de um `[[base]]`, derivadas do modelo.

    Um campo de `Base` cujo padrão é uma dataclass **e** cujo nome é uma chave
    do TOML é uma seção. `exclude_declarado` é dataclass e não entra: seu nome
    não é chave do arquivo. Seção nova entra nesta lista sozinha.
    """
    return tuple(
        nome
        for nome, campo in Base.__dataclass_fields__.items()
        if nome in CHAVES_DE_BASE and dataclasses.is_dataclass(campo.default)
    )


def _niveis() -> list[tuple[str, str]]:
    """(rótulo, TOML) — cada um com uma chave inventada num nível diferente."""
    niveis = [
        (
            "topo",
            f'versao = 1\n{INVENTADA} = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n',
        ),
        (
            "secao de topo",
            f'versao = 1\n\n[{INVENTADA}]\nx = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n',
        ),
        (
            "[padrao]",
            f'versao = 1\n\n[padrao]\n{INVENTADA} = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n',
        ),
        (
            "[[base]]",
            f'versao = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n{INVENTADA} = 1\n',
        ),
        (
            "[indexacao]",
            f'versao = 1\n\n[indexacao]\n{INVENTADA} = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n',
        ),
        (
            "entrada de raizes",
            'versao = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n'
            f'raizes = [{{ caminho = ".", {INVENTADA} = 1 }}]\n',
        ),
        (
            "[maquina]",
            f'versao = 1\n\n[maquina]\n{INVENTADA} = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n',
        ),
        (
            "exclude",
            'versao = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n'
            f"[base.exclude]\n{INVENTADA} = []\n",
        ),
    ]
    for secao in _secoes_de_base():
        niveis.append(
            (
                f"[base.{secao}]",
                'versao = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n'
                f"[base.{secao}]\n{INVENTADA} = 1\n",
            )
        )
        niveis.append(
            (
                f"[padrao.{secao}]",
                f"versao = 1\n\n[padrao.{secao}]\n{INVENTADA} = 1\n\n"
                '[[base]]\nid = "padrao"\nindice = "index"\n',
            )
        )
    return niveis


@pytest.mark.parametrize("rotulo,texto", _niveis(), ids=lambda v: v if isinstance(v, str) else "")
def test_chave_inventada_recusada_em_todo_nivel(tmp_path, rotulo, texto):
    """Erro que cita a chave, em todo nível — nunca o padrão em silêncio."""
    with pytest.raises(ErroDeConfig) as erro:
        carregar(escrever(tmp_path, texto), ambiente=SEM_AMBIENTE)
    assert INVENTADA in str(erro.value), f"{rotulo}: a mensagem não cita a chave errada"


def test_o_minimo_continua_carregando(tmp_path):
    """A régua da metade de cima: sem chave inventada, nada mudou."""
    cfg = carregar(escrever(tmp_path, BASE_MINIMA), ambiente=SEM_AMBIENTE)
    assert cfg.bases[0].id == "padrao"


def test_secoes_de_base_nao_ficou_vazia():
    """Se a derivação parar de achar seção, o teste de cima vira teatro."""
    assert set(_secoes_de_base()) == {"pesos", "busca", "chunking", "limites"}


# --------------------------------------------------------------------------- #
# 2. A lista declarada é a que a função leitora executa


def _arvore() -> ast.Module:
    return ast.parse(Path(inspect.getsourcefile(mod)).read_text(encoding="utf-8"))


def _funcoes(arvore: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)}


def _literal(no: ast.AST) -> str | None:
    return no.value if isinstance(no, ast.Constant) and isinstance(no.value, str) else None


def _chaves_lidas(
    arvore: ast.Module, funcao: str, alvo: str, vistas: frozenset[str] = frozenset()
) -> set[str]:
    """Toda chave literal lida do mapa `alvo` dentro de `funcao`.

    Enxerga as quatro formas que este módulo usa — `alvo["x"]`, `alvo.get("x")`,
    `"x" in alvo` e `_secao(alvo, "x", ...)` — e **desce** nas funções que
    recebem o mapa inteiro como argumento (`_excludes(dados, ...)` lê
    `exclude` lá dentro). Sem essa descida, a lista derivada teria um buraco
    exatamente onde a leitura é indireta, que é onde ninguém olha.
    """
    funcoes = _funcoes(arvore)
    corpo = funcoes.get(funcao)
    if corpo is None or funcao in vistas:
        return set()
    vistas = vistas | {funcao}
    achadas: set[str] = set()

    def e_alvo(no: ast.AST) -> bool:
        return isinstance(no, ast.Name) and no.id == alvo

    for no in ast.walk(corpo):
        if isinstance(no, ast.Subscript) and e_alvo(no.value):
            if (chave := _literal(no.slice)) is not None:
                achadas.add(chave)
        elif isinstance(no, ast.Compare) and any(isinstance(o, ast.In) for o in no.ops):
            if any(e_alvo(c) for c in no.comparators) and (chave := _literal(no.left)) is not None:
                achadas.add(chave)
        elif isinstance(no, ast.Call):
            if (
                isinstance(no.func, ast.Attribute)
                and no.func.attr == "get"
                and e_alvo(no.func.value)
                and no.args
                and (chave := _literal(no.args[0])) is not None
            ):
                achadas.add(chave)
            elif isinstance(no.func, ast.Name):
                for i, arg in enumerate(no.args):
                    if not e_alvo(arg):
                        continue
                    if no.func.id == "_secao" and len(no.args) > 1:
                        if (chave := _literal(no.args[1])) is not None:
                            achadas.add(chave)
                    else:
                        alvos = _funcoes(arvore).get(no.func.id)
                        if alvos is not None and len(alvos.args.args) > i:
                            achadas |= _chaves_lidas(
                                arvore, no.func.id, alvos.args.args[i].arg, vistas
                            )
    return achadas


def test_base_declara_o_que_le():
    """`CHAVES_DE_BASE` é exatamente o que `_base_de` lê de um `[[base]]`."""
    assert _chaves_lidas(_arvore(), "_base_de", "dados") == set(CHAVES_DE_BASE)


def test_padrao_declara_o_que_le():
    """`CHAVES_DE_PADRAO` é exatamente o que `carregar` lê de `[padrao]`."""
    assert _chaves_lidas(_arvore(), "carregar", "padrao_bruto") == set(CHAVES_DE_PADRAO)


def test_topo_declara_o_que_le():
    """`CHAVES_DE_TOPO` mais a exceção do censo legado, e nada além."""
    lidas = _chaves_lidas(_arvore(), "carregar", "dados")
    assert lidas == set(CHAVES_DE_TOPO) | set(CHAVES_DE_TOPO_LEGADO)


def test_raiz_declara_o_que_le():
    """`CHAVES_DE_RAIZ` é exatamente o que `_raizes` lê de uma entrada."""
    assert _chaves_lidas(_arvore(), "_raizes", "entrada") == set(CHAVES_DE_RAIZ)


def test_indexacao_declara_o_que_le():
    """`[indexacao]` recusa contra os campos de `Indexacao`, e os lê todos."""
    assert _chaves_lidas(_arvore(), "_indexacao", "dados") == set(Indexacao.__dataclass_fields__)


def test_a_varredura_de_ast_enxerga_algo():
    """Contra a varredura que passa por não achar nada — o modo de falha da casa."""
    assert len(_chaves_lidas(_arvore(), "_base_de", "dados")) >= 10


# --------------------------------------------------------------------------- #
# 3. Tipo errado sai como mensagem, não como traceback


@pytest.mark.parametrize(
    "secao,linha",
    [
        ("busca", 'candidatos = "muitos"'),
        ("busca", "candidatos = true"),
        ("pesos", 'denso = "alto"'),
        ("chunking", 'max_chars = "grande"'),
        ("limites", 'pdf = "cinquenta"'),
    ],
)
def test_tipo_errado_vira_erro_de_config(tmp_path, secao, linha):
    """`candidatos = "muitos"` saía como `TypeError` cru na cara do usuário."""
    texto = f'versao = 1\n\n[[base]]\nid = "padrao"\nindice = "index"\n[base.{secao}]\n{linha}\n'
    with pytest.raises(ErroDeConfig):
        carregar(escrever(tmp_path, texto), ambiente=SEM_AMBIENTE)


def test_rerank_nulo_continua_valido(tmp_path):
    """`rerank` é o único opcional: `None` é o padrão, não tipo errado."""
    cfg = carregar(escrever(tmp_path, BASE_MINIMA), ambiente=SEM_AMBIENTE)
    assert cfg.bases[0].busca.rerank is None
