"""O corpus sintético do `E1` no formato que o harness lê — e a conferência de eixo.

    py -m eval.adaptador_sintetico --entrada <dir do gerador> --saida <perguntas.jsonl>

O gerador (`eval/gerador/`) emite `perguntas.sintetico.jsonl` no formato dele; o
harness lê `eval.harness.Pergunta`. As diferenças são seis, e cinco são renome
(achado 8 do laudo, [`docs/avaliacao-pacote-e1.md`](../docs/avaliacao-pacote-e1.md)):

| gerador | harness | o que o adaptador faz |
|---|---|---|
| `docs_relevantes` | `fontes` | renomeia |
| `criterio: qualquer\\|todas` | derivado de `tipo == "multihop"` | **confere**, não copia |
| `armadilha`: string descritiva | `armadilha`: bool + `notas`: string | desdobra em dois |
| `armadilha_fatia` | `armadilha_fatia` | passa direto (o gerador já corrigiu o nome) |
| `feature_alvo`, `meta`, `resposta_esperada` | — | ficam no arquivo, fora de `Pergunta` |
| — | `autoria` | `gerador`, para o diff nunca confundir com pergunta de uso |

`criterio` é **conferido e não copiado** de propósito. O harness deriva o modo de
`tipo`, e um adaptador que copiasse o campo do gerador deixaria os dois divergirem
em silêncio — a pergunta diria `todas` e o harness mediria `qualquer`. Divergir é
erro alto aqui; concordar não custa nada.

`resposta_esperada` não tem lugar em `Pergunta`, e isso está certo: este é um
sistema de **recuperação**, e a régua é qual documento voltou, não que texto o
modelo escreveria. O campo fica no arquivo para quem quiser inspecionar o
gabarito à mão.

## Por que a conferência de eixo mora aqui

O achado 3 do laudo é o defeito mais caro do pacote e o menos visível: as 260
perguntas saíam `{'não declarado': 260}` porque `idioma_fonte` nunca era emitido,
a fatia cross-lingual ficava **de tamanho zero**, e o relatório saía parecendo
aprovado. Não havia erro, não havia aviso, e a métrica que faltava era justamente
a que o pacote existia para medir.

Consertar a emissão (`E1.b`, condição 2) conserta o caso. `conferir_eixos()` é a
classe: **nenhum eixo declarado pode ter pergunta no balde "não declarado"**. Não
é "≥ 2 baldes" — um corpus legitimamente monolíngue tem um balde só, e isso é
verdade, não defeito. O que nunca é legítimo é a pergunta cair no balde que
significa "ninguém preencheu", porque esse balde não distingue "não se aplica" de
"esqueceram".

Roda na conversão, e não só em teste, para o modo de falha ser o certo: o
adaptador **recusa** em vez de escrever um conjunto que mede menos do que diz.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .harness import Pergunta, carregar_perguntas
from .idioma import NAO_DECLARADO

EIXOS_EXIGIDOS = ("fatia", "armadilha_fatia")
"""Os eixos que o corpus sintético promete preencher, e que se conferem.

