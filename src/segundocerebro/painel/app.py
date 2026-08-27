"""Painel de ajuste — a API. A tela vem por cima disto.

    py -m segundocerebro.painel

**Invariante 6: isto está fora do caminho de consulta.** O painel lê e grava
configuração; não recupera, não ranqueia, não gera texto e não é requisito de
execução. O servidor MCP sobe com este módulo apagado do disco, e
`tests/test_painel.py` prova isso.

Starlette puro, sem FastAPI: `starlette`, `uvicorn` e `httpx` já vêm com o pacote
`mcp`, então o painel custa **zero dependência nova** e a história de instalação
continua sendo `pip install -r requirements.txt`. O que a FastAPI acrescentaria —
validação por pydantic e OpenAPI — não paga dez dependências transitivas numa
tela de configuração local de um usuário só.

Duas regras que moram aqui e não na tela, porque regra que só existe no
JavaScript é decoração:

1. **Salvar exige ter medido.** A invariante 4 diz que toda mudança em ranking
   passa pelo eval. O `POST /salvar` recusa uma configuração cuja assinatura não
   esteja no registro de medições desta sessão.
2. **A classe cara não passa por aqui.** Modelo de embedding e tamanhos de chunk
   custam de 31 a 114 horas de reindexação e invalidam toda medição anterior.
   Eles não são ajuste; são obra. A API recusa, com o motivo.
"""

from __future__ import annotations

import hmac
import json
import secrets
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..census import RootSpec
from ..config import (
    LIMITES_RECOMENDADOS,
    Base,
    Busca,
    ErroDeConfig,
    LimitesDeIndexacao,
    Pesos,
    carregar,
    gravar,
)
from ..index.indexer import NOME_DA_TRAVA
from ..logger import get_logger
from ..retrieve.glossario import ErroDeGlossario, Glossario

log = get_logger("painel")

CAMPOS_DE_PESO = frozenset(Pesos.__dataclass_fields__)
CAMPOS_DE_BUSCA = frozenset(Busca.__dataclass_fields__)
CLASSE_CARA = frozenset({"modelo", "chunking", "max_chars", "min_chars", "overlap_chars", "indice", "raizes"})
"""Recusados pela API de ajuste — mexer neles é reindexar, não ajustar."""


def assinatura(pesos: Pesos, busca: Busca) -> str:
    """Identidade de uma configuração ajustável, estável entre processos."""
    return json.dumps(
        {"pesos": pesos.__dict__, "busca": busca.__dict__}, sort_keys=True, separators=(",", ":")
    )


class Medicoes:
    """O que já foi medido nesta sessão. É o que destrava o Salvar."""

    def __init__(self) -> None:
        self._por_assinatura: dict[tuple[str, str], dict[str, Any]] = {}

    def registrar(self, base_id: str, pesos: Pesos, busca: Busca, resultado: dict[str, Any]) -> None:
        self._por_assinatura[(base_id, assinatura(pesos, busca))] = resultado

    def de(self, base_id: str, pesos: Pesos, busca: Busca) -> dict[str, Any] | None:
        return self._por_assinatura.get((base_id, assinatura(pesos, busca)))


def _ajuste_de(corpo: dict[str, Any], base) -> tuple[Pesos, Busca]:  # noqa: ANN001
    """Lê pesos e busca do corpo, recusando o que não é ajuste."""
    proibidos = sorted(CLASSE_CARA & set(corpo))
    if proibidos:
        raise ValueError(
            f"{', '.join(proibidos)} não é ajuste: mudar isso obriga a reindexar (de 31 a 114 h "
            "no corpus medido) e invalida toda comparação com medições anteriores"
        )

    def secao(chave: str, atual, campos: frozenset[str]):  # noqa: ANN001, ANN202
        bruto = corpo.get(chave) or {}
        if not isinstance(bruto, dict):
            raise ValueError(f"'{chave}' precisa ser um objeto")
        desconhecidos = sorted(set(bruto) - campos)
        if desconhecidos:
            raise ValueError(f"em '{chave}', campo desconhecido: {', '.join(desconhecidos)}")
        return replace(atual, **bruto)

    pesos = secao("pesos", base.pesos, CAMPOS_DE_PESO)
    busca = secao("busca", base.busca, CAMPOS_DE_BUSCA)
    pesos.validar("ajuste")
    busca.validar("ajuste")
    return pesos, busca


