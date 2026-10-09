"""Limite de crédito cadastrado no ERP (limite_atual_cliente)."""
from __future__ import annotations

import pandas as pd

from app.db.conexao import bulk_upsert, get_conn, read_df
from app.db.conversores import num_ou_none


def upsert_limite_atual(df: pd.DataFrame) -> dict:
    """Cada upload do relatório de limite substitui o valor por cliente —
    é sempre a foto mais recente, não um histórico."""
    if df.empty:
        return {"atualizados": 0}

    rows_brutas = list(zip(df["cliente"].tolist(), [num_ou_none(v) for v in df["limite_atual"]]))

    # Rede de segurança: mesmo que o parser já deduplique, um INSERT em
    # lote com ON CONFLICT não aceita o mesmo cliente duas vezes no mesmo
    # comando (CardinalityViolation). Mantém a última ocorrência de cada
    # cliente na lista (dict preserva a ordem de inserção/atualização).
    rows_dedup: dict[str, tuple] = {}
    for cliente, limite in rows_brutas:
        rows_dedup[cliente] = (cliente, limite)
    rows = list(rows_dedup.values())
    duplicados_ignorados = len(rows_brutas) - len(rows)

    with get_conn() as conn:
        with conn.cursor() as cur:
            bulk_upsert(
                cur, "limite_atual_cliente", ["cliente", "limite_atual"], rows,
                conflito=["cliente"], atualizar=["limite_atual"], extra_set="atualizado_em = NOW()",
            )
        conn.commit()
    return {"atualizados": len(rows), "duplicados_ignorados": duplicados_ignorados}


def fetch_limite_atual_df() -> pd.DataFrame:
    return read_df("SELECT cliente, limite_atual FROM limite_atual_cliente")
