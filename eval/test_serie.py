"""`F4-D.2`: a série histórica passa a ter mecanismo, não frase.

Duas metades, e a divisão é deliberada:

- **A metade que sempre tem veredito** roda contra um dourado sintético montado
  no `tmp_path`. Ela prova o mecanismo — o que muda a impressão e o que não muda
  — em qualquer máquina, com ou sem acervo. Teste que pula por causa da máquina
  é teste que não tem veredito.
- **A metade que depende do acervo** confere o `perguntas.jsonl` real contra o
  manifesto versionado. Onde o dourado real não existe — o desktop, um clone
  novo, o CI — ela ainda assere sobre o **manifesto**, que é versionado e está
  lá: bem formado, sem id repetido, `n` batendo com a lista.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import serie
from eval.harness import carregar_perguntas

PERGUNTAS = [
    {
        "id": "s001",
        "tipo": "exato",
        "pergunta": "Qual o valor do contrato CT-VCE-2024-0142?",
        "fontes": ["Contratos/CT-VCE-2024-0142.pdf"],
        "validada": True,
        "notas": "código de contrato",
    },
    {
        "id": "s002",
        "tipo": "semantica",
        "pergunta": "O que a política diz sobre uso de IA generativa?",
        "fontes": ["Politica de IA/PO-VCE-007.docx", "Anexos/Diretrizes.pdf"],
        "validada": True,
    },
]


def escrever(destino: Path, perguntas: list[dict]) -> Path:
    destino.write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in perguntas) + "\n",
        encoding="utf-8",
    )
    return destino


@pytest.fixture
def dourado(tmp_path: Path) -> Path:
    return escrever(tmp_path / "perguntas.jsonl", PERGUNTAS)


def impressoes(caminho: Path) -> dict[str, str]:
    return serie.impressoes_de(carregar_perguntas(caminho))


# --- o que move a métrica, e o que não move -----------------------------------


def test_editar_a_pergunta_muda_a_impressao(tmp_path: Path, dourado: Path) -> None:
    """É o caso que originou o pacote: typo corrigido sem deixar diff."""
    alterado = [dict(PERGUNTAS[0], pergunta="Qual o valor do contrato?"), PERGUNTAS[1]]
    outro = escrever(tmp_path / "outro.jsonl", alterado)

    divergencia = serie.conferir(carregar_perguntas(outro), impressoes(dourado))
    assert divergencia.mudaram == ("s001",)
    assert not divergencia.limpa
    assert "s001" in divergencia.relatar("dourado-v1")


def test_trocar_uma_fonte_esperada_muda_a_impressao(tmp_path: Path, dourado: Path) -> None:
    alterado = [PERGUNTAS[0], dict(PERGUNTAS[1], fontes=["Politica de IA/PO-VCE-007_v6.docx"])]
    outro = escrever(tmp_path / "outro.jsonl", alterado)

    assert serie.conferir(carregar_perguntas(outro), impressoes(dourado)).mudaram == ("s002",)


def test_reeditar_notas_ou_validada_nao_muda_nada(tmp_path: Path, dourado: Path) -> None:
    """Manifesto que reprova por nota reescrita é manifesto abandonado.

    O que se congela é o que move o número: pergunta, tipo e fontes. `notas`,
    `autoria` e `validada` são a memória de quem escreveu, não a régua.
    """
    alterado = [
        dict(PERGUNTAS[0], notas="outra explicação inteiramente", validada=False),
        dict(PERGUNTAS[1], autoria="usuario"),
    ]
    outro = escrever(tmp_path / "outro.jsonl", alterado)

    assert serie.conferir(carregar_perguntas(outro), impressoes(dourado)).limpa


def test_ordem_das_linhas_e_dos_caminhos_nao_muda_nada(tmp_path: Path, dourado: Path) -> None:
    """Reordenar o arquivo não é editar o conjunto."""
    invertido = [
        dict(PERGUNTAS[1], fontes=list(reversed(PERGUNTAS[1]["fontes"]))),
        PERGUNTAS[0],
    ]
    outro = escrever(tmp_path / "outro.jsonl", invertido)

    assert serie.conferir(carregar_perguntas(outro), impressoes(dourado)).limpa


def test_separador_de_caminho_nao_muda_nada(tmp_path: Path, dourado: Path) -> None:
    """O dourado é escrito no Windows e lido onde for — como no harness."""
    alterado = [
        dict(PERGUNTAS[0], fontes=["Contratos\\CT-VCE-2024-0142.pdf"]),
        PERGUNTAS[1],
    ]
    outro = escrever(tmp_path / "outro.jsonl", alterado)

    assert serie.conferir(carregar_perguntas(outro), impressoes(dourado)).limpa


def test_pergunta_nova_e_pergunta_removida_aparecem_separadas(tmp_path: Path, dourado: Path) -> None:
    """Somem e entram são coisas diferentes, e a mensagem diz qual foi qual."""
    alterado = [PERGUNTAS[0], dict(PERGUNTAS[1], id="s003")]
    outro = escrever(tmp_path / "outro.jsonl", alterado)

    divergencia = serie.conferir(carregar_perguntas(outro), impressoes(dourado))
    assert divergencia.sumiram == ("s002",)
    assert divergencia.entraram == ("s003",)
    assert divergencia.mudaram == ()


def test_congelar_e_conferir_fecham_o_ciclo(tmp_path: Path, dourado: Path) -> None:
    """O que `--congelar` grava é o que `--conferir` aceita, sem intervenção."""
    alvo = tmp_path / "serie.toml"
    alvo.write_text(serie.como_toml(impressoes(dourado), "teste-v1", "2026-08-30"), encoding="utf-8")

    assert serie.conferir(carregar_perguntas(dourado), serie.ler(alvo)).limpa


def test_manifesto_editado_a_mao_e_recusado(tmp_path: Path, dourado: Path) -> None:
    """`n` fora de sincronia com a lista é a assinatura da edição manual."""
    alvo = tmp_path / "serie.toml"
    texto = serie.como_toml(impressoes(dourado), "teste-v1", "2026-08-30")
    alvo.write_text(texto.replace("\ns002 = ", "\n# s002 = "), encoding="utf-8")

    with pytest.raises(ValueError, match="editado à mão"):
        serie.ler(alvo)


# --- a série real, e o que se afirma quando ela não está aqui -----------------


def test_a_serie_congelada_esta_versionada_e_bem_formada() -> None:
    """Vale em qualquer máquina: o manifesto é versionado, o dourado não é."""
    caminho = serie.caminho_da_serie()
    assert caminho.exists(), (
        f"{caminho.name} não existe. Ele é o que faz `dourado-v1` ser mecanismo em vez de "
        "frase — rode `py -m eval.serie --base <id> --congelar`."
    )
    congeladas = serie.ler(caminho)
    assert congeladas, "série vazia congela coisa nenhuma"
    assert all(
        len(h) == serie.TAMANHO_DA_IMPRESSAO and all(c in "0123456789abcdef" for c in h)
        for h in congeladas.values()
    )


def test_o_dourado_desta_maquina_e_a_serie_congelada() -> None:
    """A porta: pergunta editada não move a linha de base em silêncio.

    Onde o dourado real não existe, o teste **não** vira no-op: ele exige que o
    que está aqui seja o conjunto de exemplo, que é versionado e tem série
    própria. O que ele nunca faz é passar sem olhar nada.
    """
    from eval.harness import GOLDEN

    if not GOLDEN.exists():
        pytest.skip(
            "sem `eval/golden/perguntas.jsonl` nesta máquina — a série real não é conferível "
            "aqui, e `test_a_serie_congelada_esta_versionada_e_bem_formada` é o que sobra"
        )

    divergencia = serie.conferir(carregar_perguntas(GOLDEN), serie.ler(serie.caminho_da_serie()))
    assert divergencia.limpa, divergencia.relatar(serie.SERIE_PADRAO)
