"""
Comparativo sazonal: permite marcar períodos (datas comemorativas, picos
de demanda) e sinalizar separadamente os atrasos de pagamento ocorridos
neles nas análises de tendência — pra não penalizar um cliente por um
atraso pontual concentrado num pico sazonal, exatamente como aconteceria
misturando esse atraso com o comportamento "normal" do resto do ano.
"""
from __future__ import annotations

import pandas as pd

from app import db


def cadastrar_periodo(nome: str, data_inicio, data_fim) -> int:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO periodos_sazonais (nome, data_inicio, data_fim) VALUES (%s, %s, %s) RETURNING id",
                (nome, data_inicio, data_fim),
            )
            novo_id = cur.fetchone()["id"]
        conn.commit()
    return novo_id


def remover_periodo(periodo_id: int) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM periodos_sazonais WHERE id = %(id)s", {"id": periodo_id})
        conn.commit()


def fetch_periodos() -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM periodos_sazonais ORDER BY data_inicio", db.get_engine()
    )


def marcar_atrasos_sazonais(df_pagamentos: pd.DataFrame) -> pd.DataFrame:
    """Adiciona a coluna booleana `atraso_em_periodo_sazonal`: True quando
    o título pago em atraso venceu dentro de algum período sazonal
    cadastrado. Não remove nem esconde o atraso — só sinaliza, pra quem
    for calcular tendência decidir se quer excluir ou tratar à parte."""
    df = df_pagamentos.copy()
    if df.empty:
        df["atraso_em_periodo_sazonal"] = pd.Series(dtype="bool")
        return df

    periodos = fetch_periodos()
    df["atraso_em_periodo_sazonal"] = False
    if periodos.empty:
        return df

    venc = pd.to_datetime(df["data_vencimento"])
    for _, p in periodos.iterrows():
        inicio, fim = pd.Timestamp(p["data_inicio"]), pd.Timestamp(p["data_fim"])
        dentro = (venc >= inicio) & (venc <= fim)
        df.loc[dentro, "atraso_em_periodo_sazonal"] = True
    return df
