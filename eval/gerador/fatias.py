"""Fatias da matriz de armadilhas (E2). Contrato: f(rng,n,ext)->(docs,perguntas).
Identificadores plantados sao unicos no corpus: gabarito perfeito por construcao."""
from .nucleo import Doc, mkdoc, perg, moeda
from . import vocabulario as V

def _contrato(rng, emp, cid, valor, ano, srv):
    data = f"{rng.randrange(1,28):02d}/{rng.randrange(1,13):02d}/{ano}"
    return (f"CONTRATO {cid}\n\nContratada: {emp}\nData de assinatura: {data}\n"
            f"Objeto: prestacao de servicos de {srv}.\n"
            f"Valor total do contrato: {moeda(valor)}.\n"
            f"Vigencia: {rng.choice([12,24,36])} meses.\nForo: comarca de {rng.choice(V.CIDADES)}.\n")

def f_nomes_ruins(rng, n, ext):
    docs, ps = [], []
    for i in range(n):
        cid, valor = f"CT-NR-{i:03d}", rng.randrange(80, 9500) * 1000
        t = _contrato(rng, rng.choice(V.EMPRESAS), cid, valor, rng.randrange(2008, 2026), rng.choice(V.SERVICOS))
        nome = f"{rng.choice(['IMG','DSC','scan'])}_{rng.randrange(1000,9999)}_{i}"
        d = mkdoc("Digitalizados antigos", nome, t, ext())
        docs.append(d)
        ps.append(perg(f"q-nr-{i:03d}", "nomes_ruins", f"Qual o valor total do contrato {cid}?",
                       moeda(valor), [d.caminho], armadilha="nome de arquivo nao informativo",
                       feature_alvo="C3.a/R6.1"))
    return docs, ps

def f_versoes(rng, n, ext):
    docs, ps = [], []
    sufixos = ["v1", "v2", "v3 final", "final_FINAL(2)"]
    for i in range(n):
        emp, pid = rng.choice(V.EMPRESAS), f"PROP-{i:03d}"
        vals = [rng.randrange(50, 5000) * 1000 for _ in sufixos]
        while vals[-1] in vals[:-1]:
            vals[-1] = rng.randrange(50, 5000) * 1000
        cams = []
        for k, suf in enumerate(sufixos):
            fim = "Versao final aprovada para envio." if k == 3 else "Rascunho - sujeito a alteracao."
            t = (f"PROPOSTA {pid} - {emp}\nRevisao {k+1} de 4.\nData: {10+k}/0{1+k}/{2020+i%6}\n"
                 f"Valor proposto: {moeda(vals[k])}.\n{fim}\n")
            d = mkdoc(f"02. Comercial/Propostas/{emp}", f"Proposta {emp} {pid} {suf}", t, ext())
            cams.append(d.caminho); docs.append(d)
        ps.append(perg(f"q-vs-{i:03d}", "versoes", f"Qual o valor da versao final da proposta {pid}?",
                       moeda(vals[-1]), [cams[-1]], armadilha="familia de versoes com valores divergentes",
                       feature_alvo="C6/R1.3", familia=cams))
    return docs, ps

def f_duplicatas(rng, n, ext):
    docs, ps = [], []
    for i in range(n):
        aid, ano = f"ATA-{i:03d}", rng.randrange(2012, 2026)
        dec = f"aprovar a contratacao da {rng.choice(V.EMPRESAS)} para {rng.choice(V.SERVICOS)}"
        t = f"ATA DE REUNIAO {aid}\nData: {rng.randrange(1,28):02d}/06/{ano}\nDeliberacao: ficou decidido {dec}.\n"
        e, cams = ext(), []
        for pasta, nome in [(f"03. Governanca/Atas/{ano}", f"Ata reuniao {aid}"),
                            (f"Backup/{ano}", f"Ata reuniao {aid}"),
                            ("Antigo/Documentos diversos", f"Copia de Ata reuniao {aid}")]:
            d = mkdoc(pasta, nome, t, e); cams.append(d.caminho); docs.append(d)
        ps.append(perg(f"q-dp-{i:03d}", "duplicatas", f"O que ficou decidido na reuniao registrada na {aid}?",
                       dec, cams, armadilha="mesmo conteudo em 3 caminhos", feature_alvo="R1.3", canonico=cams[0]))
    return docs, ps

