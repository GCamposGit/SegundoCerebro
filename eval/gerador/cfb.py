"""Construtor de container CFB — para testar o `.msg` sem dado real no Git.

Um `.msg` é um Compound File Binary (o mesmo container do `.doc` e do `.xls`) com
os campos MAPI em streams de nome fixo. Testar o parser exigiria um `.msg` de
verdade, e `.msg` de verdade neste projeto **é** acervo corporativo — não entra no
repositório (`docs/colaboracao.md` §2).

A saída daqui é escrita byte a byte a partir da especificação e é lida pelo
`olefile`, que é implementação independente. Isso é o oposto de um mock: se o
arquivo estiver errado, o `olefile` reclama, e o teste não passa fingindo. A lição
de 19/08/2026 no `CLAUDE.md` — "mock de utilitário do sistema não prova permissão"
— é exatamente sobre a diferença entre as duas coisas.

Escopo: só o que um `.msg` de teste precisa. Sem DIFAT extra (109 setores de FAT
cobrem 27 MB), sem transação e sem CLSID.
"""

from __future__ import annotations

import struct

ASSINATURA = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

SETOR = 512
MINI_SETOR = 64
CORTE_MINI = 4096
"""Abaixo disto o stream mora no mini-stream. É campo do cabeçalho, mas o valor
tem que ser este: escrever outro é arquivo fora da especificação."""

LIVRE = 0xFFFFFFFF
FIM_DE_CADEIA = 0xFFFFFFFE
SETOR_DE_FAT = 0xFFFFFFFD
SEM_ENTRADA = 0xFFFFFFFF

TIPO_VAZIO = 0
TIPO_STORAGE = 1
TIPO_STREAM = 2
TIPO_RAIZ = 5

ENTRADAS_POR_SETOR = SETOR // 128
ENTRADAS_DE_FAT_POR_SETOR = SETOR // 4


class _Entrada:
    def __init__(self, nome: str, tipo: int, dados: bytes | None = None) -> None:
        self.nome = nome
        self.tipo = tipo
        self.dados = dados
        self.indice = 0
        self.filho = SEM_ENTRADA
        self.direita = SEM_ENTRADA
        self.inicio = FIM_DE_CADEIA
        self.tamanho = len(dados) if dados is not None else 0

    def bytes_(self) -> bytes:
        nome = self.nome.encode("utf-16-le")[:62] + b"\x00\x00"
        return b"".join(
            (
                nome.ljust(64, b"\x00"),
                struct.pack("<H", len(nome)),
                struct.pack("<BB", self.tipo, 1),  # 1 = preto; a cor não é lida
                struct.pack("<III", SEM_ENTRADA, self.direita, self.filho),
                b"\x00" * 16,  # CLSID
                b"\x00" * 4,  # state bits
                b"\x00" * 16,  # criação e modificação
                struct.pack("<I", self.inicio),
                struct.pack("<Q", self.tamanho),
            )
        )


def _vazia() -> bytes:
    return b"".join(
        (
            b"\x00" * 64,
            struct.pack("<H", 0),
            struct.pack("<BB", TIPO_VAZIO, 0),
            struct.pack("<III", SEM_ENTRADA, SEM_ENTRADA, SEM_ENTRADA),
            b"\x00" * 16,
            b"\x00" * 4,
            b"\x00" * 16,
            struct.pack("<I", FIM_DE_CADEIA),
            struct.pack("<Q", 0),
        )
    )


def _encadear(entradas: list[_Entrada]) -> None:
    """Irmãos à direita em fila.

    A especificação pede árvore vermelho-preta; uma fila é uma árvore degenerada
    válida, e é o que o `olefile` percorre. Ordenar de verdade só importaria para
    quem faz busca binária no diretório, e nada aqui faz."""
    for anterior, seguinte in zip(entradas, entradas[1:], strict=False):
        anterior.direita = seguinte.indice


