"""Retomada automática — o que ela retoma e, principalmente, o que ela não toca.

Uma indexação de 39 h atravessa reinício, hibernação e queda de energia. O risco
não é deixar de retomar: é retomar em cima de um indexador vivo, que duplica cada
vetor sem levantar erro.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from segundocerebro.config import Base
from segundocerebro.index.indexer import NOME_DA_TRAVA
from segundocerebro.index.progresso import NOME, caminho_de
from segundocerebro.index.retomada import INACABADOS, linha_da_tarefa, main, pendente
from segundocerebro.index import retomada


def base_com_progresso(tmp_path: Path, status: str, **extra) -> Base:  # noqa: ANN003
    indice = tmp_path / "indice"
    indice.mkdir(exist_ok=True)
    dados = {"status": status, "documentos": {"feitos": 40, "totais": 100},
             "restante": "2 h", **extra}
    caminho_de(indice).write_text(json.dumps(dados), encoding="utf-8")
    return Base(id="x", indice=indice)


@pytest.mark.parametrize("status", sorted(INACABADOS))
def test_run_inacabado_e_pendente(tmp_path: Path, status: str) -> None:
    """`indexando` num arquivo em repouso é o mais informativo: morreu sem encerrar."""
    assert pendente(base_com_progresso(tmp_path, status)) is not None


def test_run_concluido_nao_e_pendente(tmp_path: Path) -> None:
    assert pendente(base_com_progresso(tmp_path, "concluida")) is None


def test_base_sem_progresso_nao_e_pendente(tmp_path: Path) -> None:
    """Nunca indexada não é o mesmo que interrompida."""
    indice = tmp_path / "vazio"
    indice.mkdir()
    assert pendente(Base(id="x", indice=indice)) is None


def test_base_com_indexador_vivo_nao_e_pendente(tmp_path: Path) -> None:
    """O caso que importa: retomar em cima de um run vivo duplica cada vetor.

    O SQLite em WAL tolera a concorrência, o LanceDB não — medido uma vez como
    13.458 vetores para 7.214 chunks, sem nada levantar erro.
    """
    base = base_com_progresso(tmp_path, "indexando")
    trava = base.indice / NOME_DA_TRAVA
    import psutil

    trava.write_text(f"{os.getpid()},{psutil.Process().create_time():.3f}", encoding="utf-8")

    assert pendente(base) is None


def test_trava_orfa_nao_impede_retomada(tmp_path: Path) -> None:
    """Queda de energia deixa trava para trás; ela não pode ser sentença perpétua."""
    base = base_com_progresso(tmp_path, "indexando")
    (base.indice / NOME_DA_TRAVA).write_text("999999,1.000", encoding="utf-8")

    assert pendente(base) is not None


def test_progresso_ilegivel_nao_e_pendente(tmp_path: Path) -> None:
    indice = tmp_path / "indice"
    indice.mkdir()
    (indice / NOME).write_text("{truncado", encoding="utf-8")
    assert pendente(Base(id="x", indice=indice)) is None


# --- a linha de comando -------------------------------------------------------


def test_listar_nao_indexa_nada(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "config.toml").write_text(
        '[[base]]\nid = "x"\nindice = "indice"\n', encoding="utf-8"
    )
    base_com_progresso(tmp_path, "interrompida")
    chamadas = []
    monkeypatch.setattr(
        "segundocerebro.index.retomada.subprocess.run",
        lambda *a, **k: chamadas.append(a) or type("R", (), {"returncode": 0})(),
    )

    assert main(["--config", str(tmp_path / "config.toml"), "--listar"]) == 0
    assert chamadas == [], "--listar não dispara indexador"


def test_sem_nada_a_retomar_sai_com_sucesso(tmp_path: Path) -> None:
    """Roda a cada logon: erro no caso normal treina o usuário a ignorar o aviso."""
    (tmp_path / "config.toml").write_text(
        '[[base]]\nid = "x"\nindice = "indice"\n', encoding="utf-8"
    )
    base_com_progresso(tmp_path, "concluida")

    assert main(["--config", str(tmp_path / "config.toml")]) == 0


def test_retoma_chamando_o_indexador(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.toml").write_text(
        '[[base]]\nid = "x"\nindice = "indice"\n', encoding="utf-8"
    )
    base_com_progresso(tmp_path, "indexando")
    comandos = []

    def falso(comando, **k):  # noqa: ANN001, ANN003, ANN202
        comandos.append(comando)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("segundocerebro.index.retomada.subprocess.run", falso)
    assert main(["--config", str(tmp_path / "config.toml"), "--perfil", "leve"]) == 0

    assert len(comandos) == 1
    assert "--base" in comandos[0] and "x" in comandos[0]
    assert comandos[0][-2:] == ["--perfil", "leve"]


def test_retoma_com_o_perfil_salvo_na_maquina(tmp_path: Path, monkeypatch) -> None:
    """Reiniciar não volta para leve: vale o esforço que estava gravado."""
    (tmp_path / "config.toml").write_text(
        '[maquina]\nperfil = "maximo"\n[[base]]\nid = "x"\nindice = "indice"\n',
        encoding="utf-8",
    )
    base_com_progresso(tmp_path, "indexando")
    comandos = []

    def falso(comando, **k):  # noqa: ANN001, ANN003, ANN202
        comandos.append(comando)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("segundocerebro.index.retomada.subprocess.run", falso)
    assert main(["--config", str(tmp_path / "config.toml")]) == 0
    assert comandos[0][-2:] == ["--perfil", "maximo"]


def test_config_invalida_falha_claro(tmp_path: Path) -> None:
    ruim = tmp_path / "config.toml"
    ruim.write_text('[[base]]\nid = "Maiúscula"\n', encoding="utf-8")
    assert main(["--config", str(ruim)]) == 2


def test_linha_da_tarefa_entra_na_pasta_do_projeto() -> None:
    """O `.cmd` nasce em system32; `cd /d` e `PYTHONPATH=src` resolvem a raiz."""
    linha = linha_da_tarefa(Path(r"C:\Projeto"))

    assert "cd /d" in linha and r"C:\Projeto" in linha
    assert "PYTHONPATH=src" in linha
    assert "segundocerebro.index.retomada" in linha


def test_linha_da_tarefa_leva_o_provider_de_quem_instalou(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem isto a retomada no logon cai na CPU neste desktop."""
    monkeypatch.setenv("SEGUNDOCEREBRO_PROVIDER", "cuda")
    linha = linha_da_tarefa(Path(r"C:\Projeto"))
    assert "SEGUNDOCEREBRO_PROVIDER=cuda" in linha


