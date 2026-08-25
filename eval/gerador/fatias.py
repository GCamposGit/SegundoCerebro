"""Fatias da matriz de armadilhas (E2). Contrato: f(rng,n,ext)->(docs,perguntas).
Identificadores plantados sao unicos no corpus: gabarito perfeito por construcao."""
from .nucleo import Doc, mkdoc, perg, moeda
from .formatos import f_formatos
from .ranking import (
    f_chunk_hostil, f_familia_sem_numero, f_glossario, f_grafias, f_idioma_indeciso,
)
from .hostil import f_pasta_hostil
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
                       feature_alvo="nomes/C3.a/R6.1"))
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
                       feature_alvo="familias/C6/R1.3", familia=cams))
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
                       dec, cams, armadilha="mesmo conteudo em 3 caminhos", feature_alvo="hybrid/R1.3", canonico=cams[0]))
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
                           armadilha="pergunta PT, documento EN", feature_alvo="hybrid/C4/R3.1/R6.2"))
        else:
            m = rng.randrange(4, 36)
            t = f"RELATORIO DE PLANEJAMENTO R-CL-{i:03d}\n{proj}\nPrazo de conclusao estimado: {m} meses.\nFornecedora: {emp}.\n"
            d = mkdoc(f"04. Projetos/{proj}", "Relatorio de planejamento", t, ext()); docs.append(d)
            ps.append(perg(f"q-cl-{i:03d}", "cross_lingual", f"What is the estimated completion deadline for {proj}?",
                           f"{m} meses", [d.caminho], idioma="en", idioma_fonte="pt",
                           armadilha="pergunta EN, documento PT", feature_alvo="hybrid/C4/R3.1/R6.2"))
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
                           regra, [d1.caminho], armadilha="sigla ambigua entre pastas", feature_alvo="glossario/C2",
                           subtipo=sub, doc_conflitante=d2.caminho))
        elif sub == "nunca_definida":
            d = mkdoc("06. Operacoes/Relatorios", f"Relatorio operacional {sg} {i:03d}",
                      f"Conforme diretriz do {sg}, {regra}.\n", ext())
            docs.append(d)
            ps.append(perg(f"q-sg-{i:03d}", "siglas", f"O que a diretriz do {sg} exige?", regra, [d.caminho],
                           armadilha="sigla usada mas nunca definida", feature_alvo="glossario/C2", subtipo=sub))
        else:
            nd, cams = (2 if sub == "definida_2x" else 1), []
            for k in range(nd):
                d = mkdoc(f"05. Politicas/{rng.choice(V.AREAS)}", f"Politica {sg} def{k} {i:03d}",
                          f"O {exp} ({sg}) estabelece {regra}.\n", ext())
                cams.append(d.caminho); docs.append(d)
            docs.append(mkdoc("06. Operacoes/Relatorios", f"Uso da sigla {sg} {i:03d}",
                              f"A revisao anual seguiu o {sg} sem ressalvas.\n", ext()))
            ps.append(perg(f"q-sg-{i:03d}", "siglas", f"O que estabelece o {sg}?", regra, cams,
                           armadilha=f"sigla {sub}", feature_alvo="glossario/C2", subtipo=sub))
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
                       armadilha="1 linha relevante em 4000", feature_alvo="hybrid/C7"))
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
                       armadilha="resposta exige encadear 2 documentos", feature_alvo="grafo/neighbors"))
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
                           armadilha="3 revisoes, so a ultima vale", feature_alvo="familias/R6.3/C6", familia=cams))
        else:
            ps.append(perg(f"q-tp-{i:03d}", "temporal", f"Qual era o limite de alcada da politica {pol} em vigor em 2019?",
                           moeda(lim[0]*1000), [cams[0]], tipo="temporal",
                           armadilha="pergunta pela versao antiga", feature_alvo="familias/R6.3/C6", familia=cams))
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
                       armadilha="3 hard negatives na mesma pasta", feature_alvo="rerank/R6.2",
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
                           feature_alvo="nomes/R2.1", condicao=cond, par_id=i))
    return docs, ps

