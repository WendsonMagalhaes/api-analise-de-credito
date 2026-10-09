"""
Números do dashboard que não moram em carteira_atual: o que está em aberto no
mês, o que já venceu, o que entrou no mês e a quebra por carteira (coluna
"Plano de Conta" do relatório do ERP: BOLETO, DOAÇÕES etc.) e por vendedor.

Tudo sai da foto MAIS RECENTE de títulos em aberto (abertos_snapshot) e do
histórico de pagamentos, com o mesmo filtro de categorias contábeis (AVARIA,
QUEBRA DE ESTOQUE etc.) que o resto do dashboard usa — assim o total daqui
fecha com o "Em aberto hoje".

Definições (todas relativas a `hoje`, passado de fora para bater com o
date.today() do resto do sistema, e não com o CURRENT_DATE do banco, que no
Neon está em UTC):
  - vencido:          data_vencimento < hoje
  - em aberto no mês: data_vencimento dentro do mês corrente (a vencer + já vencidos)
  - recebido no mês:  pagamentos com data_pagamento do dia 1º até hoje
"""
from __future__ import annotations

from datetime import date, timedelta

from app import db

SEM_CARTEIRA = "Sem carteira"
SEM_VENDEDOR = "Sem vendedor"
TOP_VENDEDORES = 15

_ULTIMA_FOTO = "data_captura = (SELECT MAX(data_captura) FROM abertos_snapshot)"


def _limites_do_mes(hoje: date) -> tuple[date, date]:
    inicio = hoje.replace(day=1)
    prox = (inicio + timedelta(days=32)).replace(day=1)
    return inicio, prox


def _f(v) -> float:
    return round(float(v or 0), 2)


def _totais_abertos(excl: str, p: dict) -> dict:
    r = db.fetch_all(
        f"""
        SELECT
            COALESCE(SUM(valor), 0)                                        AS total,
            COUNT(*)                                                       AS qtd,
            COALESCE(SUM(valor) FILTER (WHERE data_vencimento < %(hoje)s), 0) AS venc_valor,
            COUNT(*) FILTER (WHERE data_vencimento < %(hoje)s)             AS venc_qtd,
            COUNT(DISTINCT cliente) FILTER (WHERE data_vencimento < %(hoje)s) AS venc_clientes,
            MAX(%(hoje)s - data_vencimento) FILTER (WHERE data_vencimento < %(hoje)s) AS maior_atraso,

            COALESCE(SUM(valor) FILTER (WHERE data_vencimento >= %(ini)s AND data_vencimento < %(prox)s), 0) AS mes_valor,
            COUNT(*) FILTER (WHERE data_vencimento >= %(ini)s AND data_vencimento < %(prox)s)                AS mes_qtd,
            COALESCE(SUM(valor) FILTER (WHERE data_vencimento >= %(hoje)s AND data_vencimento < %(prox)s), 0) AS mes_a_vencer_valor,
            COUNT(*) FILTER (WHERE data_vencimento >= %(hoje)s AND data_vencimento < %(prox)s)                AS mes_a_vencer_qtd,
            COALESCE(SUM(valor) FILTER (WHERE data_vencimento >= %(ini)s AND data_vencimento < %(hoje)s), 0)  AS mes_vencido_valor,
            COUNT(*) FILTER (WHERE data_vencimento >= %(ini)s AND data_vencimento < %(hoje)s)                 AS mes_vencido_qtd,

            COALESCE(SUM(valor) FILTER (WHERE %(hoje)s - data_vencimento BETWEEN 1 AND 7), 0)  AS f1_valor,
            COUNT(*)            FILTER (WHERE %(hoje)s - data_vencimento BETWEEN 1 AND 7)      AS f1_qtd,
            COALESCE(SUM(valor) FILTER (WHERE %(hoje)s - data_vencimento BETWEEN 8 AND 15), 0) AS f2_valor,
            COUNT(*)            FILTER (WHERE %(hoje)s - data_vencimento BETWEEN 8 AND 15)     AS f2_qtd,
            COALESCE(SUM(valor) FILTER (WHERE %(hoje)s - data_vencimento BETWEEN 16 AND 30), 0) AS f3_valor,
            COUNT(*)            FILTER (WHERE %(hoje)s - data_vencimento BETWEEN 16 AND 30)    AS f3_qtd,
            COALESCE(SUM(valor) FILTER (WHERE %(hoje)s - data_vencimento > 30), 0)             AS f4_valor,
            COUNT(*)            FILTER (WHERE %(hoje)s - data_vencimento > 30)                 AS f4_qtd
        FROM abertos_snapshot
        WHERE {_ULTIMA_FOTO} AND {excl}
        """,
        p,
    )[0]
    total = _f(r["total"])
    return {
        "total_aberto": total,
        "qtd_titulos": r["qtd"],
        "vencidos": {
            "valor": _f(r["venc_valor"]),
            "qtd_titulos": r["venc_qtd"],
            "qtd_clientes": r["venc_clientes"],
            "pct_do_aberto": round(_f(r["venc_valor"]) / total * 100, 1) if total else 0.0,
            "maior_atraso_dias": r["maior_atraso"],
            "faixas": [
                {"faixa": "1 a 7 dias", "valor": _f(r["f1_valor"]), "qtd_titulos": r["f1_qtd"]},
                {"faixa": "8 a 15 dias", "valor": _f(r["f2_valor"]), "qtd_titulos": r["f2_qtd"]},
                {"faixa": "16 a 30 dias", "valor": _f(r["f3_valor"]), "qtd_titulos": r["f3_qtd"]},
                {"faixa": "Mais de 30 dias", "valor": _f(r["f4_valor"]), "qtd_titulos": r["f4_qtd"]},
            ],
        },
        "em_aberto_mes": {
            "valor": _f(r["mes_valor"]),
            "qtd_titulos": r["mes_qtd"],
            "a_vencer_valor": _f(r["mes_a_vencer_valor"]),
            "a_vencer_qtd": r["mes_a_vencer_qtd"],
            "vencido_valor": _f(r["mes_vencido_valor"]),
            "vencido_qtd": r["mes_vencido_qtd"],
        },
    }


