"""Os dois documentos que o leigo lê, conferidos contra o produto.

Não é teste de estilo nem de redação: são duas afirmações verificáveis que estes
arquivos fazem e que **envelhecem sozinhas**.

O precedente é de 25/08/2026, no mesmo dia em que esta suíte nasceu:
`usar-o-mcp.md` dizia "duas ferramentas" e "`neighbors` continua hipótese" um mês
depois de a `neighbors` estar servindo no `.mcp.json` do usuário. Ninguém mentiu —
o doc simplesmente não tinha nada que o obrigasse a acompanhar o código, e
documentação que descreve superfície **menor** que a real é o pior tipo de erro
de doc: parece conservadora e faz o usuário não usar o que já tem instalado.

A classe é "doc de usuário afirma coisa que o código não sustenta" (regra 12), e
ela tem três instâncias mensuráveis. Duas estão aqui:

- **o comando que o doc manda digitar existe**. É o primeiro contato do leigo com
  o sistema, e o modo de falha é o pior possível: ele digita, o PowerShell diz que
  não reconhece, e ele conclui que não instalou. Já aconteceu por outro caminho —
  `docs/colaboracao.md` registra que os quatro console scripts existem nesta
  máquina e nenhum é achado pelo nome;
- **a lista de formatos é a do produto**. `supported_extensions()` cresceu quatro
  vezes neste repositório. Um doc que promete menos faz o usuário não apontar a
  pasta que interessa; um que promete mais faz ele achar que o sistema quebrou.

A terceira — a lista de ferramentas — mora em `test_protocolo_mcp.py`, ao lado da
superfície que ela espelha.

Nada aqui importa os módulos: `find_spec` localiza e o arquivo é lido como texto.
Importar o indexador para conferir uma linha de doc traria `fastembed` junto.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from segundocerebro.ingest.parsers import supported_extensions

REPO = Path(__file__).resolve().parents[1]
COMECAR = REPO / "docs" / "comecar.md"
USAR = REPO / "docs" / "usar-o-mcp.md"

FORA_DO_PRODUTO = {"pip"}
"""Módulos que os docs citam e que não são nossos. `pip` é o passo de instalação."""


@pytest.mark.parametrize("doc", [COMECAR, USAR], ids=lambda p: p.name)
def test_todo_comando_que_o_doc_manda_digitar_existe(doc: Path) -> None:
    """`py -m X` só entra num doc de usuário se `X` for executável hoje.

    Renomear ou mover um módulo é refatoração normal e não quebra nada — a não ser
    a página que manda o leigo digitá-lo, que ninguém relê. Aqui quebra.
    """
    # Nome de módulo de verdade: começa com letra e cada pedaço também. Sem isso o
    # `py -m ...` que o passo 2 usa como forma genérica entraria como um módulo.
    texto = doc.read_text(encoding="utf-8")
    achados = re.findall(r"\bpy -m ([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)", texto)
    modulos = {m for m in achados if m not in FORA_DO_PRODUTO}

    assert modulos, f"{doc.name} não manda digitar nenhum comando — o regex mudou?"
    for modulo in sorted(modulos):
        spec = importlib.util.find_spec(modulo)
        assert spec is not None, f"{doc.name} manda digitar `py -m {modulo}`, que não existe"

        # Executável por `-m` significa uma de duas coisas: pacote com `__main__`,
        # ou módulo com `main()`. Sem isso o comando falha com "No module named".
        # `find_spec` de submódulo só se pergunta a pacote — em módulo simples ela
        # levanta em vez de devolver `None`.
        e_pacote = spec.submodule_search_locations is not None
        tem_main_de_pacote = (
            e_pacote and importlib.util.find_spec(f"{modulo}.__main__") is not None
        )
        fonte = Path(spec.origin).read_text(encoding="utf-8") if spec.origin else ""
        tem_funcao_main = re.search(r"^def main\(", fonte, re.MULTILINE) is not None

        assert tem_main_de_pacote or tem_funcao_main, (
            f"`py -m {modulo}` está no {doc.name} mas o módulo não tem ponto de entrada"
        )


def test_o_doc_lista_exatamente_os_formatos_que_o_produto_le() -> None:
    """A lista de formatos sai de `supported_extensions()`, nos dois sentidos.

    Prometer menos faz o usuário não apontar a pasta que interessa. Prometer mais
    faz ele achar que o sistema quebrou quando o arquivo fica de fora — e, pior,
    procurar o defeito no lugar errado.

    A linha do doc é a que começa com "Só estes formatos"; ela é a única que
    enumera extensão, de propósito, para haver um lugar só a manter.
    """
    linha = next(
        (
            l
            for l in COMECAR.read_text(encoding="utf-8").splitlines()
            if "Só estes formatos" in l
        ),
        None,
    )
    assert linha, "a linha que enumera os formatos mudou de forma — o doc perdeu o guarda"

    # A enumeração continua na linha seguinte; pega o parágrafo inteiro do item.
    texto = COMECAR.read_text(encoding="utf-8")
    inicio = texto.index(linha)
    item = texto[inicio : texto.index("\n- ", inicio + 1) if "\n- " in texto[inicio:] else len(texto)]
    prometidas = set(re.findall(r"`(\.[a-z0-9]+)`", item))

    assert prometidas == set(supported_extensions()), (
        f"o doc promete {sorted(prometidas)} e o produto lê {sorted(supported_extensions())}"
    )
