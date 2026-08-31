"""Configuração → TOML. A metade que o painel usa para salvar.

Saiu de `config.py` em 29/08/2026, e é a primeira das quatro costuras que o
`Q16` levantou para aquele arquivo (`modelos` · `leitura` · `ambiente` ·
`escrita`). Não saiu por estética: o `Q11` acrescentou a recusa de chave
desconhecida em cinco níveis, `config.py` passou de 1.093 para 1.185 linhas, e
`tests/test_tamanho_dos_modulos.py` reprovou com a instrução certa — *a tabela é
escada, não teto; acrescente o que for novo em arquivo próprio*.

Escrever é a costura mais barata das quatro porque a dependência é de mão única:
ler não precisa de escrever. Por isso este módulo importa `config`, e `config`
**não** importa este — quem grava pede aqui. `painel/app.py` é o único
consumidor de produto; o resto é teste.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .census import DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_GLOBS
from .config import (
    VERSAO,
    Busca,
    Chunking,
    Config,
    ErroDeConfig,
    Indexacao,
    LimitesDeIndexacao,
    Maquina,
    Pesos,
)

__all__ = ["como_toml", "gravar"]


def como_toml(cfg: Config, raiz: Path | None = None) -> dict[str, Any]:
    """Configuração como dados prontos para serialização.

    `raiz` reescreve como relativo tudo que estiver abaixo dela — simetria de
    `_resolver`, que ancora na leitura. Sem isso, salvar pelo painel converteria
    `indice = "index"` em caminho absoluto desta máquina e o par
    `config.toml` + `index/` deixaria de poder ser copiado para outro
    computador, que é justamente o fluxo da F3.6.

    Só o que difere do padrão é escrito. Um arquivo que repete todos os valores
    embutidos vira uma cópia congelada: no dia em que um padrão do código mudar,
    a configuração antiga silenciosamente continua no valor velho, e ninguém
    descobre porque o arquivo "não foi alterado". Omitir é o que deixa o padrão
    ser padrão.
    """

    def diferenca(objeto, referencia) -> dict[str, Any]:  # noqa: ANN001
        return {
            campo: getattr(objeto, campo)
            for campo in objeto.__dataclass_fields__
            if getattr(objeto, campo) != getattr(referencia, campo)
        }

    def caminho(p: Path) -> str:
        if raiz is not None:
            try:
                return str(p.relative_to(raiz))
            except ValueError:
                pass  # fora da árvore do config: absoluto é a resposta certa
        return str(p)

    dados: dict[str, Any] = {"versao": VERSAO}

    maquina = diferenca(cfg.maquina, Maquina())
    if "limites" in maquina:
        lim = diferenca(cfg.maquina.limites, Maquina().limites)
        if lim:
            maquina["limites"] = lim
        else:
            del maquina["limites"]
    if maquina:
        dados["maquina"] = {k: v for k, v in maquina.items() if v is not None}

    indexacao = diferenca(cfg.indexacao, Indexacao())
    if indexacao:
        dados["indexacao"] = {k: v for k, v in indexacao.items() if v not in (None, "", False)}

    bases: list[dict[str, Any]] = []
    for b in cfg.bases:
        entrada: dict[str, Any] = {"id": b.id}
        for campo in ("nome", "descricao", "modelo"):
            if getattr(b, campo):
                entrada[campo] = getattr(b, campo)
        entrada["indice"] = caminho(b.indice)
        if b.dourado is not None:
            entrada["dourado"] = caminho(b.dourado)
        if b.glossario is not None:
            entrada["glossario"] = caminho(b.glossario)
        if b.raizes:
            entrada["raizes"] = [{"nome": r.name, "caminho": caminho(Path(r.path))} for r in b.raizes]

        extras_dirs = tuple(d for d in b.exclude_dirs if d not in DEFAULT_EXCLUDE_DIRS)
        extras_globs = tuple(g for g in b.exclude_globs if g not in DEFAULT_EXCLUDE_GLOBS)
        if extras_dirs or extras_globs or b.exclude_roles:
            entrada["exclude"] = {}
            if extras_dirs:
                entrada["exclude"]["dirs"] = list(extras_dirs)
            if extras_globs:
                entrada["exclude"]["globs"] = list(extras_globs)
            if b.exclude_roles:
                entrada["exclude"]["papel"] = [
                    {"dirs": list(r.dirs), "globs": list(r.globs)} if r.dirs else {"globs": list(r.globs)}
                    for r in b.exclude_roles
                ]

        for chave, valor, referencia in (
            ("pesos", b.pesos, Pesos()),
            ("busca", b.busca, Busca()),
            ("chunking", b.chunking, Chunking()),
            ("limites", b.limites, LimitesDeIndexacao()),
        ):
            secao = diferenca(valor, referencia)
            if secao:
                entrada[chave] = secao
        bases.append(entrada)

    dados["base"] = bases
    return dados


def gravar(cfg: Config, caminho: Path) -> None:
    """Grava a configuração, de forma que reler devolva o mesmo objeto.

    É a metade que falta para o painel: a invariante 4 exige medir antes de
    salvar, e salvar exige escrever. O `tomli_w` entra aqui e só aqui — escapar
    caminho do Windows à mão é onde escritor de TOML caseiro erra, e um erro
    desses corrompe a configuração do usuário em silêncio.

    Escrita atômica: um `.tmp` ao lado e um `replace`. Configuração meio escrita
    por queda de energia é pior que configuração velha.
    """
    try:
        import tomli_w
    except ModuleNotFoundError as erro:  # pragma: no cover - depende do ambiente
        raise ErroDeConfig(
            "gravar configuração exige o pacote `tomli-w` (pip install tomli-w) — "
            "ele não é necessário para consultar, só para o painel"
        ) from erro

    cfg.validar()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    with temporario.open("wb") as fh:
        tomli_w.dump(como_toml(cfg, caminho.parent), fh)
    temporario.replace(caminho)
