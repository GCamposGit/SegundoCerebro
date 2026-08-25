"""Nucleo: Doc, renderizacao multi-formato, manifesto com hash logico."""
import hashlib, itertools
from dataclasses import dataclass, field

from ..harness import IDIOMAS_ACEITOS, PT

@dataclass
class Doc:
    caminho: str
    texto: str
    formato: str = "txt"  # txt|md|csv|docx|pdf_veneno|zip_veneno|vazio
    meta: dict = field(default_factory=dict)

def mkdoc(pasta, nome, texto, ext="txt", **meta):
    return Doc(f"{pasta}/{nome}.{ext}", texto, formato=ext, meta=meta)

def perg(pid, armadilha_fatia, pergunta, resposta, docs, tipo="exato",
         idioma=PT, idioma_fonte=PT, armadilha="", feature_alvo="",
         criterio="qualquer", fora_de_escopo="", **meta):
    """Uma pergunta com gabarito. Emite os **dois** campos de idioma, sempre.

    **`armadilha_fatia`, e nao `fatia`** -- achado 8 do laudo. O harness ja tem
    dois eixos de recorte com projeto deliberadamente diferente: `idioma_fonte` e
    anotacao estatica porque nao e derivavel sem abrir o indice, e
    `grupo_de_fonte` e derivado porque o caminho ja esta no dourado. A armadilha
    plantada e um **terceiro** eixo, e ele e anotacao por construcao -- so o
    gerador sabe o que plantou. `fatia` fica reservado ao idioma, para nao
    reescrever o `C4.5`.

    **Os dois campos de idioma tem default `pt` e nao vazio**, e essa e a licao do
    achado 3: `idioma_fonte` nunca era emitido, as 260 perguntas saiam
    `{'nao declarado': 260}`, a fatia cross-lingual ficava de tamanho zero e o
    relatorio saia parecendo aprovado. **Declarar `pt` e diferente de omitir**, e
    e a omissao que mata a fatia. Nas dez fatias que nao cruzam idioma os dois sao
    `pt`; na cross-lingual eles divergem, que e o ponto dela.

    **`fora_de_escopo`** e chave de `harness.MOTIVOS_FORA_DE_ESCOPO`, e ela existe
    para a pergunta que nao e mensuravel nesta fase ficar **visivel e anotada** em
    vez de nao existir. `carregar_perguntas` recusa motivo fora do catalogo, e o
    catalogo encurta quando a capacidade entra -- entao a anotacao velha nao
    atravessa a fase em silencio.

    A validacao contra `IDIOMAS_ACEITOS` acontece **aqui**, na emissao, e nao so
    no `carregar_perguntas` -- o gerador que veio no pacote escrevia a travessia
    (`pt->en`) num campo que guarda idioma, e um produtor que nao consegue emitir
    codigo invalido e melhor que um consumidor que o rejeita depois.
    """
    for campo, valor in (("idioma", idioma), ("idioma_fonte", idioma_fonte)):
        if valor not in IDIOMAS_ACEITOS:
            raise ValueError(
                f"{pid}: {campo}={valor!r} nao e codigo de idioma -- use um de "
                f"{sorted(IDIOMAS_ACEITOS)}. Travessia (`pt->en`) nao e idioma: "
                f"ela sai de `idioma` mais `idioma_fonte`, que o harness cruza."
            )
    return {"id": pid, "armadilha_fatia": armadilha_fatia, "pergunta": pergunta,
            "resposta_esperada": resposta, "docs_relevantes": docs,
            "criterio": criterio, "tipo": tipo, "idioma": idioma,
            "idioma_fonte": idioma_fonte, "armadilha": armadilha,
            "fora_de_escopo": fora_de_escopo,
            "feature_alvo": feature_alvo, "meta": meta}

def moeda(v):
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"

DISTRIBUICAO_DO_CENSO = (("pdf", 478), ("xlsx", 218), ("docx", 147),
                         ("pptx", 80), ("md", 12), ("txt", 4))
"""Formato do corpus sintetico, em milesimos, calibrado pelo censo do acervo real.

Condicao 4 do laudo. O gerador do pacote emitia **80% `.txt`** e zero PDF com
conteudo, zero `.xlsx`, zero `.pptx` -- um corpus que mede um caminho de codigo
que o produto quase nao usa. O acervo real e 47,8% `.pdf`, 21,8% `.xlsx`, 14,7%
`.docx`, 8,0% `.pptx` (`docs/censo.md`, gitignorado; os agregados sao os que o
`CLAUDE.md` ja publica como "74% PDF+DOCX").

Os pesos sao os do censo sem renormalizar: o que sobra (`.msg`, `.xls`, `.csv`,
sem extensao) ou tem fatia propria -- email e `planilha_despejo` escolhem o
formato delas -- ou e legado que o `F4-L` ainda nao le. Formato sem biblioteca
nesta maquina cai em `txt` e fica **registrado em `caps`**, que desde o `E1.a` e
dimensao do selo: um corpus gerado sem `pymupdf` nao se confunde com um gerado
com ele.
"""

BIBLIOTECA_DE = {"pdf": "pymupdf", "xlsx": "openpyxl", "pptx": "pptx", "docx": "docx"}
"""Que import prova a capacidade de escrever cada formato binario."""


