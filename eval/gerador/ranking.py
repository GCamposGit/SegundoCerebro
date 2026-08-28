"""As fatias que medem os mecanismos de recuperação que o projeto já construiu.

Cinco fatias, e cada uma existe porque **uma classe de defeito documentada neste
repositório não tinha nada que a medisse**. Não são hipóteses: são episódios com
data, número e post-mortem no `docs/historico-decisoes.md`.

| Fatia | O episódio que a motiva |
|---|---|
| `grafias` | as cinco correções do grafo (F4) — *"o mesmo identificador escrito de outra forma não liga"*, e nenhuma foi pega por teste unitário |
| `glossario` | o segundo maior ganho da F2 (+0,033) media só um sentido do cruzamento sigla ↔ forma por extenso |
| `familia_sem_numero` | a política vigente que **não declara** `_vN` e é mais nova que a `_v6` — o caso que fez a regra de família existir |
| `idioma_indeciso` | `misto` e `indefinido` são valores legítimos de `IDIOMAS_ACEITOS` que o corpus nunca emitia; `idioma.decidido()` tem um ramo inteiro que nada exercitava |
| `chunk_hostil` | a truncagem silenciosa de 13/08 — 80,7% do texto indexado nunca virou vetor |
"""

from __future__ import annotations

from . import vocabulario as V
from .nucleo import mkdoc, moeda, perg

# --- grafias de identificador ------------------------------------------------

PASTA_NORMAS = "12. Normas"


def f_grafias(rng, n, ext):  # noqa: ANN001
    """O mesmo identificador escrito de várias formas — e o par que **não** é o mesmo.

    A classe de defeito mais insidiosa que este projeto encontrou: cada grafia
    produz sua própria aresta, igualmente plausível, e nada parece errado. As
    cinco correções da F4 foram todas isto, e **nenhuma apareceu em teste
    unitário** — só ao olhar a distribuição real.

    Cada `i` planta duas coisas de uma vez:

    - **uma norma escrita de quatro jeitos** (`ISO 42001:2023`, `ISO 42001`,
      `ISO 42.001`, `ISO-420012023`), com a resposta num documento e a pergunta
      usando *outra* grafia. Só liga se a normalização funcionar.
    - **dois projetos de lei de mesmo número e anos diferentes**, que **não**
      podem ser unificados. Para norma promulgada o ano é decoração; para projeto
      de lei o ano é identidade, porque a numeração reinicia a cada ano. Unificar
      os dois seria a "correção" óbvia e estaria errada — por isso a fatia mede
      os dois sentidos.
    """
    docs, ps = [], []
    for i in range(n):
        numero = 40000 + i
        ano = 2019 + (i % 6)
        valor = rng.randrange(50, 900) * 1000
        grafias = [
            f"ISO {numero}:{ano}",
            f"ISO {numero}",
            f"ISO {numero // 1000}.{numero % 1000:03d}",
            f"ISO-{numero}{ano}",
        ]
        caminhos = []
        for k, grafia in enumerate(grafias):
            corpo = (
                f"NOTA TECNICA sobre a {grafia}\n"
                f"A auditoria de conformidade a {grafia} custou {moeda(valor)}.\n"
                if k == 0
                else f"REGISTRO INTERNO\nEste processo segue a {grafia}.\n"
            )
            d = mkdoc(f"{PASTA_NORMAS}/Conformidade", f"Nota {k} sobre norma {i:03d}", corpo, ext())
            caminhos.append(d.caminho)
            docs.append(d)
        # A pergunta usa a grafia CURTA; a resposta está no documento que usa a
        # LONGA. Sem normalização o bm25 não casa e o nome do arquivo não ajuda.
        ps.append(perg(
            f"q-gr-{i:03d}", "grafias",
            f"Quanto custou a auditoria de conformidade à {grafias[1]}?", moeda(valor),
            [caminhos[0]],
            armadilha="pergunta usa `ISO N`, documento usa `ISO N:ano`",
            feature_alvo="grafo/identificadores", grafias=grafias,
        ))

        pl_valor = rng.randrange(10, 90) * 1000
        pl_antigo = mkdoc(
            f"{PASTA_NORMAS}/Legislativo", f"Parecer PL {2000 + i} de 2019",
            f"PARECER sobre o PL {2000 + i}/2019\nImpacto estimado: {moeda(pl_valor * 7)}.\n",
            ext(),
        )
        pl_novo = mkdoc(
            f"{PASTA_NORMAS}/Legislativo", f"Parecer PL {2000 + i} de 2023",
            f"PARECER sobre o PL {2000 + i}/2023\nImpacto estimado: {moeda(pl_valor)}.\n",
            ext(),
        )
        docs += [pl_antigo, pl_novo]
        ps.append(perg(
            f"q-gr-pl-{i:03d}", "grafias",
            f"Qual o impacto estimado do PL {2000 + i}/2023?", moeda(pl_valor),
            [pl_novo.caminho],
            armadilha="mesmo numero, ano diferente: NAO e o mesmo projeto de lei",
            feature_alvo="grafo/identificadores", nao_unificar=pl_antigo.caminho,
        ))
    return docs, ps


