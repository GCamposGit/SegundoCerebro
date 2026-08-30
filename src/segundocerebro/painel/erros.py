"""Os erros que as rotas do painel traduzem em resposta HTTP.

Módulo próprio, e sem nenhum import pesado, porque é o que mantém a fronteira que
`medir.py` declara: `app.py` decide regra de negócio e não sabe recuperar. Se o
tipo morasse em `medir.py`, `app.py` teria de importar o encoder para escrever um
`except` — é a mesma armadilha que fazia o painel carregar `fastembed` inteiro só
para ler o nome do arquivo de trava.
"""

from __future__ import annotations


class MedicaoIndisponivel(RuntimeError):
    """O harness de avaliação não está nesta instalação.

    `eval/` é a única parte do projeto que o `pyproject.toml` não empacota — não
    por esquecimento: ela carrega o conjunto dourado, que é do acervo de quem
    mediu, e não teria sentido dentro de um `pip install`. O botão "Medir" do
    painel depende dela, e até 29/08/2026 o modo de falha era um
    `ModuleNotFoundError` cru subindo pela rota, que diz ao usuário que o painel
    quebrou quando o que houve é que esta instalação não tem régua.

    O painel continua servindo tudo o mais — a invariante 6 vale para os dois
    lados: quem não tem o repositório perde a medição, não o produto.
    """
