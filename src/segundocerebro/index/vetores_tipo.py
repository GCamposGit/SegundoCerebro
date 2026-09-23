"""Rewrite Lance vector columns as FixedSizeList so dense search can run.

FND-01b copied rows with ``Table.from_pylist``, which infers a variable-length
``list<float64>``. Lance then refuses the column as a vector. This module
rewrites the table without re-parsing documents or touching SQLite.
"""

from __future__ import annotations

import argparse
import gc
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

from ..config import BASE_UNICA, ErroDeConfig
from ..config import carregar as carregar_config
from ..logger import get_logger
from .backup_io import recusar_indice_ausente, trava_de_backup
from .backup_manifesto import BackupRecusado

log = get_logger("index.vetores_tipo")

COLUNA_VETOR = "vetor"
TABELA_VETORES = "vetores"
TABELA_LEGADO = "chunks"


class TipoVetorInvalido(RuntimeError):
    """The Lance column cannot be queried as a vector; original files stay put."""

    def __init__(self, mensagem: str, codigo: str = "tipo_vetor", acao: str = "") -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.acao = acao


def tipo_vetor(dim: int):  # noqa: ANN201
    import pyarrow as pa

    if dim < 1:
        raise TipoVetorInvalido(f"dimensão inválida para vetor: {dim}", "dim_ilegivel")
    return pa.list_(pa.float32(), dim)


def e_vetor_fixo(tipo, dim: int | None = None) -> bool:  # noqa: ANN001
    import pyarrow as pa

    tamanho = getattr(tipo, "list_size", None)
    if not tamanho or int(tamanho) < 1:
        return False
    if dim is not None and int(tamanho) != int(dim):
        return False
    valor = getattr(tipo, "value_type", None)
    return valor is not None and pa.types.is_float32(valor)


def recusar_coluna_nao_vetor(tabela, dim: int | None = None) -> None:  # noqa: ANN001
    """Raise before Lance's English error; no-op on tables without a schema."""
    schema = getattr(tabela, "schema", None)
    if schema is None:
        return
    try:
        campo = schema.field(COLUNA_VETOR)
    except Exception:  # noqa: BLE001 — fakes and pre-vector schemas have no field
        return
    if e_vetor_fixo(campo.type, dim):
        return
    raise TipoVetorInvalido(
        f"A coluna de vetores não é um vetor de tamanho fixo ({campo.type}).",
        "tipo_vetor",
        "Regrave a tabela com `python -m segundocerebro.index.vetores_tipo` "
        "— não é preciso reindexar os documentos.",
    )


def inferir_dim(coluna) -> int:  # noqa: ANN001
    tamanho = getattr(coluna.type, "list_size", None)
    if tamanho and int(tamanho) > 0:
        return int(tamanho)
    for i in range(len(coluna)):
        valor = coluna.slice(i, 1).to_pylist()[0]
        if valor is not None:
            dim = len(valor)
            if dim < 1:
                break
            return dim
    raise TipoVetorInvalido(
        "Não foi possível inferir a dimensão da coluna de vetores.",
        "dim_ilegivel",
        "Passe --dim com a dimensão do modelo (1024 para e5-large).",
    )


def coluna_fixa(coluna, dim: int):  # noqa: ANN001, ANN201
    """Cast a list column to FixedSizeList[dim] of float32."""
    import pyarrow as pa
    import pyarrow.compute as pc

    combinada = coluna.combine_chunks() if hasattr(coluna, "combine_chunks") else coluna
    n = len(combinada)
    try:
        plano = combinada.flatten()
    except Exception:  # noqa: BLE001 — some list encodings expose values another way
        plano = None
    if plano is not None and n > 0 and len(plano) == n * dim:
        return pa.FixedSizeListArray.from_arrays(pc.cast(plano, pa.float32()), dim)
    return _coluna_fixa_via_numpy(combinada, dim)


def _coluna_fixa_via_numpy(coluna, dim: int):  # noqa: ANN001, ANN202
    import numpy as np
    import pyarrow as pa

    matriz = np.asarray(coluna.to_pylist(), dtype=np.float32)
    if matriz.ndim != 2 or matriz.shape[1] != dim:
        raise TipoVetorInvalido(
            f"Os vetores não têm dimensão {dim} (forma {getattr(matriz, 'shape', None)}).",
            "dim_divergente",
            "Confira o modelo com que o índice foi construído.",
        )
    return pa.FixedSizeListArray.from_arrays(
        pa.array(matriz.reshape(-1), type=pa.float32()), dim
    )


def tabela_com_vetor_fixo(arrow, dim: int, ocorrencias: Mapping[str, str] | None = None):  # noqa: ANN001, ANN201
    import pyarrow as pa

    nomes = list(arrow.column_names)
    vetor = coluna_fixa(arrow[COLUNA_VETOR], dim)
    arrays = []
    fields = []
    for nome in nomes:
        if nome == COLUNA_VETOR:
            arrays.append(vetor)
            fields.append(pa.field(COLUNA_VETOR, tipo_vetor(dim)))
        elif nome == "ocorrencia_id" and ocorrencias is not None:
            ids = _ocorrencias_da_tabela(arrow, ocorrencias)
            arrays.append(pa.array(ids, type=pa.string()))
            fields.append(pa.field("ocorrencia_id", pa.string()))
        else:
            arrays.append(arrow[nome])
            fields.append(arrow.schema.field(nome))
    if ocorrencias is not None and "ocorrencia_id" not in nomes:
        ids = _ocorrencias_da_tabela(arrow, ocorrencias)
        arrays.append(pa.array(ids, type=pa.string()))
        fields.append(pa.field("ocorrencia_id", pa.string()))
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def _ocorrencias_da_tabela(arrow, ocorrencias: Mapping[str, str]) -> list[str]:  # noqa: ANN001
    paths = arrow["path"].to_pylist()
    atuais = (
        arrow["ocorrencia_id"].to_pylist()
        if "ocorrencia_id" in arrow.column_names
        else [""] * len(paths)
    )
    return [
        ocorrencias.get(str(path or ""), str(oid or ""))
        for path, oid in zip(paths, atuais, strict=True)
    ]