# --- glossário nos dois sentidos ---------------------------------------------

PASTA_GLOSSARIO = "13. Normativos"

EXPANSOES = (
    ("acordo de protecao de dados", "APD"),
    ("plano de continuidade operacional", "PCO"),
    ("relatorio de impacto regulatorio", "RIR"),
    ("termo de encerramento de obra", "TEO"),
    ("matriz de risco integrada", "MRI"),
)
"""Pares genéricos, vocabulário da VCE. A sigla nunca é a de nenhum acervo real."""


def f_glossario(rng, n, ext):  # noqa: ANN001
    """Pergunta pela sigla × documento por extenso, **e o inverso**.

    O glossário é o segundo maior ganho da F2 (+0,033, custo zero por consulta), e
    o corpus media só metade dele: documentos que *definem* siglas. O que a
    feature resolve é o **cruzamento**, e o sentido que mais importa é o que
    `tests/test_glossario.py` já nomeia: *a pergunta é por extenso e o documento
    usa a sigla*.

    Duas perguntas por `i`, uma em cada sentido, apontando para documentos
    diferentes — então acertar um sentido e errar o outro aparece na tabela em vez
    de sumir na média.
    """
    docs, ps = [], []
    for i in range(n):
        extenso, sigla = EXPANSOES[i % len(EXPANSOES)]
        prazo = rng.randrange(5, 180)
        area = rng.choice(V.AREAS)

        so_sigla = mkdoc(
            f"{PASTA_GLOSSARIO}/{area}", f"Procedimento operacional {i:03d}",
            f"PROCEDIMENTO OPERACIONAL\nO {sigla} deve ser revisado a cada {prazo} dias.\n",
            ext(),
        )
        so_extenso = mkdoc(
            f"{PASTA_GLOSSARIO}/{area}", f"Manual de governanca {i:03d}",
            f"MANUAL DE GOVERNANCA\nO {extenso} e aprovado pela area de {area}.\n",
            ext(),
        )
        docs += [so_sigla, so_extenso]

        ps.append(perg(
            f"q-gl-sig-{i:03d}", "glossario",
            f"Quem aprova o {sigla}?", area, [so_extenso.caminho],
            armadilha="pergunta usa a sigla, documento usa a forma por extenso",
            feature_alvo="glossario", sentido="sigla->extenso",
        ))
        ps.append(perg(
            f"q-gl-ext-{i:03d}", "glossario",
            f"De quantos em quantos dias o {extenso} deve ser revisado?", f"{prazo} dias",
            [so_sigla.caminho],
            armadilha="pergunta por extenso, documento usa a sigla -- o sentido que mais importa",
            feature_alvo="glossario", sentido="extenso->sigla",
        ))
    return docs, ps


# --- família de versão sem número --------------------------------------------

PASTA_POLITICAS = "14. Politicas vigentes"