def _limites_do_corpo(corpo: dict[str, Any]) -> LimitesDeIndexacao:
    """Lê o mapa tipo → MB. 0 é sem teto; negativo ou tipo desconhecido é erro."""
    bruto = corpo.get("limites")
    if not isinstance(bruto, dict):
        raise ValueError("'limites' precisa ser um objeto com o teto em MB de cada tipo")
    conhecidos = set(LimitesDeIndexacao.__dataclass_fields__)
    desconhecidos = sorted(set(bruto) - conhecidos)
    if desconhecidos:
        raise ValueError(
            f"tipo desconhecido: {', '.join(desconhecidos)} "
            f"(conhecidos: {', '.join(sorted(conhecidos))})"
        )
    convertidos: dict[str, float] = {}
    for chave, valor in bruto.items():
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise ValueError(f"limite '{chave}' precisa ser um número em MB (0 = sem teto)")
        convertidos[chave] = float(valor)
    limites = replace(LimitesDeIndexacao(), **convertidos)
    limites.validar("limites")
    return limites


def criar_app(
    caminho_config: Path,
    *,
    medidor: Callable[[Any, Pesos, Busca], dict[str, Any]],
    token: str,
    diagnosticador: Callable[[Any, Pesos, Busca, str], dict[str, Any]] | None = None,
):
    """Monta a aplicação. `medidor` e `diagnosticador` são injetados porque abrem
    o encoder e o índice — o teste não pode pagar isso para verificar uma regra.
    """
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse
    from starlette.routing import Route

    medicoes = Medicoes()

    def autorizado(request: Request) -> bool:
        """Porta local não é porta privada: qualquer processo da máquina alcança."""
        enviado = request.headers.get("x-painel-token") or request.query_params.get("token", "")
        return hmac.compare_digest(enviado, token)

    def _golden_padrao() -> Path:
        return caminho_config.parent / "eval" / "golden" / "perguntas.jsonl"

    def _glossario_padrao(base) -> Path:  # noqa: ANN001
        """Ao lado do config, não dentro do índice: o dicionário é do usuário e
        tem que sobreviver a um `--reindexar` que apague a pasta do índice."""
        return caminho_config.parent / f"glossario-{base.id}.toml"

    def _config():  # noqa: ANN202
        """Lê o `config.toml` se existir; senão, descobre (census.toml, padrões).

        Assimetria de propósito: ler cai para a descoberta, gravar sempre escreve
        em `caminho_config`. É o que faz o painel **materializar** o config.toml
        no primeiro salvamento, a partir da base sintetizada do `census.toml` —
        em vez de recusar-se a abrir porque o arquivo que ele mesmo criaria ainda
        não existe.
        """
        return carregar(caminho_config if caminho_config.exists() else None, ambiente={})

    def _base(conf, corpo: dict[str, Any]):  # noqa: ANN001, ANN202
        return conf.base(corpo.get("base") or None, ambiente={})

    async def estado(request: Request) -> JSONResponse:
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        try:
            conf = _config()
        except ErroDeConfig as erro:
            # Configuração ilegível é erro do usuário, não defeito do servidor:
            # devolver 500 esconderia a mensagem que diz como consertar.
            return JSONResponse({"erro": str(erro), "bases": []}, status_code=400)
        from ..index.esforco import planar

        maquina = {
            "perfil": conf.maquina.perfil,
            "threads": conf.maquina.threads,
            "lote": conf.maquina.lote,
            "provider": conf.maquina.provider,
            "limites": conf.maquina.limites.como_json(),
            "plano": planar(conf.maquina.perfil).como_json(),
        }
        return JSONResponse(
            {
                "config": str(caminho_config),
                "maquina": maquina,
                "limites_recomendados": LIMITES_RECOMENDADOS.como_json(),
                "limites_fabrica": LimitesDeIndexacao().como_json(),
                "bases": [
                    {
                        "id": b.id,
                        "nome": b.titulo,
                        "descricao": b.descricao,
                        "indice": str(b.indice),
                        "indexada": b.indexada,
                        "indexando": (b.indice / NOME_DA_TRAVA).exists(),
                        "modelo": b.modelo,
                        "pesos": dict(b.pesos.__dict__),
                        "busca": dict(b.busca.__dict__),
                        "raizes": [str(r.path) for r in b.raizes],
                        "limites": b.limites.como_json(),
                        # Quantas perguntas medem esta base. Perfil medido contra
                        # quatro perguntas não é perfil medido, e a tela precisa
                        # poder dizer isso.
                        "dourado": len(_ids_do_dourado(b.dourado or _golden_padrao())),
                    }
                    for b in conf.bases
                ],
            }
        )

    async def medir(request: Request) -> JSONResponse:
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        try:
            conf = _config()
            base = _base(conf, corpo)
            pesos, busca = _ajuste_de(corpo, base)
        except (ErroDeConfig, ValueError) as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        if (base.indice / NOME_DA_TRAVA).exists():
            # Medir contra um índice sendo reescrito mede um alvo em movimento.
            return JSONResponse(
                {"erro": f"a base '{base.id}' está sendo indexada — medir agora daria número instável"},
                status_code=409,
            )

        resultado = medidor(base, pesos, busca)
        medicoes.registrar(base.id, pesos, busca, resultado)
        return JSONResponse({"base": base.id, "medicao": resultado})

    async def salvar(request: Request) -> JSONResponse:
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        try:
            conf = _config()
            base = _base(conf, corpo)
            pesos, busca = _ajuste_de(corpo, base)
        except (ErroDeConfig, ValueError) as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        medicao = medicoes.de(base.id, pesos, busca)
        if medicao is None:
            # Invariante 4. A tela também desabilita o botão, mas a tela é
            # sugestão; a regra é aqui.
            return JSONResponse(
                {"erro": "esta configuração ainda não foi medida — meça antes de salvar"},
                status_code=409,
            )

        novas = tuple(
            replace(b, pesos=pesos, busca=busca) if b.id == base.id else b for b in conf.bases
        )
        try:
            gravar(replace(conf, bases=novas), caminho_config)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        log.info("base '%s' salva em %s", base.id, caminho_config)
        return JSONResponse({"base": base.id, "salvo": True, "medicao": medicao})

    async def diagnostico(request: Request) -> JSONResponse:
        """Por que este documento veio em primeiro — a pergunta real de quem ajusta.

        Não é UI de consulta: devolve procedência, posição em cada ranking antes
        da fusão e contribuição de cada ranqueador. Sem texto gerado.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        if diagnosticador is None:
            return JSONResponse({"erro": "diagnóstico indisponível"}, status_code=501)
        corpo = await request.json()
        consulta = (corpo.get("consulta") or "").strip()
        if not consulta:
            return JSONResponse({"erro": "consulta vazia"}, status_code=400)
        try:
            conf = _config()
            base = _base(conf, corpo)
            pesos, busca = _ajuste_de(corpo, base)
        except (ErroDeConfig, ValueError) as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        return JSONResponse({"base": base.id, "consulta": consulta,
                             "resultado": diagnosticador(base, pesos, busca, consulta)})

    async def dourado(request: Request) -> JSONResponse:
        """Acrescenta uma pergunta ao conjunto dourado da base.

        É o que faz "otimizar para o meu caso" ser verdade: sem isto, os perfis
        são medidos contra as 45 perguntas de outra pessoa. Só acrescenta —
        apagar pergunta já medida invalidaria comparação histórica.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        pergunta = (corpo.get("pergunta") or "").strip()
        fontes = [f for f in (corpo.get("fontes") or []) if f]
        if not pergunta or not fontes:
            return JSONResponse({"erro": "pergunta e ao menos uma fonte"}, status_code=400)
        try:
            conf = _config()
            base = _base(conf, corpo)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        alvo = base.dourado or _golden_padrao()
        existentes = _ids_do_dourado(alvo)
        novo = {
            "id": _proximo_id(existentes),
            "tipo": corpo.get("tipo") or "semantica",
            "pergunta": pergunta,
            "fontes": fontes,
            "autoria": "usuario",
            "validada": True,
            "base": base.id,
        }
        alvo.parent.mkdir(parents=True, exist_ok=True)
        with alvo.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(novo, ensure_ascii=False) + "\n")
        log.info("pergunta %s acrescentada ao dourado de '%s'", novo["id"], base.id)
        return JSONResponse({"id": novo["id"], "total": len(existentes) + 1, "arquivo": str(alvo)})

    async def glossario(request: Request) -> JSONResponse:
        """Lista (GET) e ensina (POST) uma sigla do acervo de quem está usando.

        Esta é a feature, não um acessório dela. Medido em 18/08/2026
        (`docs/ablacao-glossario.md`): o grupo de entradas genéricas — as que
        serviriam a qualquer acervo — mediu **zero** ganho, e as específicas da
        empresa produziram o ganho inteiro. Um glossário que exija editar TOML
        entrega zero justamente para o usuário que tem as siglas que importam.

        Grava sem exigir medição, ao contrário de `salvar`: a invariante 4 é sobre
        mudar ranking, e uma sigla é vocabulário do acervo, não peso. Além disso o
        efeito é por pergunta e não aparece numa média de 45 — exigir medição aqui
        travaria a única fonte de dado que o sistema não tem como adivinhar.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        if request.method == "POST":
            corpo = await request.json()
        else:
            corpo = {"base": request.query_params.get("base")}
        try:
            conf = _config()
            base = _base(conf, corpo)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        alvo = base.glossario or _glossario_padrao(base)
        atual = Glossario.de_arquivo(alvo)
        if request.method != "POST":
            return JSONResponse(
                {"arquivo": str(alvo), "termos": {s: list(f) for s, f in atual.termos.items()}}
            )

        sigla = (corpo.get("sigla") or "").strip()
        formas = [f.strip() for f in (corpo.get("formas") or []) if (f or "").strip()]
        try:
            novo = atual.com(sigla, formas)
        except ValueError:
            return JSONResponse({"erro": "sigla e ao menos uma forma por extenso"}, status_code=400)
        try:
            novo.gravar(alvo)
        except ErroDeGlossario as erro:
            return JSONResponse({"erro": str(erro)}, status_code=500)

        # O arquivo sozinho não muda recuperação: quem lê o glossário é a base.
        # Apontar na primeira gravação é o que impede o caso "ensinei e não mudou
        # nada" — que seria indistinguível de a expansão não funcionar.
        if base.glossario is None:
            gravar(replace(conf, bases=tuple(
                replace(b, glossario=alvo) if b.id == base.id else b for b in conf.bases
            )), caminho_config)
            log.info("base '%s' passou a apontar o glossário %s", base.id, alvo)
        log.info("sigla '%s' ensinada na base '%s'", sigla, base.id)
        return JSONResponse({"arquivo": str(alvo), "total": len(novo.termos), "sigla": sigla})

    async def indexacao(request: Request) -> JSONResponse:
        """Estado da indexação de cada base — lido, nunca comandado daqui.

        O indexador é processo independente que publica; o painel lê. Fechar esta
        tela não para nada, e a linha de comando continua completa. É a mesma
        razão da invariante 6, um nível acima.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        from ..index.progresso import ler

        try:
            conf = _config()
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro), "bases": {}}, status_code=400)

        return JSONResponse(
            {
                "bases": {
                    b.id: {
                        "indexando": (b.indice / NOME_DA_TRAVA).exists(),
                        "progresso": ler(b.indice),
                    }
                    for b in conf.bases
                }
            }
        )

    async def retomada(request: Request) -> JSONResponse:
        """Retomada automática depois de reinício — estado (GET) e liga/desliga (POST).

        Uma indexação deste acervo levou 39 h de trabalho efetivo e 64 h de parede.
        Nesse intervalo a máquina reinicia, e sem esta tarefa a retomada depende de
        alguém lembrar de digitar um comando — que é exatamente o que o usuário
        não-técnico deste painel não vai fazer.

        **Aqui o painel comanda, e é a única exceção da tela.** O endpoint
        `indexacao` acima só lê, de propósito. A diferença é que instalar a tarefa
        é ato de configuração, não de recuperação: acontece uma vez, fora do
        caminho de consulta, e o que ele agenda é o indexador — que segue processo
        independente. A invariante 6 continua de pé, e desligar é apagar o
        `.cmd` da pasta de inicialização — o `schtasks /SC ONLOGON` exige
        elevação neste Windows e foi recusado.

        **Nunca acontece por efeito colateral:** só em POST com `ligar`
        explícito no corpo.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        from ..index.retomada import NOME_DA_TAREFA, instalada, pendentes

        if request.method == "POST":
            corpo = await request.json()
            ligar = corpo.get("ligar")
            if not isinstance(ligar, bool):
                return JSONResponse({"erro": "'ligar' precisa ser true ou false"}, status_code=400)
            from ..index.retomada import agendar

            if agendar(instalar=ligar) != 0:
                from ..index.retomada import caminho_do_gatilho

                # Dizer **qual arquivo** falhou é o que torna o erro acionável: o
                # gatilho é um `.cmd` na pasta de inicialização, e o usuário pode
                # criá-lo ou apagá-lo à mão se o painel não conseguir.
                return JSONResponse(
                    {
                        "erro": "não consegui escrever na pasta de inicialização do "
                        f"Windows ({caminho_do_gatilho().parent}). Verifique se ela "
                        "existe e se o antivírus não está bloqueando."
                    },
                    status_code=500,
                )

        try:
            conf = _config()
            aguardando = [b.id for b, _ in pendentes(conf)]
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        return JSONResponse(
            {
                "instalada": instalada(),
                "tarefa": NOME_DA_TAREFA,
                "aguardando": aguardando,
            }
        )

    async def maquina(request: Request) -> JSONResponse:
        """Perfil de esforço e threads — grava direto, sem exigir medição.

        A invariante 4 exige medir antes de salvar **mudança de ranking**. Isto
        não é: `[maquina]` muda a velocidade com que o índice é produzido e nunca
        o conteúdo dele (`ARCHITECTURE.md` §4), então não há métrica que se mova.
        Exigir medição aqui seria ritual, e ritual ensina o usuário a ignorar a
        regra nos lugares onde ela importa.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        from ..config import PERFIS, normalizar_perfil

        perfil = normalizar_perfil(str(corpo.get("perfil") or ""))
        if perfil not in PERFIS:
            return JSONResponse(
                {"erro": f"perfil precisa ser um de {', '.join(PERFIS)}"},
                status_code=400,
            )
        try:
            conf = _config()
            nova = replace(conf.maquina, perfil=perfil)
            if "threads" in corpo:
                nova = replace(nova, threads=corpo["threads"] or None)
            gravar(replace(conf, maquina=nova), caminho_config)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        from ..index.esforco import pedir as pedir_esforco
        from ..index.esforco import planar

        for b in conf.bases:
            if (b.indice / NOME_DA_TRAVA).exists():
                pedir_esforco(b.indice, perfil)

        log.info("perfil de máquina salvo: %s", perfil)
        return JSONResponse(
            {
                "perfil": perfil,
                "threads": nova.threads,
                "plano": planar(perfil).como_json(),
                "ao_vivo": any((b.indice / NOME_DA_TRAVA).exists() for b in conf.bases),
            }
        )

    async def raizes(request: Request) -> JSONResponse:
        """Re-aponta as pastas de uma base — o caso de copiar o índice de máquina.

        Classe **de instalação**, não de ajuste: mudar as pastas muda o que entra
        no acervo. Por isso exige `confirmo` no corpo e devolve o aviso de que
        **nada reindexa sozinho** — o índice existente continua valendo, e é
        exatamente isso que torna útil re-apontar depois de copiar.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        caminhos = [c for c in (corpo.get("raizes") or []) if str(c).strip()]
        if not caminhos:
            return JSONResponse({"erro": "informe ao menos uma pasta"}, status_code=400)
        if not corpo.get("confirmo"):
            return JSONResponse(
                {"erro": "mudar as pastas altera o acervo — confirme explicitamente"},
                status_code=409,
            )
        try:
            conf = _config()
            base = _base(conf, corpo)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        ausentes = [c for c in caminhos if not Path(c).expanduser().is_dir()]
        if ausentes:
            return JSONResponse(
                {"erro": f"pasta não encontrada: {', '.join(ausentes)}"}, status_code=400
            )

        novas_raizes = tuple(
            RootSpec(name=Path(c).name or f"raiz{i}", path=Path(c).expanduser())
            for i, c in enumerate(caminhos, start=1)
        )
        atualizada = replace(base, raizes=novas_raizes)
        try:
            gravar(
                replace(
                    conf,
                    bases=tuple(atualizada if b.id == base.id else b for b in conf.bases),
                ),
                caminho_config,
            )
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        log.info("raízes da base '%s' re-apontadas", base.id)
        return JSONResponse(
            {
                "base": base.id,
                "raizes": [str(r.path) for r in novas_raizes],
                "aviso": "nada foi reindexado: o índice existente continua valendo. "
                "Rode o indexador se os documentos mudaram.",
            }
        )

    async def limites(request: Request) -> JSONResponse:
        """Teto de MB por tipo ao indexar. Grava direto: não é ranking.

        Arquivo acima do teto fica `adiado`, não some. Já no índice continua até
        mudar no disco. A passada em voo nasceu com o mapa antigo — vale na
        próxima. Não é `chunking.max_chars`: aquele muda todos os ids.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        try:
            conf = _config()
            base = _base(conf, corpo)
            novos = _limites_do_corpo(corpo)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)
        except ValueError as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        atualizada = replace(base, limites=novos)
        maquina = replace(conf.maquina, limites=novos)
        try:
            gravar(
                replace(
                    conf,
                    maquina=maquina,
                    bases=tuple(atualizada if b.id == base.id else b for b in conf.bases),
                ),
                caminho_config,
            )
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        log.info("limites de indexação da base '%s' salvos: %s", base.id, novos.como_mapa())
        return JSONResponse(
            {
                "base": base.id,
                "limites": novos.como_json(),
                "aviso": "Salvo. Vale na próxima passada desta base e nas bases novas desta máquina. "
                "Arquivos já indexados não saem sozinhos. 0 MB = sem teto.",
            }
        )

    async def censo(request: Request) -> JSONResponse:
        """Prévia de pastas antes de indexar. Só metadado, nunca conteúdo."""
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        caminhos = [c for c in (corpo.get("raizes") or []) if str(c).strip()]
        if not caminhos:
            return JSONResponse({"erro": "informe ao menos uma pasta"}, status_code=400)

        from .censo import prever

        return JSONResponse(prever(caminhos).como_json())

    async def criar_base(request: Request) -> JSONResponse:
        """Cria a base no `config.toml`, materializando-o se preciso.

        Não indexa: criar e indexar são decisões separadas, e a segunda custa
        horas. O usuário vê a prévia entre as duas.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        caminhos = [c for c in (corpo.get("raizes") or []) if str(c).strip()]
        if not caminhos:
            return JSONResponse({"erro": "informe ao menos uma pasta"}, status_code=400)

        try:
            conf = _config()
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        id_ = (corpo.get("id") or "").strip().lower()
        nova = Base(
            id=id_,
            nome=(corpo.get("nome") or "").strip(),
            descricao=(corpo.get("descricao") or "").strip(),
            indice=caminho_config.parent / f"index-{id_}",
            modelo=corpo.get("modelo") or Base.modelo,
            limites=conf.maquina.limites,
            raizes=tuple(
                RootSpec(name=Path(c).name or f"raiz{i}", path=Path(c).expanduser())
                for i, c in enumerate(caminhos, start=1)
            ),
        )
        if any(b.id == id_ for b in conf.bases):
            return JSONResponse({"erro": f"já existe uma base '{id_}'"}, status_code=409)

        try:
            gravar(replace(conf, bases=(*conf.bases, nova)), caminho_config)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        log.info("base '%s' criada em %s", id_, caminho_config)
        return JSONResponse({"id": id_, "indice": str(nova.indice)})

    async def comando(request: Request) -> JSONResponse:
        """Pausa, continua ou cancela. Só grava um arquivo; o indexador obedece.

        O painel não mata o processo. Matar perderia o documento em voo; o
        pedido deixa o commit do atual terminar. Sem indexação viva, recusa —
        um `comando.txt` órfão na próxima largada seria apagado de qualquer jeito.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        acao = (corpo.get("acao") or "").strip()
        try:
            conf = _config()
            base = _base(conf, corpo)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        from ..index.comando import CANCELAR, PAUSAR, ler, limpar, pedir

        viva = (base.indice / NOME_DA_TRAVA).exists()
        if acao in {PAUSAR, CANCELAR} and not viva:
            return JSONResponse(
                {"erro": f"a base '{base.id}' não está sendo indexada"}, status_code=409
            )
        if acao == PAUSAR:
            pedir(base.indice, PAUSAR)
        elif acao == CANCELAR:
            pedir(base.indice, CANCELAR)
        elif acao == "retomar":
            if ler(base.indice) == PAUSAR:
                limpar(base.indice)
        else:
            return JSONResponse(
                {"erro": "acao deve ser pausar, retomar ou cancelar"}, status_code=400
            )
        return JSONResponse({"base": base.id, "acao": acao, "comando": ler(base.indice)})

    async def indexar(request: Request) -> JSONResponse:
        """Dispara o indexador como processo **independente**.

        Desanexado de propósito: fechar o painel — ou perder a aba — não pode
        parar uma indexação de horas. O painel volta a ser só observador no
        instante seguinte, e quem acompanha é `/api/indexacao`.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        try:
            conf = _config()
            base = _base(conf, corpo)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        if (base.indice / NOME_DA_TRAVA).exists():
            return JSONResponse(
                {"erro": f"a base '{base.id}' já está sendo indexada"}, status_code=409
            )

        from ..config import normalizar_perfil

        perfil = normalizar_perfil(corpo.get("perfil") or conf.maquina.perfil)
        comando = [
            sys.executable, "-m", "segundocerebro.index.indexer",
            "--base", base.id, "--config", str(caminho_config), "--perfil", perfil,
        ]
        # `DETACHED_PROCESS` no Windows, `start_new_session` no resto: sem isto o
        # filho morre com o painel, e a indexação viraria hostage da aba aberta.
        extras: dict[str, Any] = {"cwd": str(caminho_config.parent)}
        if hasattr(subprocess, "DETACHED_PROCESS"):
            extras["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            extras["start_new_session"] = True

        filho = subprocess.Popen(  # noqa: S603 — comando montado aqui, não pelo usuário
            comando,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **extras,
        )
        log.info("indexação da base '%s' iniciada (pid %s, perfil %s)", base.id, filho.pid, perfil)
        return JSONResponse({"base": base.id, "pid": filho.pid, "perfil": perfil})

    async def registro(request: Request) -> JSONResponse:
        """O trecho de `.mcp.json` da base — o último degrau para usar de verdade."""
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        try:
            conf = _config()
            base = conf.base(request.query_params.get("base") or None, ambiente={})
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        from ..mcp.registrar import trecho

        return JSONResponse(
            {"base": base.id, "json": trecho([base], nomear=conf.caminho is not None)}
        )

    async def conectar(request: Request) -> JSONResponse:
        """Grava no arquivo do Claude Desktop. Grok/Claude Code já leem `.mcp.json`.

        Sem este POST o leigo ainda precisa do terminal (`--instalar`). A mescla
        é a mesma do CLI: não apaga os outros servidores do arquivo.
        """
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        corpo = await request.json()
        try:
            conf = _config()
            base = _base(conf, corpo)
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)

        cliente = corpo.get("cliente") or "claude-desktop"
        from ..mcp.registrar import (
            CLIENTES,
            DESTINOS,
            RELATIVO,
            destino_de,
            extra_env_hardware,
            gravar_em,
            python_do_projeto,
        )

        if cliente not in DESTINOS:
            return JSONResponse(
                {
                    "erro": (
                        f"{cliente} não tem arquivo de configuração conhecido. "
                        "Grok e Claude Code leem o .mcp.json da pasta do projeto — "
                        "recarregue o cliente. Claude Desktop é o que este botão liga."
                    )
                },
                status_code=400,
            )
        destino = destino_de(cliente)
        if destino is None:
            return JSONResponse(
                {"erro": f"não sei onde {cliente} guarda a configuração"},
                status_code=400,
            )
        if not destino.parent.is_dir():
            return JSONResponse(
                {
                    "erro": (
                        f"{CLIENTES[cliente]} não existe — {cliente} não parece "
                        "instalado neste computador"
                    )
                },
                status_code=409,
            )
        try:
            existente: dict[str, Any] = {}
            if destino.exists():
                try:
                    existente = json.loads(destino.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return JSONResponse(
                        {
                            "erro": (
                                f"{destino} não é JSON válido — não vou "
                                "sobrescrever a configuração dos outros"
                            )
                        },
                        status_code=400,
                    )
            acrescentados, trocados = gravar_em(
                destino,
                [base],
                nomear=True,
                absoluto=cliente not in RELATIVO,
                python=python_do_projeto(relativo=cliente in RELATIVO),
                extra_env=extra_env_hardware(conf, existente),
            )
        except ErroDeConfig as erro:
            return JSONResponse({"erro": str(erro)}, status_code=400)
        return JSONResponse(
            {
                "base": base.id,
                "cliente": cliente,
                "destino": str(destino),
                "acrescentados": acrescentados,
                "trocados": trocados,
            }
        )

    async def pagina(request: Request) -> HTMLResponse:
        """A tela. O token vem na URL e o JavaScript o repassa em cada chamada."""
        return HTMLResponse((Path(__file__).parent / "index.html").read_text(encoding="utf-8"))

    async def perfis(request: Request) -> JSONResponse:
        if not autorizado(request):
            return JSONResponse({"erro": "token inválido"}, status_code=403)
        from .perfis import como_json

        return JSONResponse({"perfis": como_json()})

    return Starlette(
        routes=[
            Route("/", pagina),
            Route("/api/estado", estado),
            Route("/api/perfis", perfis),
            Route("/api/indexacao", indexacao),
            Route("/api/retomada", retomada, methods=["GET", "POST"]),
            Route("/api/maquina", maquina, methods=["POST"]),
            Route("/api/raizes", raizes, methods=["POST"]),
            Route("/api/limites", limites, methods=["POST"]),
            Route("/api/censo", censo, methods=["POST"]),
            Route("/api/base", criar_base, methods=["POST"]),
            Route("/api/indexar", indexar, methods=["POST"]),
            Route("/api/comando", comando, methods=["POST"]),
            Route("/api/registro", registro),
            Route("/api/conectar", conectar, methods=["POST"]),
            Route("/api/medir", medir, methods=["POST"]),
            Route("/api/salvar", salvar, methods=["POST"]),
            Route("/api/diagnostico", diagnostico, methods=["POST"]),
            Route("/api/dourado", dourado, methods=["POST"]),
            Route("/api/glossario", glossario, methods=["GET", "POST"]),
        ]
    )


def _ids_do_dourado(caminho: Path) -> list[str]:
    if not caminho.exists():
        return []
    ids = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            try:
                ids.append(json.loads(linha)["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def _proximo_id(existentes: list[str]) -> str:
    """`g001`, `g002`… continuando de onde o arquivo parou."""
    numeros = [int(i[1:]) for i in existentes if i.startswith("g") and i[1:].isdigit()]
    return f"g{max(numeros, default=0) + 1:03d}"


def gerar_token() -> str:
    return secrets.token_urlsafe(24)


PORTA_PADRAO = 18787
"""Porta fixa para o atalho do Windows reabrir a mesma URL.

