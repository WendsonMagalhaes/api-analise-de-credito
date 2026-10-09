"""Decisões de crédito registradas pelos analistas (decisoes_credito)."""
from __future__ import annotations

import pandas as pd

from app.db.conexao import get_conn, read_df


def registrar_decisao(
    cliente: str,
    tipo: str,
    valor_solicitado: float | None,
    valor_aprovado: float | None,
    prazo_dias: int | None,
    score_no_momento: int | None,
    faixa_no_momento: str | None,
    analista: str | None,
    observacao: str | None,
) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decisoes_credito
                    (cliente, tipo, valor_solicitado, valor_aprovado, prazo_dias,
                     score_no_momento, faixa_no_momento, analista, observacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    cliente,
                    tipo,
                    valor_solicitado,
                    valor_aprovado,
                    prazo_dias,
                    score_no_momento,
                    faixa_no_momento,
                    analista,
                    observacao,
                ),
            )
            novo_id = cur.fetchone()["id"]
        conn.commit()
    return novo_id


def fetch_decisoes_cliente_df(cliente: str) -> pd.DataFrame:
    return read_df(
        "SELECT * FROM decisoes_credito WHERE cliente = %(c)s ORDER BY criado_em DESC",
        {"c": cliente},
    )


def fetch_decisoes_recentes_df(limite: int = 50) -> pd.DataFrame:
    return read_df(
        "SELECT * FROM decisoes_credito ORDER BY criado_em DESC LIMIT %(l)s", {"l": limite}
    )