def escrever_cfb(streams: dict[str, bytes]) -> bytes:
    """Um CFB com estes streams. Chave com `/` cria storage, como no `.msg`."""
    raiz = _Entrada("Root Entry", TIPO_RAIZ)
    entradas: list[_Entrada] = [raiz]

    def registrar(entrada: _Entrada) -> _Entrada:
        entrada.indice = len(entradas)
        entradas.append(entrada)
        return entrada

    topo: list[_Entrada] = []
    por_storage: dict[str, list[_Entrada]] = {}

    for chave, dados in streams.items():
        if "/" not in chave:
            topo.append(registrar(_Entrada(chave, TIPO_STREAM, dados)))
            continue
        pai, filho = chave.split("/", 1)
        if pai not in por_storage:
            por_storage[pai] = []
            topo.append(registrar(_Entrada(pai, TIPO_STORAGE)))
        por_storage[pai].append(registrar(_Entrada(filho, TIPO_STREAM, dados)))

    _encadear(topo)
    if topo:
        raiz.filho = topo[0].indice
    for entrada in topo:
        filhos = por_storage.get(entrada.nome) if entrada.tipo == TIPO_STORAGE else None
        if filhos:
            _encadear(filhos)
            entrada.filho = filhos[0].indice

    # --- alocação de setores -------------------------------------------------
    setores: list[bytes] = []
    fat: list[int] = []

    def alocar(dados: bytes) -> int:
        if not dados:
            return FIM_DE_CADEIA
        inicio = len(setores)
        pedacos = [dados[i : i + SETOR] for i in range(0, len(dados), SETOR)]
        for n, pedaco in enumerate(pedacos):
            setores.append(pedaco.ljust(SETOR, b"\x00"))
            fat.append(FIM_DE_CADEIA if n == len(pedacos) - 1 else inicio + n + 1)
        return inicio

    grandes = [e for e in entradas if e.dados and len(e.dados) >= CORTE_MINI]
    pequenos = [e for e in entradas if e.dados and 0 < len(e.dados) < CORTE_MINI]

    for entrada in grandes:
        entrada.inicio = alocar(entrada.dados or b"")

    mini_dados = bytearray()
    mini_fat: list[int] = []
    for entrada in pequenos:
        inicio = len(mini_fat)
        n = -(-len(entrada.dados or b"") // MINI_SETOR)
        for i in range(n):
            mini_fat.append(FIM_DE_CADEIA if i == n - 1 else inicio + i + 1)
        mini_dados += (entrada.dados or b"").ljust(n * MINI_SETOR, b"\x00")
        entrada.inicio = inicio

    raiz.inicio = alocar(bytes(mini_dados))
    raiz.tamanho = len(mini_dados)

    mini_fat_bytes = b"".join(struct.pack("<I", v) for v in mini_fat)
    resto = (-len(mini_fat_bytes)) % SETOR
    mini_fat_bytes += struct.pack("<I", LIVRE) * (resto // 4)
    inicio_mini_fat = alocar(mini_fat_bytes)
    n_mini_fat = len(mini_fat_bytes) // SETOR

    diretorio = b"".join(e.bytes_() for e in entradas)
    faltam = (-len(entradas)) % ENTRADAS_POR_SETOR
    diretorio += _vazia() * faltam
    inicio_diretorio = alocar(diretorio)

    # A FAT também ocupa setor, então o número dela depende de si mesmo.
    n_fat = 1
    while -(-(len(setores) + n_fat) // ENTRADAS_DE_FAT_POR_SETOR) > n_fat:
        n_fat += 1
    primeiro_fat = len(setores)
    for _ in range(n_fat):
        fat.append(SETOR_DE_FAT)
        setores.append(b"")  # substituído abaixo, quando a FAT estiver fechada
    fat += [LIVRE] * (n_fat * ENTRADAS_DE_FAT_POR_SETOR - len(fat))
    fat_bytes = b"".join(struct.pack("<I", v) for v in fat)
    for i in range(n_fat):
        setores[primeiro_fat + i] = fat_bytes[i * SETOR : (i + 1) * SETOR].ljust(SETOR, b"\xff")

    difat = [primeiro_fat + i for i in range(n_fat)] + [LIVRE] * (109 - n_fat)

    cabecalho = b"".join(
        (
            ASSINATURA,
            b"\x00" * 16,  # CLSID
            struct.pack("<HH", 0x003E, 0x0003),
            struct.pack("<H", 0xFFFE),
            struct.pack("<HH", 9, 6),  # setor 512, mini-setor 64
            b"\x00" * 6,
            struct.pack("<I", 0),  # setores de diretório: 0 na versão 3
            struct.pack("<I", n_fat),
            struct.pack("<I", inicio_diretorio),
            struct.pack("<I", 0),  # transação
            struct.pack("<I", CORTE_MINI),
            struct.pack("<I", inicio_mini_fat if n_mini_fat else FIM_DE_CADEIA),
            struct.pack("<I", n_mini_fat),
            struct.pack("<I", FIM_DE_CADEIA),  # primeiro DIFAT
            struct.pack("<I", 0),  # setores de DIFAT
            b"".join(struct.pack("<I", v) for v in difat),
        )
    )
    assert len(cabecalho) == SETOR, len(cabecalho)
    return cabecalho + b"".join(setores)


def msg_de(
    *,
    assunto: str = "",
    de: str = "",
    email_de: str = "",
    para: str = "",
    corpo: str = "",
    corpo_html: str = "",
    anexos: tuple[str, ...] = (),
    envio: int | None = None,
) -> bytes:
    """Um `.msg` de teste, com os campos MAPI que o parser lê.

    `envio` é `FILETIME` — 100 ns desde 1601 — porque é o que está no arquivo."""
    from segundocerebro.ingest.parsers import mail

    streams: dict[str, bytes] = {}

    def unicode_(tag: str, valor: str) -> None:
        if valor:
            streams[f"{mail.PREFIXO_PROPRIEDADE}{tag}{mail.TIPO_UNICODE}"] = valor.encode("utf-16-le")

    unicode_(mail.TAG_ASSUNTO, assunto)
    unicode_(mail.TAG_REMETENTE, de)
    unicode_(mail.TAG_REMETENTE_EMAIL, email_de)
    unicode_(mail.TAG_PARA, para)
    unicode_(mail.TAG_CORPO, corpo)
    unicode_(mail.TAG_CORPO_HTML, corpo_html)

    for i, nome in enumerate(anexos):
        chave = f"{mail.PREFIXO_ANEXO}#{i:08X}/{mail.PREFIXO_PROPRIEDADE}{mail.TAG_ANEXO_NOME_LONGO}{mail.TIPO_UNICODE}"
        streams[chave] = nome.encode("utf-16-le")

    if envio is not None:
        streams[mail.STREAM_DE_PROPRIEDADES] = b"\x00" * 32 + struct.pack(
            "<HHIQ", mail.TIPO_SYSTIME, mail.ID_ENVIO, 0, envio
        )

    return escrever_cfb(streams)


def filetime(ano: int, mes: int, dia: int, hora: int = 0, minuto: int = 0) -> int:
    import datetime as dt

    quando = dt.datetime(ano, mes, dia, hora, minuto, tzinfo=dt.UTC)
    from segundocerebro.ingest.parsers.mail import EPOCA_FILETIME

    return int((quando - EPOCA_FILETIME).total_seconds()) * 10_000_000