# --- o gatilho de logon: arquivo na pasta de inicialização --------------------
# Era `schtasks /SC ONLOGON` no ROADMAP. Tentado nesta máquina em 19/08/2026 e
# **negado sem elevação**, por `schtasks` e por `Register-ScheduledTask`; criar
# tarefa `ONCE` no mesmo shell funciona, o que localiza o impedimento no gatilho
# de logon e não no agendador. Exigir administrador para ligar uma conveniência
# derrubaria o público do painel, então o mecanismo é um `.cmd` de usuário.


@pytest.fixture
def inicializacao(tmp_path: Path, monkeypatch) -> Path:
    """Redireciona a pasta de inicialização — nenhum teste toca a real."""
    pasta = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    pasta.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return pasta


def test_ligar_escreve_o_cmd_e_desligar_apaga(inicializacao: Path) -> None:
    assert retomada.instalada() is False
    assert retomada.agendar(instalar=True) == 0
    assert retomada.instalada() is True

    alvo = retomada.caminho_do_gatilho()
    assert alvo.parent == inicializacao
    conteudo = alvo.read_text(encoding="ascii")
    assert "segundocerebro.index.retomada" in conteudo
    assert "PYTHONPATH=src" in conteudo

    assert retomada.agendar(instalar=False) == 0
    assert retomada.instalada() is False