`fatia` é o recorte de idioma do `C4.5`; `armadilha_fatia` é o terceiro eixo do
`E1`. `grupo_de_fonte` fica de fora porque ele é derivado do caminho e sempre
devolve um dos quatro grupos — não existe balde "não declarado" para ele cair.
"""

VAZIOS = frozenset({"", NAO_DECLARADO})
"""O que conta como "ninguém preencheu". `não declarado` vem de
`idioma.fatia()`, que o devolve quando qualquer um dos dois códigos falta."""


class EixoColapsado(ValueError):
    """Um eixo declarado tem pergunta no balde de não preenchido."""


def conferir_eixos(perguntas: list[Pergunta], eixos: tuple[str, ...] = EIXOS_EXIGIDOS) -> None:
    """Recusa um conjunto que mede menos do que declara.

    Levanta `EixoColapsado` nomeando o eixo, quantas perguntas caíram no balde
    vazio e um exemplo de id — porque "a fatia está vazia" sem o id manda quem
    lê procurar em 300 linhas.
    """
    for eixo in eixos:
        vazias = [p.id for p in perguntas if getattr(p, eixo, "") in VAZIOS]
        if vazias:
            raise EixoColapsado(
                f"eixo '{eixo}': {len(vazias)} de {len(perguntas)} perguntas no balde "
                f"'não declarado' (ex.: {', '.join(vazias[:3])}). Um eixo que ninguém "
                f"preenche não mede nada, e o relatório sai parecendo aprovado — foi o "
                f"achado 3 do laudo do E1."
            )


def censo_de_eixos(perguntas: list[Pergunta]) -> dict[str, Counter]:
    """Quantas perguntas por balde, em cada eixo. Vai para o cabeçalho do relatório."""
    return {
        "fatia": Counter(p.fatia for p in perguntas),
        "grupo_de_fonte": Counter(p.grupo_de_fonte for p in perguntas),
        "armadilha_fatia": Counter(p.armadilha_fatia for p in perguntas),
    }


def adaptar_uma(d: dict) -> dict:
    """Uma pergunta do gerador no formato do harness."""
    criterio = d.get("criterio", "qualquer")
    esperado = "todas" if d.get("tipo") == "multihop" else "qualquer"
    if criterio != esperado:
        raise ValueError(
            f"{d['id']}: o gerador diz criterio={criterio!r} e o harness derivaria "
            f"{esperado!r} de tipo={d.get('tipo')!r}. O harness sempre ganha — "
            f"corrigir a fatia no gerador, não o adaptador."
        )
    descricao = d.get("armadilha") or ""
    return {
        "id": d["id"],
        "tipo": d["tipo"],
        "pergunta": d["pergunta"],
        "fontes": list(d["docs_relevantes"]),
        "validada": True,
        "notas": descricao,
        "autoria": "gerador",
        "armadilha": bool(descricao),
        "idioma": d["idioma"],
        "idioma_fonte": d["idioma_fonte"],
        "armadilha_fatia": d["armadilha_fatia"],
        # Fora de `Pergunta`, e de propósito: o harness ignora chave que não
        # conhece, e a matriz do `E2` precisa destes para duplicatas@10,
        # precisão contra distratores e o Δ taxonomia vs plana.
        "resposta_esperada": d.get("resposta_esperada", ""),
        "feature_alvo": d.get("feature_alvo", ""),
        "meta": d.get("meta", {}),
    }


def adaptar(entrada: Path, saida: Path) -> list[Pergunta]:
    """Converte, grava, recarrega pelo harness e confere os eixos.

    **Recarregar pelo próprio `carregar_perguntas` é parte do contrato**, não
    zelo: é ele que valida o vocabulário fechado de idioma e o catálogo de
    `fora_de_escopo`. Um adaptador que só escrevesse deixaria o erro para a
    próxima rodada de eval, longe da causa.
    """
    origem = entrada / "perguntas.sintetico.jsonl" if entrada.is_dir() else entrada
    linhas = [json.loads(l) for l in origem.read_text(encoding="utf-8").splitlines() if l.strip()]

    saida.parent.mkdir(parents=True, exist_ok=True)
    with saida.open("w", encoding="utf-8") as f:
        for d in linhas:
            f.write(json.dumps(adaptar_uma(d), ensure_ascii=False) + "\n")

    perguntas = carregar_perguntas(saida)
    conferir_eixos(perguntas)
    return perguntas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.adaptador_sintetico")
    parser.add_argument("--entrada", type=Path, required=True,
                        help="diretório do gerador, ou o perguntas.sintetico.jsonl")
    parser.add_argument("--saida", type=Path, required=True,
                        help="onde gravar o conjunto no formato do harness")
    args = parser.parse_args(argv)

    # Importado aqui, e não no topo, pelo mesmo motivo de `eval.idioma` e
    # `eval.latencia`: o módulo é importável sem o pacote instalado, e só o CLI
    # precisa do logger.
    from segundocerebro.logger import get_logger

    log = get_logger("eval.adaptador_sintetico")
    perguntas = adaptar(args.entrada, args.saida)
    log.info("%d perguntas em %s", len(perguntas), args.saida)
    for eixo, contagem in censo_de_eixos(perguntas).items():
        log.info("  %-16s %s", eixo, dict(contagem.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