def _por_carteira(excl: str, p: dict) -> list[dict]:
    rows = db.fetch_all(
        f"""
        SELECT COALESCE(NULLIF(TRIM(plano_conta), ''), %(sem)s)           AS carteira,
               COUNT(*)                                                    AS qtd,
               COUNT(DISTINCT cliente)                                     AS clientes,
               COALESCE(SUM(valor), 0)                                     AS aberto,
               COALESCE(SUM(valor) FILTER (WHERE data_vencimento < %(hoje)s), 0) AS vencido,
               COUNT(*) FILTER (WHERE data_vencimento < %(hoje)s)          AS venc_qtd
        FROM abertos_snapshot
        WHERE {_ULTIMA_FOTO} AND {excl}
        GROUP BY 1
        ORDER BY aberto DESC, carteira
        """,
        {**p, "sem": SEM_CARTEIRA},
    )
    total = sum(float(r["aberto"] or 0) for r in rows)
    return [
        {
            "carteira": r["carteira"],
            "qtd_titulos": r["qtd"],
            "qtd_clientes": r["clientes"],
            "valor_aberto": _f(r["aberto"]),
            "valor_vencido": _f(r["vencido"]),
            "qtd_vencidos": r["venc_qtd"],
            "pct_do_aberto": round(float(r["aberto"] or 0) / total * 100, 1) if total else 0.0,
            "pct_vencido": round(float(r["vencido"] or 0) / float(r["aberto"]) * 100, 1) if r["aberto"] else 0.0,
        }
        for r in rows
    ]