CRUZA_IDIOMA = 3
"""Uma em cada tres perguntas de reuniao e de email cruza idioma.

**A intersecao, e nao a soma** -- condicao 3 do laudo. No dourado real **3 das 11
perguntas de reuniao sao cross-lingual** (`docs/colaboracao.md` secao 6), e uma
fatia sintetica que somasse os dois eixos -- reuniao monolingue de um lado,
cross-lingual de escritorio do outro -- nao mediria o caso que existe no acervo.
A `F4-P` decide sobre reuniao **e** sobre cross-lingual, e o teto de oraculo dela
nao desconta a intersecao.
"""


def _vtt(rng, falas):
    """WebVTT com marca de tempo. `eval.fonte` classifica por extensao."""
    blocos = ["WEBVTT", ""]
    for k, fala in enumerate(falas):
        ini, fim = 12 * k, 12 * k + 11
        blocos.append(f"{ini // 60:02d}:{ini % 60:02d}.000 --> {fim // 60:02d}:{fim % 60:02d}.000")
        blocos.append(fala)
        blocos.append("")
    return "\n".join(blocos)


def f_reuniao(rng, n, ext):
    """Transcricao de reuniao: o identificador esta na FALA, nunca no nome.

    A armadilha e contra o ranqueador de nome, que e o sinal que a `C3.a` mostrou
    ser 14x mais sensivel no grupo de reuniao. O arquivo se chama
    `Gravacao_2025-03-14_0930.vtt` -- data e hora, como gravador de reuniao nomeia
    -- e a resposta so existe no texto falado, com hesitacao e repeticao.
    """
    docs, ps = [], []
    for i in range(n):
        proj = f"Projeto {V.PROJETOS[i % 10]}-R{i:02d}"
        emp, valor = rng.choice(V.EMPRESAS), rng.randrange(120, 8000) * 1000
        ano, mes, dia = rng.randrange(2021, 2026), rng.randrange(1, 13), rng.randrange(1, 28)
        cruzado = i % CRUZA_IDIOMA == 0
        if cruzado:
            falas = [
                "So, quick recap before we close.",
                f"The board signed off on {moeda(valor)} for {proj}, with {emp} as the vendor.",
                "Right, and that number is final for this cycle.",
            ]
            idioma, idioma_fonte = "pt", "en"
            pergunta = f"Quanto o comite aprovou para o {proj}?"
        else:
            falas = [
                "Entao... deixa eu recapitular antes de encerrar.",
                f"O comite aprovou, aprovou sim, {moeda(valor)} para o {proj}, com a {emp}.",
                "Isso, e esse valor esta fechado para o ciclo.",
            ]
            idioma, idioma_fonte = "pt", "pt"
            pergunta = f"Quanto o comite aprovou para o {proj}?"
        nome = f"Gravacao_{ano}-{mes:02d}-{dia:02d}_{rng.randrange(8, 18):02d}{rng.choice(['00','30'])}"
        d = mkdoc(f"09. Meetings/{ano}", nome, _vtt(rng, falas), "vtt")
        docs.append(d)
        ps.append(perg(f"q-rn-{i:03d}", "reuniao", pergunta, moeda(valor), [d.caminho],
                       idioma=idioma, idioma_fonte=idioma_fonte,
                       armadilha="identificador so na fala; nome do arquivo e data e hora",
                       feature_alvo="nomes/F4-P/C3.a", cruza_idioma=cruzado))
    return docs, ps


