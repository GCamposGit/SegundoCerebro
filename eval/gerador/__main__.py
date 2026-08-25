"""CLI: python -m eval.gerador --seed 42 --n-por-fatia 30 --out corpus_sintetico/
Mesma seed+n => mesmo corpus (hash logico identico no manifesto)."""
import argparse, json, random
from pathlib import Path
from .nucleo import detectar_caps, picker, escrever, manifesto
from .fatias import FATIAS

def gerar(seed, n, out, sem_docx=False):
    """`sem_docx=True` desliga **todos** os formatos binarios, nao so o docx.

    O nome vem do pacote, quando `docx` era o unico binario que o gerador sabia
    escrever. Desde o `E1.c` sao quatro (pdf, xlsx, pptx, docx) e a flag continua
    querendo dizer a mesma coisa -- "corpus so de texto, rapido, para o CI". O
    alias `--so-texto` e o nome certo; `--sem-docx` fica porque o comando de
    reproducao do laudo o usa.

    Isto **muda o selo**, e e para mudar: `caps` e dimensao do selo desde o
    `E1.a`, entao um corpus so-texto nunca se confunde com o completo.
    """
    out = Path(out)
    caps = detectar_caps()
    if sem_docx:
        caps = dict.fromkeys(caps, False)
    docs, pergs, stats, vistos = [], [], {}, set()
    for nome, fn in FATIAS:
        rng = random.Random(f"{seed}:{nome}")  # rng por fatia: fatia nova nao muda as demais
        d, p = fn(rng, n, picker(caps))
        for dd in d:
            if dd.caminho in vistos:
                raise RuntimeError(f"colisao de caminho: {dd.caminho}")
            vistos.add(dd.caminho)
        docs += d; pergs += p
        stats[nome] = {"docs": len(d), "perguntas": len(p)}
    for d in docs:
        escrever(d, out / "corpus")
    with open(out / "perguntas.sintetico.jsonl", "w", encoding="utf-8") as f:
        for p in pergs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    man = manifesto(docs, seed, n, stats, caps)
    (out / "manifesto.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return man

def main():
    ap = argparse.ArgumentParser(prog="eval.gerador")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n-por-fatia", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--so-texto", "--sem-docx", dest="sem_docx", action="store_true",
                    help="corpus so de texto (rapido, para o CI). `--sem-docx` e o "
                         "nome antigo, mantido porque o laudo o usa")
    a = ap.parse_args()
    m = gerar(a.seed, a.n_por_fatia, Path(a.out), sem_docx=a.sem_docx)
    td = sum(s["docs"] for s in m["stats"].values())
    tp = sum(s["perguntas"] for s in m["stats"].values())
    print(f"corpus: {td} docs | {tp} perguntas | agregado {m['agregado'][:16]}...")

if __name__ == "__main__":
    main()