def _vendedores_abertos(excl: str, p: dict) -> list[dict]:
    return db.fetch_all(
        f"""
        SELECT COALESCE(NULLIF(TRIM(vendedor), ''), %(sem)s)               AS vendedor,
               COUNT(*)                                                     AS qtd,
               COUNT(DISTINCT cliente)                                      AS clientes,
               COALESCE(SUM(valor), 0)                                      AS aberto,
               COALESCE(SUM(valor) FILTER (WHERE data_vencimento < %(hoje)s), 0) AS vencido,
               COUNT(*) FILTER (WHERE data_vencimento < %(hoje)s)           AS venc_qtd
        FROM abertos_snapshot
        WHERE {_ULTIMA_FOTO} AND {excl}
        GROUP BY 1
        ORDER BY aberto DESC, vendedor
        """,
        {**p, "sem": SEM_VENDEDOR},
    )


def _vendedores_pagamentos(excl: str, p: dict) -> list[dict]:
    """Por vendedor: quanto entrou no mês e o atraso médio de pagamento dos
    últimos 90 dias (data_pagamento - data_vencimento; negativo = adiantado)."""
    return db.fetch_all(
        f"""
        SELECT COALESCE(NULLIF(TRIM(vendedor), ''), %(sem)s) AS vendedor,
               COALESCE(SUM(valor_pago) FILTER (WHERE data_pagamento >= %(ini)s), 0) AS recebido_mes,
               AVG(data_pagamento - data_vencimento)
                   FILTER (WHERE data_pagamento >= %(hoje)s - 90 AND data_vencimento IS NOT NULL) AS atraso_90d
        FROM pagamentos
        WHERE data_pagamento >= LEAST(%(ini)s, %(hoje)s - 90) AND data_pagamento <= %(hoje)s AND {excl}
        GROUP BY 1
        """,
        {**p, "sem": SEM_VENDEDOR},
    )


def _recebido_mes(excl: str, p: dict) -> dict:
    r = db.fetch_all(
        f"""
        SELECT COALESCE(SUM(valor_pago), 0) AS valor, COUNT(*) AS qtd
        FROM pagamentos
        WHERE data_pagamento >= %(ini)s AND data_pagamento <= %(hoje)s AND {excl}
        """,
        p,
    )[0]
    return {"valor": _f(r["valor"]), "qtd_titulos": r["qtd"]}


def calcular(hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    ini, prox = _limites_do_mes(hoje)
    excl, padroes = db.filtro_exclusao()
    p = {"hoje": hoje, "ini": ini, "prox": prox, "padroes_exclusao": padroes}

    totais, carteiras, vend_abertos, vend_pgto, recebido = db.run_parallel(
        lambda: _totais_abertos(excl, p),
        lambda: _por_carteira(excl, p),
        lambda: _vendedores_abertos(excl, p),
        lambda: _vendedores_pagamentos(excl, p),
        lambda: _recebido_mes(excl, p),
    )

    pgto = {r["vendedor"]: r for r in vend_pgto}
    total = totais["total_aberto"]
    vendedores = []
    for r in vend_abertos:
        pg = pgto.get(r["vendedor"])
        aberto = float(r["aberto"] or 0)
        vendedores.append(
            {
                "vendedor": r["vendedor"],
                "qtd_clientes": r["clientes"],
                "qtd_titulos": r["qtd"],
                "valor_aberto": _f(aberto),
                "valor_vencido": _f(r["vencido"]),
                "qtd_vencidos": r["venc_qtd"],
                "pct_do_aberto": round(aberto / total * 100, 1) if total else 0.0,
                "pct_vencido": round(float(r["vencido"] or 0) / aberto * 100, 1) if aberto else 0.0,
                "recebido_mes": _f(pg["recebido_mes"]) if pg else 0.0,
                "atraso_medio_90d": round(float(pg["atraso_90d"]), 1) if pg and pg["atraso_90d"] is not None else None,
            }
        )

    return {
        "hoje": hoje.isoformat(),
        "mes_referencia": ini.isoformat(),
        **totais,
        "recebido_mes": recebido,
        "por_carteira": carteiras,
        "carteira_informada": any(c["carteira"] != SEM_CARTEIRA for c in carteiras),
        "vendedores_total": len(vendedores),
        "por_vendedor": vendedores[:TOP_VENDEDORES],
    }