def f_email(rng, n, ext):
    """Email MIME: o assunto nao responde, o corpo responde.

    `RES: RES: ENC:` e o assunto generico que o acervo real tem aos montes -- e o
    caso em que o ranqueador de nome nao tem sinal nenhum. O `.eml` e MIME de
    verdade, montado pela `email` da biblioteca padrao, que e o que
    `ingest/parsers/mail.py` le desde 21/08.
    """
    from email.message import EmailMessage

    docs, ps = [], []
    for i in range(n):
        cid, prazo = f"CT-EM-{i:03d}", rng.randrange(5, 90)
        emp, area = rng.choice(V.EMPRESAS), rng.choice(V.AREAS)
        ano, mes, dia = rng.randrange(2021, 2026), rng.randrange(1, 13), rng.randrange(1, 28)
        cruzado = i % CRUZA_IDIOMA == 0
        if cruzado:
            assunto = "RE: FW: RE: contract"
            corpo = (f"Hi all,\n\nLegal confirmed the notice period for contract {cid} "
                     f"with {emp}: {prazo} days.\n\nBest regards,\n{area}\n")
            idioma, idioma_fonte = "pt", "en"
            pergunta = f"Qual o prazo de aviso previo do contrato {cid}?"
        else:
            assunto = "RES: RES: ENC: contrato"
            corpo = (f"Prezados,\n\nO juridico confirmou o prazo de aviso previo do contrato "
                     f"{cid} com a {emp}: {prazo} dias.\n\nAtenciosamente,\n{area}\n")
            idioma, idioma_fonte = "pt", "pt"
            pergunta = f"Qual o prazo de aviso previo do contrato {cid}?"
        msg = EmailMessage()
        msg["Subject"] = assunto
        msg["From"] = f"{area.lower()}@vce.example"
        msg["To"] = "arquivo@vce.example"
        # Data explicita: sem ela a `email` nao carimba nada, mas declarar mantem
        # o `.eml` parecido com o real sem introduzir relogio no gerador.
        msg["Date"] = f"{dia:02d} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][mes-1]} {ano} 09:00:00 -0300"
        msg.set_content(corpo)
        nome = f"{assunto.replace(':', '').replace(' ', '_')}_{i:03d}"
        d = mkdoc("10. Caixa de entrada", nome, msg.as_string(), "eml")
        docs.append(d)
        ps.append(perg(f"q-em-{i:03d}", "email", pergunta, f"{prazo} dias", [d.caminho],
                       idioma=idioma, idioma_fonte=idioma_fonte,
                       armadilha="assunto generico (RES: RES: ENC:); resposta so no corpo",
                       feature_alvo="F4-P/parser de email", cruza_idioma=cruzado))
    return docs, ps


FATIAS = [("nomes_ruins", f_nomes_ruins), ("versoes", f_versoes), ("duplicatas", f_duplicatas),
          ("cross_lingual", f_cross_lingual), ("siglas", f_siglas),
          ("planilha_despejo", f_planilha_despejo), ("multihop", f_multihop),
          ("temporal", f_temporal), ("distratores", f_distratores),
          ("estrutura_pastas", f_estrutura_pastas),
          # Fatias de 25/08/2026 (E1.c, condicao 3). Entram no FIM da lista de
          # proposito: o RNG e por fatia (`random.Random(f"{seed}:{nome}")`), entao
          # acrescentar fatia nao muda nenhuma das existentes -- e o detalhe de
          # projeto do pacote que o laudo elogiou, e a ordem aqui nao o afeta.
          ("reuniao", f_reuniao), ("email", f_email),
          # A pasta hostil substitui `venenosos` (E1.e, 25/08/2026). Ela nao e
          # uma lista de armadilhas escrita a mao: a cobertura sai do enum
          # `ingest.document.ParseStatus`, e o teste confere contra ele. Absorve
          # a `F6-E` do ROADMAP -- o gerador E o montador de pastas.
          # Cobertura de parser, garantida e nao sorteada (E1.d): a distribuicao
          # do censo serve ao realismo, e realismo nao garante cobertura --
          # `.pptm` sao 0,1% do acervo e arredondam para zero em metade das seeds.
          # Fatias de ranking de 25/08/2026 (E1.f). Cada uma existe porque uma
          # classe de defeito DOCUMENTADA neste repositorio nao tinha nada que a
          # medisse -- nao sao hipoteses, sao episodios com data e post-mortem.
          ("grafias", f_grafias), ("glossario", f_glossario),
          ("familia_sem_numero", f_familia_sem_numero),
          ("idioma_indeciso", f_idioma_indeciso),
          ("chunk_hostil", f_chunk_hostil),
          ("formatos", f_formatos),
          ("pasta_hostil", f_pasta_hostil)]