def nomes_lance(db) -> list[str]:  # noqa: ANN001
    try:
        resposta = db.list_tables()
        if hasattr(resposta, "tables"):
            return list(resposta.tables)
        return list(resposta)
    except Exception:  # noqa: BLE001 — compatibility with older LanceDB
        try:
            return list(db.table_names())
        except Exception:  # noqa: BLE001 — compatibility fallback for old LanceDB
            return []


def abrir_tabela(db):  # noqa: ANN001, ANN201
    nomes = nomes_lance(db)
    for nome in (TABELA_VETORES, TABELA_LEGADO):
        if nome in nomes:
            return db.open_table(nome)
    return None


def regravar_pasta(
    pasta: Path,
    *,
    dim: int | None = None,
    ocorrencias: Mapping[str, str] | None = None,
) -> dict[str, int | bool]:
    """Rewrite ``pasta`` (a ``vetores.lance`` directory) to FixedSizeList float32."""
    arrow = _ler_arrow(pasta)
    if arrow is None or arrow.num_rows == 0:
        return {"linhas": 0, "alterado": False, "dim": int(dim or 0)}
    dim_efetiva = int(dim) if dim is not None else inferir_dim(arrow[COLUNA_VETOR])
    ja_certo = ocorrencias is None and e_vetor_fixo(
        arrow.schema.field(COLUNA_VETOR).type, dim_efetiva
    )
    if ja_certo:
        return {"linhas": int(arrow.num_rows), "alterado": False, "dim": dim_efetiva}
    novo = tabela_com_vetor_fixo(arrow, dim_efetiva, ocorrencias)
    linhas = _publicar_arrow(pasta, novo)
    return {"linhas": linhas, "alterado": True, "dim": dim_efetiva}


def _ler_arrow(pasta: Path):  # noqa: ANN202
    import lancedb

    from .lancedb_recursos import fechar_recursos

    db = lancedb.connect(str(pasta))
    tabela = None
    try:
        tabela = abrir_tabela(db)
        if tabela is None:
            return None
        return tabela.to_arrow()
    finally:
        fechar_recursos(tabela, db)


def _publicar_arrow(pasta: Path, arrow) -> int:  # noqa: ANN001
    import lancedb

    from .lancedb_recursos import fechar_recursos

    novo = pasta.with_name(f"{pasta.name}.novo")
    if novo.exists():
        shutil.rmtree(novo)
    db = lancedb.connect(str(novo))
    tabela = None
    try:
        tabela = db.create_table(TABELA_VETORES, data=arrow)
        n = int(tabela.count_rows())
    finally:
        fechar_recursos(tabela, db)
    gc.collect()
    shutil.rmtree(pasta)
    novo.rename(pasta)
    return n


def reparar(indice: Path, *, dim: int | None = None) -> dict[str, int | bool]:
    """Fix the live index's vector table under the exclusive lock. SQLite stays."""
    indice = indice.resolve()
    recusar_indice_ausente(indice)
    lance = indice / "vetores.lance"
    if not lance.is_dir():
        raise TipoVetorInvalido(
            "Este índice não tem tabela de vetores.",
            "vetores_ausentes",
            "Indexe a base antes de corrigir o tipo da coluna.",
        )
    with trava_de_backup(indice):
        relato = regravar_pasta(lance, dim=dim)
    log.info(
        "vetores %s: %d linha(s), dim=%d",
        "regravados" if relato["alterado"] else "já no tipo certo",
        relato["linhas"],
        relato["dim"],
    )
    return relato


def _indice_da_base(base_id: str, config: Path | None) -> Path:
    conf = carregar_config(config, validar=True) if config is not None else carregar_config()
    base = next((b for b in conf.bases if b.id == base_id), None)
    if base is None:
        raise ErroDeConfig(
            f"A base '{base_id}' não foi encontrada. Disponíveis: {', '.join(conf.ids)}."
        )
    return base.indice


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regrava a coluna Lance para vetor de tamanho fixo, sem reindexar."
    )
    parser.add_argument("--base", default=BASE_UNICA, help="Base cujo índice será corrigido.")
    parser.add_argument("--config", type=Path, help="config.toml da base.")
    parser.add_argument("--indice", type=Path, help="Diretório do índice; sobrepõe a base.")
    parser.add_argument("--dim", type=int, help="Dimensão; ausente: lê da primeira linha.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        origem = args.indice if args.indice is not None else _indice_da_base(args.base, args.config)
        relato = reparar(origem, dim=args.dim)
    except (TipoVetorInvalido, ErroDeConfig, BackupRecusado) as exc:
        print(str(exc), file=sys.stderr)  # noqa: T201 — saída da CLI
        acao = getattr(exc, "acao", "")
        if acao:
            print(acao, file=sys.stderr)  # noqa: T201 — saída da CLI
        return 2
    estado = "regravada" if relato["alterado"] else "já no tipo certo"
    print(f"coluna {estado}: {relato['linhas']} vetores de {relato['dim']} dimensões")  # noqa: T201 — saída da CLI
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
