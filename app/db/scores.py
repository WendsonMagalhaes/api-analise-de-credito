"""Histórico de score por cliente (score_snapshot), usado nos alertas de mudança de faixa."""
from __future__ import annotations

from datetime import date
import itertools

import pandas as pd

from app.db.conexao import bulk_upsert, conn_ou_nova, fetch_all, read_df
from app.db.conversores import num_ou_none


def salvar_score_snapshot(score_df: pd.DataFrame, data_captura: date, conn=None) -> None:
    """
    Grava um retrato do score de cada cliente na data informada, pra dar
    pra comparar depois (ver /api/alertas). Se já existir um snapshot desse
    cliente nessa data (reimportação no mesmo dia), sobrescreve com o valor
    mais recente. `conn` opcional: participa da transação de quem chamou.
    """
    if score_df.empty:
        return
    rows = list(
        zip(
            itertools.repeat(data_captura),
            score_df["cliente"].tolist(),
            [int(s) for s in score_df["score"]],
            score_df["faixa"].tolist(),
            [num_ou_none(v) for v in score_df["valor_em_aberto"]] if "valor_em_aberto" in score_df else itertools.repeat(None),
        )
    )
    with conn_ou_nova(conn) as c:
        with c.cursor() as cur:
            bulk_upsert(
                cur, "score_snapshot",
                ["data_captura", "cliente", "score", "faixa", "valor_em_aberto"], rows,
                conflito=["data_captura", "cliente"], atualizar=["score", "faixa", "valor_em_aberto"],
            )


def fetch_ultimas_duas_datas_snapshot() -> list[date]:
    """As duas datas mais recentes com score_snapshot gravado (mais nova primeiro)."""
    rows = fetch_all(
        "SELECT DISTINCT data_captura FROM score_snapshot ORDER BY data_captura DESC LIMIT 2"
    )
    return [r["data_captura"] for r in rows]


def fetch_score_snapshot_por_data(data_captura: date) -> pd.DataFrame:
    return read_df(
        "SELECT * FROM score_snapshot WHERE data_captura = %(d)s", {"d": data_captura}
    )


def fetch_historico_score_cliente(cliente: str) -> pd.DataFrame:
    """
    Evolução do score do cliente ao longo do tempo — uma captura por dia em
    que relatórios foram importados (ver salvar_score_snapshot). Dá pra ver
    se ele vem melhorando ou piorando, não só o número de hoje.
    """
    return read_df(
        """SELECT data_captura, score, faixa, valor_em_aberto
           FROM score_snapshot WHERE cliente = %(c)s
           ORDER BY data_captura""",
        {"c": cliente},
    )