def f_cross_lingual(rng, n, ext):
    """A unica fatia em que `idioma` e `idioma_fonte` divergem -- e o ponto dela.

    As outras dez declaram `pt` nos dois. Declarar e diferente de omitir: com
    `idioma_fonte` omitido, `harness.Pergunta.fatia` devolve `nao declarado` para
    **todas**, a fatia cross-lingual sai de tamanho zero e o relatorio sai
    parecendo aprovado -- que e o achado 3 do laudo, palavra por palavra o que o
    `eval/golden/README.md` avisou que aconteceria.
    """
    docs, ps = [], []
    for i in range(n):
        proj, emp = f"Projeto {V.PROJETOS[i % 10]}-X{i:02d}", rng.choice(V.EMPRESAS)
        if i % 2 == 0:
            orc = rng.randrange(100, 9000) * 1000
            t = (f"INTERNAL MEMO M-CL-{i:03d}\nProject: {proj}\nThe steering committee approved "
                 f"a total budget of USD {orc:,} for {proj}. Vendor: {emp}.\n")
            d = mkdoc(f"04. Projetos/{proj}", "Steering committee memo", t, ext()); docs.append(d)
            ps.append(perg(f"q-cl-{i:03d}", "cross_lingual", f"Qual o orcamento total aprovado para o {proj}?",
                           f"USD {orc:,}", [d.caminho], idioma="pt", idioma_fonte="en",
                           armadilha="pergunta PT, documento EN", feature_alvo="C4/R3.1/R6.2"))
        else:
            m = rng.randrange(4, 36)
            t = f"RELATORIO DE PLANEJAMENTO R-CL-{i:03d}\n{proj}\nPrazo de conclusao estimado: {m} meses.\nFornecedora: {emp}.\n"
            d = mkdoc(f"04. Projetos/{proj}", "Relatorio de planejamento", t, ext()); docs.append(d)
            ps.append(perg(f"q-cl-{i:03d}", "cross_lingual", f"What is the estimated completion deadline for {proj}?",
                           f"{m} meses", [d.caminho], idioma="en", idioma_fonte="pt",
                           armadilha="pergunta EN, documento PT", feature_alvo="C4/R3.1/R6.2"))
    return docs, ps

TETO_DE_SIGLAS = 26**3
"""Quantas siglas de tres letras existem, e por que o numero esta escrito aqui.

A versao entregue no pacote gerava `chr(65 + (b * m) % 26)` para `m` em
`(7, 11, 17)`. Os tres multiplicadores sao coprimos de 26, entao `b mod 26` e
**bijecao** sobre a tripla: o espaco tinha 26 elementos, nao 26**3, e o
`while True` nunca saia depois de esgotados os 26.

Medido neste repositorio em 25/08/2026, com `--seed 42 --sem-docx`:

| `--n-por-fatia` | resultado |
|---|---|
| 26 | termina, agregado `ad7030086dbed99b...` |
| 27 | **trava** (nao termina em 15 s) |
| 30 | **trava** -- e 30 e o `estatistica.N_MINIMO` que o `E5` exige |

O laudo (`docs/avaliacao-pacote-e1.md`, achado 1) poe a parede em `i = 26`; a
medicao poe em `n = 27`, porque com `n = 26` o indice vai de 0 a 25 e a 26a
chamada ainda encontra sigla livre. A conclusao do laudo e a recomendacao de
`--n-por-fatia 26` seguem certas; o numero e que era um a menos.

Aqui a tripla sao os tres digitos de `i` em base 26 -- bijecao sobre 26**3.
Nao ha colisao para `i` distintos, e portanto nao ha laco de onde sair.
"""