0 (livre) fazia cada abertura nascer noutro endereço, e o usuário não tinha
como voltar à tela sem perguntar ao agente."""

SESSAO_PAINEL = ".painel.json"


def caminho_da_sessao(config: Path) -> Path:
    return Path(config).expanduser().resolve().parent / SESSAO_PAINEL


def ler_sessao(config: Path) -> dict[str, Any] | None:
    alvo = caminho_da_sessao(config)
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(dados, dict):
        return None
    porta, token = dados.get("porta"), dados.get("token")
    if not isinstance(porta, int) or not isinstance(token, str) or not token:
        return None
    return {"porta": porta, "token": token, "url": dados.get("url") or f"http://127.0.0.1:{porta}/?token={token}"}


def gravar_sessao(config: Path, porta: int, token: str) -> None:
    alvo = caminho_da_sessao(config)
    payload = {
        "porta": porta,
        "token": token,
        "url": f"http://127.0.0.1:{porta}/?token={token}",
    }
    tmp = alvo.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(alvo)


def painel_responde(porta: int, token: str, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """True se já há um painel vivo nesta porta com este token."""
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    pedido = Request(
        f"http://{host}:{porta}/api/estado",
        headers={"x-painel-token": token},
        method="GET",
    )
    try:
        with urlopen(pedido, timeout=timeout) as resp:  # noqa: S310 — loopback, token obrigatório
            return 200 <= getattr(resp, "status", 200) < 300
    except (URLError, TimeoutError, OSError):
        return False
