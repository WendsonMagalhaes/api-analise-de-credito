"""Métricas do período: maior compra e maior atraso de hoje, por cliente e no total.

Fonte: títulos pagos (pagamentos) + títulos em aberto da foto mais recente
(abertos_snapshot). O período filtra pela data de EMISSÃO do título.
Categorias contábeis (AVARIA etc.) ficam de fora, como no resto do sistema.
Todo valor vindo de fora vai como parâmetro (%(nome)s), nunca no texto do SQL.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.db.conexao import fetch_all, read_df
from app.db.exclusoes import filtro_exclusao

_CTE = """
WITH base AS (
    SELECT cliente, data_emissao, valor, NULL::date AS data_vencimento, FALSE AS aberto
    FROM pagamentos
    UNION ALL
    SELECT cliente, data_emissao, valor, data_vencimento, TRUE AS aberto
    FROM abertos_snapshot
    WHERE data_captura = (SELECT MAX(data_captura) FROM abertos_snapshot)
),
filtrado AS (
    SELECT * FROM base
    WHERE {excl}
      AND (%(inicio)s::date IS NULL OR data_emissao >= %(inicio)s::date)
      {extra}
)
"""


def _montar(clientes: list[str] | None, inicio: date | None) -> tuple[str, dict]:
    excl, padroes = filtro_exclusao()
    params: dict = {"inicio": inicio, "padroes_exclusao": padroes}
    extra = ""
    if clientes is not None:
        extra = "AND cliente = ANY(%(clientes)s)"
        params["clientes"] = clientes
    return _CTE.format(excl=excl, extra=extra), params


def fetch_metricas_clientes(clientes: list[str], inicio: date | None) -> pd.DataFrame:
    """Uma linha por cliente: maior_compra (valor) e maior_atraso_hoje (dias)."""
    if not clientes:
        return pd.DataFrame(columns=["cliente", "maior_compra", "maior_atraso_hoje"])
    cte, params = _montar(clientes, inicio)
    return read_df(
        cte
        + """
        SELECT cliente,
               MAX(valor) AS maior_compra,
               MAX(CURRENT_DATE - data_vencimento)
                 FILTER (WHERE aberto AND data_vencimento < CURRENT_DATE) AS maior_atraso_hoje
        FROM filtrado
        GROUP BY cliente
        """,
        params,
    )


def fetch_destaques(inicio: date | None) -> dict:
    """Quem tem a maior compra e o maior atraso de hoje, no período, na carteira toda."""
    cte, params = _montar(None, inicio)
    compra = fetch_all(
        cte + "SELECT cliente, valor FROM filtrado WHERE valor IS NOT NULL ORDER BY valor DESC LIMIT 1",
        params,
    )
    atraso = fetch_all(
        cte
        + """
        SELECT cliente, CURRENT_DATE - data_vencimento AS dias
        FROM filtrado
        WHERE aberto AND data_vencimento < CURRENT_DATE
        ORDER BY dias DESC
        LIMIT 1
        """,
        params,
    )
    return {
        "maior_compra": (
            {"cliente": compra[0]["cliente"], "valor": float(compra[0]["valor"])} if compra else None
        ),
        "maior_atraso": (
            {"cliente": atraso[0]["cliente"], "dias": int(atraso[0]["dias"])} if atraso else None
        ),
    }


def fetch_historico_cliente(cliente: str, inicio: date | None) -> dict:
    """Histórico de pagamentos de UM cliente no período (pela data de emissão do título).

    atraso_medio: média de (data_pagamento - data_vencimento), em dias.
    pct_atraso:   % dos títulos pagos que foram pagos depois do vencimento.
    """
    linha = fetch_all(
        """
        SELECT COUNT(*) AS qtd,
               COALESCE(SUM(valor_pago), 0) AS total,
               AVG(data_pagamento - data_vencimento)
                 FILTER (WHERE data_pagamento IS NOT NULL AND data_vencimento IS NOT NULL) AS atraso_medio,
               100.0 * COUNT(*) FILTER (WHERE data_pagamento > data_vencimento)
                 / NULLIF(COUNT(*) FILTER (WHERE data_pagamento IS NOT NULL AND data_vencimento IS NOT NULL), 0) AS pct_atraso
        FROM pagamentos
        WHERE cliente = %(cliente)s
          AND (%(inicio)s::date IS NULL OR data_emissao >= %(inicio)s::date)
        """,
        {"cliente": cliente, "inicio": inicio},
    )[0]
    return {
        "qtd_pagos": int(linha["qtd"]),
        "total_pago": float(linha["total"] or 0),
        "atraso_medio": float(linha["atraso_medio"]) if linha["atraso_medio"] is not None else None,
        "pct_atraso": float(linha["pct_atraso"]) if linha["pct_atraso"] is not None else None,
    }
