"""
Índice de velocidade de pagamento = dias_para_pagamento / prazo_do_titulo,
onde dias_para_pagamento é contado desde a EMISSÃO do título (mesma
referência do prazo, pra o índice ser comparável entre títulos de 8, 14
ou 21 dias): 1.0 = pagou exatamente no prazo dele; < 1 = adiantado;
> 1 = atrasado, na proporção do próprio prazo (não em dias absolutos).

Mantém histórico por cliente (média móvel dos últimos N títulos pagos,
N configurável) — nunca sobrescreve capturas de datas anteriores.
"""
from __future__ import annotations

import itertools
from datetime import date

import pandas as pd
from app.db import config
from app import db

CHAVE_JANELA = "velocidade_media_movel_janela_titulos"
_PADRAO_JANELA = 10


def calcular_indice_por_titulo(df_pagamentos: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona `indice_velocidade` por título pago. Títulos sem
    prazo_do_titulo conhecido (relatório antigo sem as duas datas) ficam
    de fora — não dá pra normalizar sem o divisor.
    """
    df = df_pagamentos.copy()
    if df.empty:
        df["indice_velocidade"] = pd.Series(dtype="float64")
        return df

    dias_para_pagamento = (
        pd.to_datetime(df["data_pagamento"]) - pd.to_datetime(df["data_emissao"])
    ).dt.days
    prazo = df["prazo_do_titulo"]
    indice = dias_para_pagamento / prazo
    indice[(prazo.isna()) | (prazo == 0)] = None
    df["indice_velocidade"] = indice
    return df


def media_movel_por_cliente(df_com_indice: pd.DataFrame, janela: int | None = None) -> pd.DataFrame:
    """Média móvel pegando os N títulos pagos mais recentes de cada
    cliente (ordenado por data_pagamento) — reflete o comportamento
    atual do cliente, não a média de toda a vida dele.

    Vetorizado (groupby.tail em vez de um loop por cliente). A ordenação é
    estável e desempata pelo id do pagamento: vários pagamentos no mesmo dia
    são comuns, e sem desempate a escolha de QUAIS entram na janela de N
    podia mudar de uma execução pra outra."""
    janela = janela or config.get(CHAVE_JANELA, _PADRAO_JANELA)
    vazio = pd.DataFrame(columns=["cliente", "indice_medio_movel", "qtd_titulos_considerados"])
    if df_com_indice.empty:
        return vazio

    df = df_com_indice.dropna(subset=["indice_velocidade"])
    if df.empty:
        return vazio

    ordem = ["data_pagamento"] + (["id"] if "id" in df.columns else [])
    df = df.sort_values(ordem, kind="mergesort")
    agregado = df.groupby("cliente").tail(janela).groupby("cliente")["indice_velocidade"].agg(["mean", "size"])
    return pd.DataFrame(
        {
            "cliente": agregado.index,
            "indice_medio_movel": [round(float(m), 3) for m in agregado["mean"]],
            "qtd_titulos_considerados": agregado["size"].astype(int).values,
        }
    )


def salvar_snapshot(df_medias: pd.DataFrame, data_captura: date, conn=None) -> None:
    """Histórico append-only: upsert só quando é a MESMA data_captura
    (reimportação no mesmo dia); datas anteriores nunca são tocadas.
    `conn` opcional: participa da transação de quem chamou."""
    if df_medias.empty:
        return
    rows = list(
        zip(
            df_medias["cliente"].tolist(),
            itertools.repeat(data_captura),
            df_medias["indice_medio_movel"].tolist(),
            [int(q) for q in df_medias["qtd_titulos_considerados"]],
        )
    )
    with db.conn_ou_nova(conn) as c:
        with c.cursor() as cur:
            db.bulk_upsert(
                cur,
                "velocidade_pagamento_snapshot",
                ["cliente", "data_captura", "indice_medio_movel", "qtd_titulos_considerados"],
                rows,
                conflito=["cliente", "data_captura"],
                atualizar=["indice_medio_movel", "qtd_titulos_considerados"],
            )


def fetch_historico_cliente(cliente: str) -> pd.DataFrame:
    return db.read_df(
        """SELECT data_captura, indice_medio_movel, qtd_titulos_considerados
           FROM velocidade_pagamento_snapshot WHERE cliente = %(c)s
           ORDER BY data_captura""",
        {"c": cliente},
    )


def fetch_ultimo_indice_por_cliente() -> pd.DataFrame:
    """Índice médio móvel mais recente de cada cliente — usado por
    reajuste_limite, tolerancia e fluxo_caixa."""
    return db.read_df(
        """
        SELECT DISTINCT ON (cliente) cliente, data_captura, indice_medio_movel, qtd_titulos_considerados
        FROM velocidade_pagamento_snapshot
        ORDER BY cliente, data_captura DESC
        """
    )