def test_desligar_o_que_ja_esta_desligado_e_sucesso(inicializacao: Path) -> None:
    """Clicar "Desligar" duas vezes não é erro.

    O usuário pediu um estado, e o estado é esse. Falhar aqui pintaria de vermelho
    uma tela que fez exatamente o que foi pedido.
    """
    assert retomada.agendar(instalar=False) == 0
    assert retomada.instalada() is False


def test_ligar_duas_vezes_nao_duplica(inicializacao: Path) -> None:
    retomada.agendar(instalar=True)
    primeiro = retomada.caminho_do_gatilho().read_text(encoding="ascii")
    retomada.agendar(instalar=True)
    assert retomada.caminho_do_gatilho().read_text(encoding="ascii") == primeiro
    assert len(list(inicializacao.iterdir())) == 1


def test_cmd_nao_sai_com_quebra_dupla(inicializacao: Path) -> None:
    """`\r\r\n` é o defeito clássico de escrever `\r\n` sem `newline=""`.

    O `cmd` engole algumas linhas assim e falha noutras, o que produz um gatilho
    que às vezes funciona — o pior modo de falha para algo que roda no logon.
    """
    retomada.agendar(instalar=True)
    bruto = retomada.caminho_do_gatilho().read_bytes()
    assert b"\r\r\n" not in bruto
    assert bruto.count(b"\r\n") >= 4


def test_sem_pasta_de_inicializacao_responde_nao_sei(tmp_path: Path, monkeypatch) -> None:
    """Fora do Windows não existe pasta de inicialização.

    "Não sei" e "desligado" levam a telas diferentes: a segunda oferece o botão de
    ligar, e oferecer isso onde o mecanismo não existe é prometer o que não há.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "nao-existe"))
    assert retomada.instalada() is None


def test_a_tarefa_de_logon_numa_instalacao_por_pip(monkeypatch, tmp_path):
    """O ramo que ninguém testava, e que o `F6` existe para cobrir.

    `test_linha_da_tarefa_entra_na_pasta_do_projeto` afirma
    `"PYTHONPATH=src" in linha` **incondicionalmente**, e passa só porque a suíte
    roda de um checkout. É a lição do `⊆` do `CLAUDE.md`: quando o mecanismo real
    não é visível ao instrumento, o que fecha é um segundo teste de
    comportamento — este.

    Fora de um checkout o `.cmd` não pode levar `PYTHONPATH`, não pode entrar na
    raiz deduzida (que é o `site-packages`), e precisa do `--config`. Sem isso a
    retomada de logon sobe, sintetiza a base `padrao` sem raiz e reindexa o nada,
    toda vez que o usuário liga o computador.
    """
    from segundocerebro.index import retomada

    monkeypatch.setattr(retomada, "em_checkout", lambda: False)
    monkeypatch.setattr(retomada.sys, "executable", str(tmp_path / "Python" / "python.exe"))
    config = tmp_path / "meu" / "config.toml"
    config.parent.mkdir(parents=True)
    linha = retomada.linha_da_tarefa(retomada.raiz_do_repositorio(), config)

    assert "PYTHONPATH" not in linha, "instalação por pip não leva PYTHONPATH"
    assert f'cd /d "{config.parent}"' in linha, (
        f"o `cd /d` tem de ir para a pasta do config do usuário: {linha!r}"
    )
    assert f'--config "{config}"' in linha, "sem --config a retomada reindexa o nada"
    assert str(retomada.raiz_do_repositorio()) not in linha, (
        "a tarefa de logon leva a raiz do repositório para a máquina do usuário"
    )


def test_no_checkout_a_tarefa_de_logon_continua_como_era(monkeypatch):
    """A régua do teste acima: quem roda do checkout não perde nada."""
    from segundocerebro.index import retomada

    monkeypatch.setattr(retomada, "em_checkout", lambda: True)
    linha = retomada.linha_da_tarefa(retomada.raiz_do_repositorio())
    assert "set PYTHONPATH=src" in linha
    assert f'cd /d "{retomada.raiz_do_repositorio()}"' in linha
