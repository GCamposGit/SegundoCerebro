"""Nucleo: Doc, renderizacao multi-formato, manifesto com hash logico."""
import hashlib, itertools, zipfile
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
         criterio="qualquer", **meta):
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
            "feature_alvo": feature_alvo, "meta": meta}

def moeda(v):
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"

def detectar_caps():
    try:
        import docx  # noqa
        return {"docx": True}
    except Exception:
        return {"docx": False}

def picker(caps):
    exts = ["txt", "txt", "md", "txt"] + (["docx"] if caps.get("docx") else ["txt"])
    c = itertools.cycle(exts)
    return lambda: next(c)

def escrever(doc, raiz):
    p = raiz / doc.caminho
    p.parent.mkdir(parents=True, exist_ok=True)
    if doc.formato in ("txt", "md", "csv"):
        p.write_text(doc.texto, encoding="utf-8")
    elif doc.formato == "docx":
        import docx as dx
        d = dx.Document()
        for par in doc.texto.split("\n"):
            d.add_paragraph(par)
        d.save(str(p))
    elif doc.formato == "pdf_veneno":   # PDF truncado (R1.4)
        p.write_bytes(b"%PDF-1.4\n" + b"\x00\x01lixo" * 40)
    elif doc.formato == "zip_veneno":   # ZIP renomeado p/ .docx (R1.4)
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("x/nada.bin", b"\x00" * 128)
    elif doc.formato == "vazio":
        p.write_bytes(b"")
    else:
        raise ValueError(doc.formato)

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