def detectar_caps():
    """O que esta maquina consegue escrever. Vai para o manifesto e para o selo."""
    caps = {}
    for formato, modulo in BIBLIOTECA_DE.items():
        try:
            __import__(modulo)
            caps[formato] = True
        except Exception:
            caps[formato] = False
    return caps


def _padrao(pesos, tamanho=100):
    """Sequencia deterministica que respeita os pesos e os espalha.

    Round-robin ponderado suave: a cada passo todo formato acumula credito
    proporcional ao peso e o de maior credito paga um. Concatenar as fatias
    (`pdf`*51 + `xlsx`*23 + ...) tambem daria a proporcao certa no corpus
    inteiro, mas cada fatia pega um prefixo do ciclo -- e as fatias pequenas
    sairiam 100% PDF. Espalhar e o que faz a proporcao valer **por fatia**.
    """
    total = sum(peso for _, peso in pesos)
    credito = {formato: 0.0 for formato, _ in pesos}
    saida = []
    for _ in range(tamanho):
        for formato, peso in pesos:
            credito[formato] += peso / total
        escolhido = max(credito, key=lambda f: (credito[f], f))
        credito[escolhido] -= 1.0
        saida.append(escolhido)
    return saida


def picker(caps):
    """Sorteador de formato por documento, na distribuicao do censo.

    Formato sem biblioteca vira `txt`, e o peso dele vai junto -- e por isso que
    `--so-texto` produz um corpus 100% texto sem mudar a forma do codigo.
    """
    pesos = []
    para_texto = 0
    for formato, peso in DISTRIBUICAO_DO_CENSO:
        if formato in BIBLIOTECA_DE and not caps.get(formato):
            para_texto += peso
        else:
            pesos.append((formato, peso))
    if para_texto:
        pesos = [(f, p + para_texto if f == "txt" else p) for f, p in pesos]
    c = itertools.cycle(_padrao(pesos))
    return lambda: next(c)

from .escrita import escrever  # noqa: E402,F401  (reexportado: escrita.py e o dono)


DIMENSOES_DO_SELO = ("seed", "n_por_fatia", "caps")
"""O que identifica um corpus, alem do conteudo. O `E3` sela estas tres.

**O selo nao e a seed sozinha, e o achado 6 do laudo e o motivo.** O hash logico
esta certo em ignorar o binario (`.docx` embute timestamp), mas a entrada dele
inclui o **caminho**, e o caminho inclui a extensao, que sai de `detectar_caps()`.
Mesma seed com `python-docx` instalado e sem ele ja produzia agregados diferentes:

    --sem-docx        agregado ad7030086dbed99b...
    com python-docx   agregado 54873c29b838d32f...

Selar `caps` junto **nao** faz os dois corpora virarem um -- eles sao diferentes
de verdade. O que muda e o diagnostico: `conferir_selo` diz qual dimensao
divergiu, em vez de deixar o `E3` com um hash que nao bate e nenhuma explicacao a
vista. Um selo gerado no desktop com `python-docx` que rode no CI sem ele passa a
falhar dizendo `caps`, nao dizendo `agregado`.
"""


def manifesto(docs, seed, n, stats, caps=None):
    """Hash LOGICO (conteudo-fonte), nao binario: docx embute timestamps.

    `caps` entra na entrada do hash de proposito -- ver `DIMENSOES_DO_SELO`.
    """
    caps = dict(caps or {})
    ent = []
    for d in sorted(docs, key=lambda x: x.caminho):
        h = hashlib.sha256(d.texto.encode()).hexdigest() if d.texto else d.formato
        ent.append({"caminho": d.caminho, "formato": d.formato, "sha256_logico": h})
    marca_caps = ",".join(f"{k}={bool(v)}" for k, v in sorted(caps.items()))
    corpo = "\n".join(f"{e['caminho']}|{e['sha256_logico']}" for e in ent)
    ag = hashlib.sha256(
        (corpo + f"|seed={seed}|n={n}|caps={marca_caps}").encode()
    ).hexdigest()
    return {"seed": seed, "n_por_fatia": n, "caps": caps, "agregado": ag,
            "stats": stats, "arquivos": ent}


def conferir_selo(selo, atual):
    """Por que dois manifestos divergem. Devolve lista vazia quando batem.

    Confere as `DIMENSOES_DO_SELO` **antes** do agregado, e e essa ordem que e a
    entrega: agregado diferente e um sintoma que serve para todas as causas, e so
    uma delas e "o gerador mudou". Sem isto o `E3` reprovaria um test-set selado
    dizendo "hash diferente" quando a causa e `python-docx` ausente no CI --
    verdadeiro, inutil, e caro de descobrir.
    """
    divergencias = []
    for dim in DIMENSOES_DO_SELO:
        esperado, obtido = selo.get(dim), atual.get(dim)
        if esperado != obtido:
            divergencias.append(f"{dim}: selo tem {esperado!r}, esta maquina tem {obtido!r}")
    if divergencias:
        return divergencias
    if selo.get("agregado") != atual.get("agregado"):
        return [
            f"agregado: selo tem {str(selo.get('agregado'))[:16]}..., esta maquina tem "
            f"{str(atual.get('agregado'))[:16]}... -- as dimensoes do selo batem, "
            f"entao o gerador mudou"
        ]
    return []