def f_familia_sem_numero(rng, n, ext):  # noqa: ANN001
    """A vigente **não** declara `_vN` e é mais nova que a `_v6`.

    É o caso que fez a regra de família existir, e o corpus não o tinha: a fatia
    `versoes` sempre marca a final com sufixo, que é o caso fácil. Aqui o número
    declarado aponta para o documento **errado** e só a data resolve — que é
    exatamente o desempate que `retrieve/familias.py` implementa.

    O `mtime` é fixado pelo gerador (`escrita._datar`). Sem isso a fatia mediria a
    ordem em que os arquivos foram escritos, que é acidente.
    """
    docs, ps = [], []
    for i in range(n):
        pol = f"PO-VCE-{100 + i:03d}"
        limites = rng.sample(range(20, 900), 3)
        base = f"{PASTA_POLITICAS}/{pol}"
        # `ext()` uma vez para a familia inteira, como em `f_duplicatas`: familia
        # de versao com extensoes diferentes seria outra armadilha, e misturar
        # duas numa fatia so torna o resultado ilegivel. A primeira versao gravava
        # `.txt` fixo e levou o `.txt` do corpus de 0,4% (censo) a 8,3% -- o
        # sorteador existe para as fatias nao decidirem formato por conta.
        formato = ext()
        antiga = mkdoc(base, f"{pol} Politica de alcadas_v1",
                       f"POLITICA {pol} - v1\nLimite de alcada: {moeda(limites[0] * 1000)}.\n",
                       formato, mtime="2021-03-04")
        numerada = mkdoc(base, f"{pol} Politica de alcadas_v6",
                         f"POLITICA {pol} - v6\nLimite de alcada: {moeda(limites[1] * 1000)}.\n",
                         formato, mtime="2023-07-19")
        vigente = mkdoc(base, f"{pol} Politica de alcadas_revisada_GC",
                        f"POLITICA {pol} - revisao vigente\n"
                        f"Limite de alcada: {moeda(limites[2] * 1000)}.\n",
                        formato, mtime="2026-05-30")
        docs += [antiga, numerada, vigente]
        ps.append(perg(
            f"q-fs-{i:03d}", "familia_sem_numero",
            f"Qual o limite de alcada vigente da politica {pol}?",
            moeda(limites[2] * 1000), [vigente.caminho],
            armadilha="a vigente nao declara _vN e e mais nova que a _v6: numero aponta errado",
            feature_alvo="familias/C6",
            familia=[antiga.caminho, numerada.caminho, vigente.caminho],
        ))
    return docs, ps


# --- idioma que o detector não resolve ---------------------------------------

PASTA_BILINGUE = "15. Bilingue"


def f_idioma_indeciso(rng, n, ext):  # noqa: ANN001
    """`misto` e `indefinido` — os dois códigos que o corpus nunca emitia.

    `IDIOMAS_ACEITOS` tem quatro valores e o gerador usava dois. Não é
    completismo: `idioma.decidido()` **exclui** `misto` e `indefinido` da fatia
    cross-lingual de propósito — *"um documento metade PT metade EN atende
    consulta nos dois idiomas, e contá-lo como acerto cross-lingual inflaria
    justamente a métrica que existe para achar a fraqueza da ponte"*. Esse ramo
    nunca era exercitado, então a proteção nunca era testada com dado.

    E `indefinido` na pergunta é um caso real e medido: **2 das 62 perguntas do
    acervo corporativo** são consulta curta de sigla e número, sem palavra
    funcional nenhuma — o detector não resolve, e declarar é melhor que baixar o
    limiar, que acertaria essas duas e passaria a errar as outras sessenta.
    """
    docs, ps = [], []
    for i in range(n):
        cid = f"CT-BL-{i:03d}"
        valor = rng.randrange(80, 7000) * 1000
        emp = rng.choice(V.EMPRESAS)

        # "Registro" e nao "Ata": `fonte.PASTAS_DE_REUNIAO` casa `atas?` no comeco
        # de qualquer segmento de caminho, inclusive o NOME DO ARQUIVO, e um "Ata
        # bilingue" cairia no grupo `reuniao` sem querer -- inflando de 30 para 60
        # um grupo que esta fatia nao mede. E o defeito que o proprio laudo do E1
        # apontou na fatia de duplicatas: "mistura de grupos por acidente, nao
        # fatia de reuniao". Quem mede reuniao e a fatia `reuniao`, de proposito.
        bilingue = mkdoc(
            PASTA_BILINGUE, f"Registro bilingue {cid}",
            f"REGISTRO DE DELIBERACAO / DECISION RECORD\n"
            f"Participantes / Participants: {emp}.\n"
            f"Ficou decidido aprovar o contrato {cid}. The approved amount is "
            f"{moeda(valor)}.\nProxima revisao / Next review: a definir / TBD.\n",
            ext(),
        )
        docs.append(bilingue)
        ps.append(perg(
            f"q-bl-{i:03d}", "idioma_indeciso",
            f"Qual o valor aprovado do contrato {cid}?", moeda(valor),
            [bilingue.caminho], idioma="pt", idioma_fonte="misto",
            armadilha="documento metade PT metade EN: nao conta como cross-lingual",
            feature_alvo="hybrid/C4.5",
        ))

        curto = mkdoc(
            PASTA_BILINGUE, f"Ficha {cid}",
            f"FICHA CADASTRAL\nContrato: {cid}\nFornecedora: {emp}\n"
            f"Vigencia: {rng.choice([12, 24, 36])} meses\n",
            ext(),
        )
        docs.append(curto)
        ps.append(perg(
            f"q-bl-sig-{i:03d}", "idioma_indeciso",
            cid, emp, [curto.caminho], idioma="indefinido", idioma_fonte="pt",
            armadilha="consulta e so sigla e numero: o detector de idioma nao resolve",
            feature_alvo="hybrid/C4.5-anotacao",
        ))
    return docs, ps


