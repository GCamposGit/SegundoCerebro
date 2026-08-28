"""Legenda com marca de tempo, nos tres formatos que o produto le.

Existe porque o `F4-T` registrou `.vtt`, `.srt` e `.sbv` em
`supported_extensions()`, e a guarda do `f_formatos` reprovou na hora: **parser
novo sem fixture reprova**. Escrever prosa dentro de um `.srt` passaria a guarda
e criaria o defeito ao contrario -- arquivo sem marca de tempo, que o parser
devolve **vazio**, e uma pergunta do dourado apontando para um documento sem
chunk. Foi exatamente esse o modo de falha que o `F4-T` fechou; nao vale
reintroduzi-lo pelo gerador.

Uma definicao, dois consumidores, pelo mesmo motivo que `retrieve/fonte.py` mora
em `retrieve/` e nao em `eval/`: a fatia de reuniao (`fatias.f_reuniao`) e a de
cobertura de formato (`formatos.f_formatos`) tem de escrever a **mesma** coisa,
senao uma passa e a outra nao, e cada uma esta certa sozinha.
"""

from __future__ import annotations

from collections.abc import Sequence

SEGUNDOS_POR_FALA = 12
"""Duracao de cada fala gerada.

Doze segundos com onze de fala deixa **um** segundo de silencio entre cues --
abaixo do `SALTO_DE_ASSUNTO` de 8 s do parser, de proposito: as falas de uma
transcricao gerada tem de sair no **mesmo** bloco, senao o corpus mediria a
fronteira de bloco do parser em vez do ranqueamento."""


def _mmss(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def _hmmss(total: int) -> str:
    return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def vtt_de(falas: Sequence[str]) -> str:
    """WebVTT — o que Teams e Meet salvam."""
    blocos = ["WEBVTT", ""]
    for k, fala in enumerate(falas):
        ini, fim = SEGUNDOS_POR_FALA * k, SEGUNDOS_POR_FALA * k + 11
        blocos.append(f"{_mmss(ini)}.000 --> {_mmss(fim)}.000")
        blocos.append(fala)
        blocos.append("")
    return "\n".join(blocos)


def srt_de(falas: Sequence[str]) -> str:
    """SubRip — indice numerico, hora obrigatoria e **virgula** como decimal."""
    blocos: list[str] = []
    for k, fala in enumerate(falas, start=1):
        ini = SEGUNDOS_POR_FALA * (k - 1)
        fim = ini + 11
        blocos.append(str(k))
        blocos.append(f"{_hmmss(ini).rjust(8, '0')},000 --> {_hmmss(fim).rjust(8, '0')},000")
        blocos.append(fala)
        blocos.append("")
    return "\n".join(blocos)


def sbv_de(falas: Sequence[str]) -> str:
    """SubViewer — sem cabecalho, sem indice, e a **virgula separa os tempos**."""
    blocos: list[str] = []
    for k, fala in enumerate(falas):
        ini, fim = SEGUNDOS_POR_FALA * k, SEGUNDOS_POR_FALA * k + 11
        blocos.append(f"{_hmmss(ini)}.000,{_hmmss(fim)}.000")
        blocos.append(fala)
        blocos.append("")
    return "\n".join(blocos)


POR_EXTENSAO = {".vtt": vtt_de, ".srt": srt_de, ".sbv": sbv_de}
"""Extensao → construtor. As chaves têm de cobrir `EXTENSOES_DE_TRANSCRICAO`.

Conferido em `tests/test_gerador_transcricao.py`: extensão de transcrição que o
produto passe a ler sem construtor aqui reprova, em vez de virar arquivo de prosa
que o parser devolve vazio."""


def falas_de(texto: str) -> list[str]:
    """Quebra um corpo de texto em falas, para virar cue.

    Linha vazia e limite de paragrafo somem: cue nao tem paragrafo. O que sobra
    e uma fala por linha nao vazia, que e como transcricao automatica sai.
    """
    return [linha.strip() for linha in texto.splitlines() if linha.strip()]
