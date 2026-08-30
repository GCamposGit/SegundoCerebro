"""O caminho do leigo, ponta a ponta, sem uma linha de terminal — `F6-B`.

Porta de fase `F6`: *primeiro uso em máquina desconhecida*. O estágio 0 é o
percurso único que alguém que nunca abriu um terminal precisa completar:

    apontar a pasta → ver o que tem lá → indexar → ligar no cliente MCP

Cada degrau já existia como rota. O que não existia era **a prova de que os
quatro se encadeiam** — e a diferença importa, porque a falha típica não é uma
rota quebrada: é o degrau 3 devolver algo que o degrau 4 não aceita. Foi assim
que o registro do MCP passou meses gravando o caminho do repositório na
configuração do usuário: cada peça, sozinha, funcionava.

Sem GPU, sem modelo, sem acervo real — é o que a saída da `F6-B` pede.

**O que este arquivo cobre, e o que não:** os degraus 1, 2 e 4 — abrir sem
config, apontar a pasta, e ligar no cliente. A passada de indexação em si **não**
entra: ela custa horas e já tem a suíte de `tests/test_index.py` inteira. O que
se prova aqui é o encadeamento das decisões do usuário e o que sai gravado no
disco dele, que é onde o percurso quebrava.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from segundocerebro.painel.app import criar_app

TOKEN = "t0k3n-de-teste"


def cabecalho() -> dict[str, str]:
    return {"x-painel-token": TOKEN}


@pytest.fixture
def pasta_do_usuario(tmp_path: Path) -> Path:
    """Uma pasta como a de quem instala amanhã: documentos, e nada nosso."""
    alvo = tmp_path / "Meus Documentos"
    (alvo / "Contratos").mkdir(parents=True)
    (alvo / "Contratos" / "contrato-2026.md").write_text(
        "# Contrato\nContrato NN-VCE-001 da Varzea Clara Energia, 12 meses.\n",
        encoding="utf-8",
    )
    (alvo / "notas.md").write_text("# Notas\nReunião de abertura em março.\n", encoding="utf-8")
    return alvo


@pytest.fixture
def cliente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Painel sem `config.toml` — o estado real de quem acabou de instalar."""
    from starlette.testclient import TestClient

    monkeypatch.setattr("segundocerebro.index.retomada.instalada", lambda: False)
    return TestClient(criar_app(tmp_path / "config.toml", medidor=lambda *a: {}, token=TOKEN))


def test_estagio_zero_do_leigo(cliente, pasta_do_usuario, tmp_path, monkeypatch):
    """Os quatro degraus, em sequência, com o estado carregando de um para o outro."""
    # 1. O painel abre sem config nenhum e não esconde isso.
    estado = cliente.get("/api/estado", headers=cabecalho())
    assert estado.status_code == 200, estado.text

    # 2. Aponta a pasta. Criar não indexa — são duas decisões, e a segunda custa horas.
    criada = cliente.post(
        "/api/base",
        headers=cabecalho(),
        json={"id": "meus", "nome": "Meus documentos", "raizes": [str(pasta_do_usuario)]},
    )
    assert criada.status_code == 200, criada.text

    depois = cliente.get("/api/estado", headers=cabecalho()).json()
    nossa = [b for b in depois["bases"] if b["id"] == "meus"]
    assert nossa, f"a base criada não aparece no estado: {depois['bases']}"
    assert not nossa[0]["indexada"], "criar não pode indexar — o usuário vê a prévia antes"

    # 3. O config foi materializado no lugar certo, e a raiz **resolve** para a
    #    pasta que o usuário apontou. O arquivo a grava relativa a si mesmo, que
    #    é o que faz a base ser copiável junto com o config — por isso a
    #    asserção é sobre o caminho resolvido, não sobre o texto do TOML.
    config = tmp_path / "config.toml"
    assert config.exists(), "o painel não materializou o config.toml"

    from segundocerebro.config import carregar

    base = carregar(config, ambiente={}, validar=False).base("meus")
    assert [Path(r.path).resolve() for r in base.raizes] == [pasta_do_usuario.resolve()]