# --- chunking sob estresse ---------------------------------------------------

PASTA_CHUNK = "16. Anexos volumosos"

LINHAS_DA_TABELA = 900
"""Uma tabela que atravessa qualquer janela de modelo.

O maior chunk do índice MiniLM tinha **40.880 tokens** contra uma janela de 128, e
62,3% dos chunks estavam acima dela. Blocos marcados `never_split` — tabela,
planilha — atravessavam inteiros. A resposta fica no fim de propósito."""


def f_chunk_hostil(rng, n, ext):  # noqa: ANN001
    """A truncagem silenciosa de 13/08, em forma de corpus.

    Dois documentos por `i`, e os dois põem a resposta **longe do começo**:

    - **URL gigante sem espaço**: o caso que produziu um chunk de 82 caracteres
      num email. Texto sem ponto de quebra natural derrota o chunker por cima e
      por baixo — ou corta no lugar errado, ou não corta.
    - **tabela de 900 linhas**: o bloco `never_split`. O ranqueador denso vinha
      julgando cada documento pelo *começo* de cada chunk, e como o chunk começa
      com o prefixo contextual (nome do arquivo + headings), boa parte da janela
      é cabeçalho e não conteúdo.

    Se a resposta estivesse no primeiro parágrafo, a fatia mediria zero: a
    truncagem só aparece quando o que importa está depois do corte.
    """
    docs, ps = [], []
    for i in range(n):
        cid = f"CT-CK-{i:03d}"
        valor = rng.randrange(300, 9000) * 1000
        # 600 repeticoes ~ 12 mil caracteres sem um unico espaco. A primeira
        # versao usava 220 e dava 4,5 mil -- o teste reprovou, e reprovou certo:
        # 4,5 mil cabe em poucos chunks e nao estressa nada. O numero tem de vir
        # da janela do modelo, nao do que parece grande.
        url = "https://portal.vce.example/documentos/" + "segmento-sem-espaco-" * 600 + f"{cid}"
        corrido = mkdoc(
            PASTA_CHUNK, f"Encaminhamento {cid}",
            f"Prezados,\n\nSegue o link do processo abaixo.\n\n{url}\n\n"
            f"Confirmado com o juridico: o valor homologado do contrato {cid} e "
            f"{moeda(valor)}.\n",
            ext(),
        )
        docs.append(corrido)
        ps.append(perg(
            f"q-ck-url-{i:03d}", "chunk_hostil",
            f"Qual o valor homologado do contrato {cid}?", moeda(valor),
            [corrido.caminho],
            armadilha="URL de 12 mil caracteres sem espaco antes da resposta",
            feature_alvo="chunking/truncagem",
        ))

        tabela = ["ITEM;DESCRICAO;QUANTIDADE;UNITARIO"]
        for linha in range(LINHAS_DA_TABELA):
            tabela.append(
                f"{linha:04d};{rng.choice(V.SERVICOS)};{rng.randrange(1, 400)};"
                f"{rng.randrange(100, 9000)}"
            )
        tabela.append(f"TOTAL GERAL DO ANEXO {cid};;;{valor}")
        volumoso = mkdoc(
            PASTA_CHUNK, f"Anexo de precos {cid}",
            f"ANEXO DE PRECOS {cid}\n\n" + "\n".join(tabela) + "\n",
            ext(),
        )
        docs.append(volumoso)
        ps.append(perg(
            f"q-ck-tab-{i:03d}", "chunk_hostil",
            f"Qual o total geral do anexo de precos {cid}?", str(valor),
            [volumoso.caminho],
            armadilha=f"tabela de {LINHAS_DA_TABELA} linhas; o total esta na ultima",
            feature_alvo="chunking/never_split",
        ))
    return docs, ps
