"""`except Exception` sem motivo escrito não entra — a suíte lê o código.

A política vive em `ARCHITECTURE.md` (Camada 1). Este arquivo é o método que
passa a pegá-la sozinho (regra 12): um BLE001 novo sem o sufixo de motivo
reprova no mesmo dia, em qualquer arquivo versionado, sem ninguém reler o
guia.

Três afirmações, e só essas:

- todo `except Exception` versionado tem `# noqa: BLE001 — <motivo>` na mesma
  linha;
- o caminho de consulta (`mcp/`, `retrieve/`) não tem `except Exception` —
  ali a exceção é tipada ou sobe;
- o texto da política em `ARCHITECTURE.md` ainda nomeia os três casos
  permitidos. Sem isso o doc envelhece e o teste de sufixo continua verde.

Não importa os módulos: `git ls-files` localiza e o arquivo é lido como texto.
Importar o indexador para conferir um comentário traria `fastembed` junto.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARQUITETURA = REPO / "ARCHITECTURE.md"

CAMINHO_DE_CONSULTA = ("src/segundocerebro/mcp/", "src/segundocerebro/retrieve/")

EXCEPT = re.compile(r"^(\s*)except Exception(?: as \w+)?:(.*)$")
NOQA_BLE = re.compile(
    r"#\s*noqa:\s*([A-Z][A-Z0-9]+(?:\s*,\s*[A-Z][A-Z0-9]+)*)\s+—\s+\S"
)

# Frases que a política precisa continuar contendo. Se alguém reescrever o
# parágrafo e tirar o caso, o teste pede o parágrafo de volta — não uma
# redraft da tabela.
FRASES_DA_POLITICA = (
    "except Exception",
    "arquivo hostil",
    "ParseStatus",
    "laço de onda",
    "probe de hardware",
    "caminho de consulta",
)


def versionados_py() -> list[Path]:
    saida = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO / nome for nome in saida.split("\0") if nome]


def _motivo_ok(resto: str) -> bool:
    achado = NOQA_BLE.search(resto)
    if achado is None:
        return False
    codigos = {c.strip() for c in achado.group(1).split(",")}
    return "BLE001" in codigos


def test_o_padrao_recusa_ble001_sem_motivo() -> None:
    """O regex é o método. Sem estes casos ele aceita sufixo vazio e parece prova."""
    assert not _motivo_ok("  # noqa: BLE001")
    assert not _motivo_ok("  # noqa: BLE001 —")
    assert not _motivo_ok("  # noqa: BLE001 — ")
    assert not _motivo_ok("  # a corrupt file must not stop the indexing run")
    assert _motivo_ok("  # noqa: BLE001 — borda de parse, arquivo hostil")
    assert _motivo_ok("  # noqa: ANN001, BLE001 — probe de import")
    assert _motivo_ok("  # noqa: BLE001, ARG001 — laço de onda que não pode morrer")


def test_except_exception_leva_motivo_no_noqa() -> None:
    """BLE001 sem travessão e motivo é o defeito. A lista de arquivos não é."""
    faltando: list[str] = []
    for caminho in versionados_py():
        rel = caminho.relative_to(REPO).as_posix()
        try:
            linhas = caminho.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, linha in enumerate(linhas, start=1):
            casado = EXCEPT.match(linha)
            if casado is None:
                continue
            if not _motivo_ok(casado.group(2)):
                faltando.append(f"{rel}:{n}")

    assert not faltando, (
        "except Exception sem `# noqa: BLE001 — <motivo>` na mesma linha. "
        "A política está em ARCHITECTURE.md (Camada 1); o sufixo é o que "
        "impede o próximo BLE001 de nascer mudo:\n  "
        + "\n  ".join(faltando)
    )


def test_caminho_de_consulta_nao_engole_exception() -> None:
    """search/read_note/neighbors não viram lista vazia por except Exception."""
    achados: list[str] = []
    for caminho in versionados_py():
        rel = caminho.relative_to(REPO).as_posix()
        if not rel.startswith(CAMINHO_DE_CONSULTA):
            continue
        try:
            linhas = caminho.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, linha in enumerate(linhas, start=1):
            if EXCEPT.match(linha) is not None:
                achados.append(f"{rel}:{n}")

    assert not achados, (
        "except Exception no caminho de consulta MCP. Ali a exceção é "
        "tipada (ErroDeConfig e irmãs) ou sobe — nunca vira lista vazia:\n  "
        + "\n  ".join(achados)
    )


def test_arquitetura_ainda_nomeia_os_tres_casos() -> None:
    """O doc é a política. Sem estas frases ele descreve outra coisa."""
    texto = ARQUITETURA.read_text(encoding="utf-8").lower()
    faltando = [f for f in FRASES_DA_POLITICA if f.lower() not in texto]
    assert not faltando, (
        "ARCHITECTURE.md perdeu a política de except Exception "
        f"({', '.join(faltando)}). Recoloque o parágrafo da Camada 1, não "
        "apague o teste."
    )
