# Corpus sintético de colaboração

Empresa fictícia **Várzea Clara Energia (VCE)**. Nenhum arquivo daqui veio do
acervo corporativo nem do acervo privado do desktop. Regenerar:

```bash
py -m eval.sintetico.gerar
```

O que ele prova, e o que ele **não** prova, está em
[`docs/colaboracao.md`](../../docs/colaboracao.md) §5.

Dois índices do mesmo modelo (GPU × CPU, ou desktop × notebook):

```bash
py -m eval.sintetico.comparar --a index-sintetico-gpu --b index-sintetico-cpu
```

Perguntas: [`eval/golden/perguntas.example.jsonl`](../golden/perguntas.example.jsonl).
Como escrever as suas: [`eval/golden/README.md`](../golden/README.md).
