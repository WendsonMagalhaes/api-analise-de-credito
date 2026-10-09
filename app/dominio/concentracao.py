"""
Concentração de risco: ranking de clientes por % do saldo total em
aberto da carteira, com alerta configurável quando alguém ultrapassa um
percentual (evita depender demais de poucos clientes grandes).
"""
from __future__ import annotations

import pandas as pd

from app.db import config

CHAVE_ALERTA_PCT = "concentracao_risco_alerta_pct"
_PADRAO_ALERTA_PCT = 15


def calcular_ranking(carteira_df: pd.DataFrame) -> pd.DataFrame:
    if carteira_df.empty:
        return pd.DataFrame(columns=["cliente", "valor_em_aberto", "pct_da_carteira", "acima_do_limiar"])

    total = float(carteira_df["valor_em_aberto"].fillna(0).sum())
    limiar = config.get(CHAVE_ALERTA_PCT, _PADRAO_ALERTA_PCT)

    df = carteira_df[["cliente", "valor_em_aberto"]].copy()
    df["valor_em_aberto"] = df["valor_em_aberto"].fillna(0)
    df = df[df["valor_em_aberto"] > 0]
    df["pct_da_carteira"] = (df["valor_em_aberto"] / total * 100).round(2) if total else 0
    df["acima_do_limiar"] = df["pct_da_carteira"] > limiar
    # ordena pelo valor (não pelo % já arredondado em 2 casas): com o arredondamento,
    # clientes de valores parecidos empatam e a ordem — e quem entra no top 10 —
    # ficava arbitrária. kind estável + desempate por nome = resultado sempre igual.
    return df.sort_values(["valor_em_aberto", "cliente"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