def test_o_botao_de_ligar_grava_config_do_usuario_e_nao_do_repositorio(
    cliente, pasta_do_usuario, tmp_path, monkeypatch
):
    """Degrau 4: o botão "ligar no Claude Desktop", que é onde o terminal morria.

    A asserção que importa não é "gravou": é **o que** gravou. Até 30/08/2026 o
    painel escrevia `--config <raiz do repositório>/config.toml` e
    `cwd=<raiz do repositório>` — para quem instalou por `pip`, um caminho dentro
    do `site-packages`. O cliente subia com `ModuleNotFoundError` e o usuário
    lia "servidor não conecta".
    """
    from segundocerebro.mcp import registrar

    destino = tmp_path / "cliente" / "config.json"
    destino.parent.mkdir()
    monkeypatch.setattr(registrar, "em_checkout", lambda: False)
    monkeypatch.setattr(registrar, "destino_de", lambda _c: destino)

    cliente.post(
        "/api/base",
        headers=cabecalho(),
        json={"id": "meus", "nome": "Meus documentos", "raizes": [str(pasta_do_usuario)]},
    )
    ligado = cliente.post(
        "/api/conectar", headers=cabecalho(), json={"base": "meus", "cliente": "claude-desktop"}
    )
    assert ligado.status_code == 200, ligado.text

    escrito = json.loads(destino.read_text(encoding="utf-8"))
    entrada = escrito["mcpServers"]["segundocerebro-meus"]
    assert entrada["cwd"] == str(tmp_path), (
        f"o `cwd` tem de ser a pasta do config do usuário, e veio {entrada['cwd']!r}"
    )
    assert str(tmp_path / "config.toml") in entrada["args"]
    assert "PYTHONPATH" not in entrada["env"], "instalação por pip não leva PYTHONPATH"
    assert str(registrar.RAIZ) not in json.dumps(entrada), (
        f"o registro leva a raiz do repositório para a máquina do usuário: {entrada}"
    )


def test_o_botao_nao_apaga_a_configuracao_dos_outros(cliente, pasta_do_usuario, tmp_path, monkeypatch):
    """Mesclar, nunca substituir — o arquivo do cliente costuma ter outros servidores."""
    from segundocerebro.mcp import registrar

    destino = tmp_path / "cliente" / "config.json"
    destino.parent.mkdir()
    destino.write_text(
        json.dumps({"mcpServers": {"outro-servidor": {"command": "algo"}}}), encoding="utf-8"
    )
    monkeypatch.setattr(registrar, "destino_de", lambda _c: destino)

    cliente.post(
        "/api/base",
        headers=cabecalho(),
        json={"id": "meus", "nome": "Meus", "raizes": [str(pasta_do_usuario)]},
    )
    cliente.post(
        "/api/conectar", headers=cabecalho(), json={"base": "meus", "cliente": "claude-desktop"}
    )
    servidores = json.loads(destino.read_text(encoding="utf-8"))["mcpServers"]
    assert "outro-servidor" in servidores, "apagou a configuração de terceiros"
    assert "segundocerebro-meus" in servidores


def test_o_estagio_zero_roda_na_suite_padrao():
    """A saída da `F6-B` é literal: o percurso roda numa máquina sem placa.

    A prova é este arquivo **não** ter marcador. `modelo`, `cuda`, `ocr` e
    `arquivo` são as quatro portas declaradas em `pyproject.toml` que tiram um
    teste da suíte padrão; se algum degrau do estágio 0 passar a exigir GPU ou o
    encoder real, alguém vai marcar este arquivo — e aí o estágio 0 deixou de
    ser testável na máquina de quem clona, que é a condição que a `F6` existe
    para garantir. O teste é a linha que torna esse movimento visível.

    Que o painel não arrasta o encoder é conferido em `tests/test_painel.py`,
    num **subprocesso** — aqui não daria: `sys.modules` é do processo inteiro e
    outro arquivo da suíte já carregou o que quis.
    """
    import ast

    fonte = Path(__file__).read_text(encoding="utf-8")
    marcadores = {
        no.attr
        for no in ast.walk(ast.parse(fonte))
        if isinstance(no, ast.Attribute) and isinstance(no.value, ast.Attribute)
        and getattr(no.value, "attr", "") == "mark"
    }
    proibidos = marcadores & {"modelo", "cuda", "ocr", "arquivo"}
    assert not proibidos, (
        f"o estágio 0 ganhou o marcador {sorted(proibidos)} e saiu da suíte padrão — "
        "deixou de ser o caminho que roda numa máquina sem placa (F6-B)"
    )