def _sigla(vistos, i):
    """A i-esima sigla de tres letras. Sem laco, e com teto que levanta erro.

    **O contrato e o teto explicito, e ele vale mais que o espaco maior.** Um
    gerador que laca em vez de falhar e o pior modo de falha possivel, porque a
    suite que roda com `n` pequeno fica verde e o comando do README nao termina
    -- foi exatamente o que aconteceu aqui, e e a licao da `F3.5-D` com outro
    nome: teste verde contra um caminho que a maquina nao executa.
    """
    if i >= TETO_DE_SIGLAS:
        raise ValueError(
            f"a fatia de siglas pediu a sigla de indice {i} e o espaco de tres "
            f"letras tem {TETO_DE_SIGLAS} -- acrescentar letra, nunca lacar"
        )
    s = "".join(chr(65 + (i // 26**k) % 26) for k in (2, 1, 0))
    if s in vistos:
        raise ValueError(
            f"sigla {s} repetida: `i` tem de ser unico dentro da fatia (recebido {i})"
        )
    vistos.add(s)
    return s

def f_siglas(rng, n, ext):
    docs, ps, vistos = [], [], set()
    subs = ["definida_2x", "definida_1x", "ambigua", "nunca_definida"]
    for i in range(n):
        sub, sg = subs[i % 4], _sigla(vistos, i)
        exp = (f"{rng.choice(['Plano','Programa','Comite','Indice','Termo'])} de "
               f"{rng.choice(['Gestao','Riscos','Qualidade','Auditoria','Conformidade'])} "
               f"{rng.choice(['Operacional','Corporativa','Integrada','Regulatoria'])}")
        regra = (f"aprovacao previa da area de {rng.choice(V.AREAS)} para despesas de "
                 f"{rng.choice(V.TEMAS)} acima de {moeda(rng.randrange(5,500)*1000)}")
        if sub == "ambigua":
            r2 = f"registro obrigatorio de incidentes de {rng.choice(V.TEMAS)}"
            d1 = mkdoc("05. Politicas/Juridico", f"Norma {sg} Juridico", f"O {exp} ({sg}) estabelece {regra}.\n", ext())
            d2 = mkdoc("05. Politicas/TI", f"Norma {sg} TI", f"O {exp} Setorial ({sg}) estabelece {r2}.\n", ext())
            docs += [d1, d2]
            ps.append(perg(f"q-sg-{i:03d}", "siglas", f"No contexto da area Juridico, o que estabelece o {sg}?",
                           regra, [d1.caminho], armadilha="sigla ambigua entre pastas", feature_alvo="C2",
                           subtipo=sub, doc_conflitante=d2.caminho))
        elif sub == "nunca_definida":
            d = mkdoc("06. Operacoes/Relatorios", f"Relatorio operacional {sg} {i:03d}",
                      f"Conforme diretriz do {sg}, {regra}.\n", ext())
            docs.append(d)
            ps.append(perg(f"q-sg-{i:03d}", "siglas", f"O que a diretriz do {sg} exige?", regra, [d.caminho],
                           armadilha="sigla usada mas nunca definida", feature_alvo="C2", subtipo=sub))
        else:
            nd, cams = (2 if sub == "definida_2x" else 1), []
            for k in range(nd):
                d = mkdoc(f"05. Politicas/{rng.choice(V.AREAS)}", f"Politica {sg} def{k} {i:03d}",
                          f"O {exp} ({sg}) estabelece {regra}.\n", ext())
                cams.append(d.caminho); docs.append(d)
            docs.append(mkdoc("06. Operacoes/Relatorios", f"Uso da sigla {sg} {i:03d}",
                              f"A revisao anual seguiu o {sg} sem ressalvas.\n", ext()))
            ps.append(perg(f"q-sg-{i:03d}", "siglas", f"O que estabelece o {sg}?", regra, cams,
                           armadilha=f"sigla {sub}", feature_alvo="C2", subtipo=sub))
    return docs, ps

def f_planilha_despejo(rng, n, ext, linhas=4000):
    docs, ps, alvos = [], [], []
    for c in range(3):
        rows = ["fornecedor;cnpj;municipio;valor_anual"]
        alvo_idx = set(sorted({rng.randrange(100, linhas - 100) for _ in range(40)})[: (n + 2) // 3])
        for r in range(linhas):
            if r in alvo_idx:
                nome, cid = f"{rng.choice(V.EMPRESAS)} Suprimentos {len(alvos):02d}", rng.choice(V.CIDADES)
                alvos.append((nome, cid, c))
            else:
                nome, cid = f"Fornecedor Generico {c:02d}-{r:05d}", rng.choice(V.CIDADES)
            rows.append(f"{nome};{rng.randrange(10,99)}.{rng.randrange(100,999)}.{rng.randrange(100,999)}/0001-{rng.randrange(10,99)};{cid};{rng.randrange(10,900)*1000}")
        docs.append(Doc(f"07. Compras/base_fornecedores_{c:02d}.csv", "\n".join(rows) + "\n", formato="csv"))
    for i, (nome, cid, c) in enumerate(alvos[:n]):
        ps.append(perg(f"q-pl-{i:03d}", "planilha_despejo",
                       f"Existe algum fornecedor chamado {nome}? Em qual municipio?", cid,
                       [f"07. Compras/base_fornecedores_{c:02d}.csv"],
                       armadilha="1 linha relevante em 4000", feature_alvo="C7"))
    return docs, ps

def f_multihop(rng, n, ext):
    docs, ps = [], []
    for i in range(n):
        proj = f"Projeto {V.PROJETOS[(i*3) % 10]}-M{i:02d}"
        emp, ano = rng.choice(V.EMPRESAS), rng.randrange(2012, 2026)
        cid, valor, e = f"CT-MH-{i:03d}", rng.randrange(200, 9000) * 1000, ext()
        da = mkdoc(f"04. Projetos/{proj}", "Resumo executivo",
                   f"RESUMO EXECUTIVO - {proj}\nO {proj} e regido pelo contrato {cid}, firmado com a {emp}.\n", e)
        db = mkdoc(f"01. Juridico/Contratos/{ano}", cid,
                   _contrato(rng, emp, cid, valor, ano, rng.choice(V.SERVICOS)), e)
        docs += [da, db]
        ps.append(perg(f"q-mh-{i:03d}", "multihop", f"Qual o valor do contrato que rege o {proj}?",
                       moeda(valor), [da.caminho, db.caminho], tipo="multihop", criterio="todas",
                       armadilha="resposta exige encadear 2 documentos", feature_alvo="neighbors/grafo"))
    return docs, ps

def f_temporal(rng, n, ext):
    docs, ps, anos = [], [], [2019, 2022, 2025]
    for i in range(n):
        pol, lim, e, cams = f"PL-TP-{i:03d}", rng.sample(range(10, 990), 3), ext(), []
        for k, ano in enumerate(anos):
            vig = "Esta e a versao vigente." if k == 2 else f"Substituida pela revisao de {anos[k+1]}."
            t = f"POLITICA {pol} - Revisao de {ano}\nLimite de alcada para aprovacao direta: {moeda(lim[k]*1000)}.\n{vig}\n"
            d = mkdoc(f"05. Politicas/{pol}", f"Politica de alcadas {pol} rev{ano}", t, e)
            cams.append(d.caminho); docs.append(d)
        if i % 2 == 0:
            ps.append(perg(f"q-tp-{i:03d}", "temporal", f"Qual o limite de alcada vigente segundo a politica {pol}?",
                           moeda(lim[-1]*1000), [cams[-1]], tipo="temporal",
                           armadilha="3 revisoes, so a ultima vale", feature_alvo="R6.3/C6", familia=cams))
        else:
            ps.append(perg(f"q-tp-{i:03d}", "temporal", f"Qual era o limite de alcada da politica {pol} em vigor em 2019?",
                           moeda(lim[0]*1000), [cams[0]], tipo="temporal",
                           armadilha="pergunta pela versao antiga", feature_alvo="R6.3/C6", familia=cams))
    return docs, ps

def f_distratores(rng, n, ext):
    docs, ps = [], []
    for i in range(n):
        aid, tema = f"AUD-{i:03d}", rng.choice(V.TEMAS)
        achado = f"divergencia de {moeda(rng.randrange(10,900)*1000)} na conciliacao de {tema}"
        e, pasta = ext(), f"08. Auditoria/AUD-{i:03d}"
        alvo = mkdoc(pasta, f"Achados da auditoria {aid}",
                     f"AUDITORIA {aid} - ACHADOS\nA auditoria {aid} identificou {achado}.\n", e)
        docs.append(alvo); distr = []
        for sec in ["Plano de trabalho", "Definicao de escopo", "Cronograma"]:
            d = mkdoc(pasta, f"{sec} {aid}",
                      f"AUDITORIA {aid} - {sec.upper()}\nPlanejamento da auditoria {aid} sobre {tema}. Nenhum achado e reportado aqui.\n", e)
            distr.append(d.caminho); docs.append(d)
        ps.append(perg(f"q-dt-{i:03d}", "distratores", f"Qual divergencia a auditoria {aid} identificou?",
                       achado, [alvo.caminho], tipo="semantica",
                       armadilha="3 hard negatives na mesma pasta", feature_alvo="R6.2 rerank",
                       docs_distratores=distr))
    return docs, ps

def f_estrutura_pastas(rng, n, ext):
    docs, ps = [], []
    for i in range(n // 2):
        e = ext()
        for cond, j in (("taxonomia", 2*i), ("plana", 2*i+1)):
            uid, cid = f"UN-{j:03d}", rng.choice(V.CIDADES)
            data = f"{rng.randrange(1,28):02d}/{rng.randrange(1,13):02d}/{rng.randrange(2005,2026)}"
            t = f"RELATORIO DE INAUGURACAO\nUnidade {uid} - {cid}\nData de inauguracao: {data}.\n"
            d = (mkdoc(f"06. Operacoes/Unidades/{cid}/Inauguracao", f"Relatorio inauguracao unidade {uid}", t, e)
                 if cond == "taxonomia" else mkdoc("Diversos", f"doc_{j:04d}", t, e))
            docs.append(d)
            ps.append(perg(f"q-ep-{j:03d}", "estrutura_pastas", f"Quando foi inaugurada a unidade {uid}?",
                           data, [d.caminho], armadilha=f"condicao {cond}",
                           feature_alvo="R2.1 contexto de pasta", condicao=cond, par_id=i))
    return docs, ps

def f_venenosos(rng, n, ext):
    docs = []
    for i in range(3):
        docs.append(Doc(f"Quarentena teste/relatorio_truncado_{i}.pdf", "", formato="pdf_veneno"))
        docs.append(Doc(f"Quarentena teste/planilha_antiga_{i}.docx", "", formato="zip_veneno"))
        docs.append(Doc(f"Quarentena teste/vazio_{i}.txt", "", formato="vazio"))
    return docs, []  # sem perguntas: mede robustez do indexador (R1.4)

FATIAS = [("nomes_ruins", f_nomes_ruins), ("versoes", f_versoes), ("duplicatas", f_duplicatas),
          ("cross_lingual", f_cross_lingual), ("siglas", f_siglas),
          ("planilha_despejo", f_planilha_despejo), ("multihop", f_multihop),
          ("temporal", f_temporal), ("distratores", f_distratores),
          ("estrutura_pastas", f_estrutura_pastas), ("venenosos", f_venenosos)]
