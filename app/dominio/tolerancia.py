"""
Margem de tolerância acima do limite formal (não altera o limite
cadastrado — só define até quanto pode ser liberado além dele).

Percentual por classe (configurável): A até 15%, B até 8% (só se atraso
médio < limiar configurado), C até 3% (só valores baixos, teto em R$
configurável), D/E sem tolerância.

valor_maximo_liberado = limite_atual + (limite_atual × tolerância), com
um teto de proteção adicional: a tolerância nunca pode levar o saldo do
cliente a ultrapassar um % configurável da carteira total em aberto —
protege a carteira mesmo se o % individual parecer razoável.

Toda vez que o valor em aberto de um cliente ultrapassa o limite
cadastrado (mesmo dentro da tolerância), gera um registro de auditoria
em tolerancia_eventos — mesmo uso "normal" da tolerância fica rastreado.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.db import config
from app import db

CHAVE_PCT_POR_CLASSE = "tolerancia_percentual_por_classe"
CHAVE_CLASSE_B_ATRASO_MAX = "tolerancia_classe_b_atraso_medio_max_dias"
CHAVE_CLASSE_C_VALOR_MAX = "tolerancia_classe_c_valor_maximo"
CHAVE_TETO_CARTEIRA_PCT = "tolerancia_teto_carteira_pct"

_PADRAO_PCT = {"A": 15, "B": 8, "C": 3, "D": 0, "E": 0}


def calcular_tolerancia_pct(classe: str, atraso_medio_dias: float | None, valor_em_aberto: float) -> float:
    """Percentual de tolerância efetivo pro cliente, já considerando as
    exceções por classe (B exige baixo atraso; C só vale para saldo baixo)."""
    pct_base = config.get(CHAVE_PCT_POR_CLASSE, _PADRAO_PCT).get(classe, 0)

    if classe == "B":
        limiar_atraso = config.get(CHAVE_CLASSE_B_ATRASO_MAX, 5)
        if atraso_medio_dias is None or atraso_medio_dias >= limiar_atraso:
            return 0.0

    if classe == "C":
        teto_valor = config.get(CHAVE_CLASSE_C_VALOR_MAX, 500)
        if valor_em_aberto > float(teto_valor):
            return 0.0

    return float(pct_base)


def calcular_valor_maximo_liberado(
    limite_atual: float, classe: str, atraso_medio_dias: float | None, valor_em_aberto: float, valor_total_carteira: float
) -> dict:
    """Devolve valor_maximo_liberado já com o teto de proteção da carteira
    aplicado, e o detalhe de qual regra limitou (tolerância normal ou
    teto de proteção)."""
    tolerancia_pct = calcular_tolerancia_pct(classe, atraso_medio_dias, valor_em_aberto)
    valor_maximo_por_tolerancia = round(limite_atual + limite_atual * tolerancia_pct / 100, 2)

    teto_carteira_pct = config.get(CHAVE_TETO_CARTEIRA_PCT, 5)
    teto_protecao = round(float(valor_total_carteira) * teto_carteira_pct / 100, 2) if valor_total_carteira else None

    valor_maximo_liberado = valor_maximo_por_tolerancia
    limitado_por_teto_carteira = False
    if teto_protecao is not None and valor_maximo_por_tolerancia > teto_protecao:
        valor_maximo_liberado = teto_protecao
        limitado_por_teto_carteira = True

    return {
        "tolerancia_pct": tolerancia_pct,
        "valor_maximo_por_tolerancia": valor_maximo_por_tolerancia,
        "teto_protecao_carteira": teto_protecao,
        "valor_maximo_liberado": valor_maximo_liberado,
        "limitado_por_teto_carteira": limitado_por_teto_carteira,
    }


def registrar_evento_se_acima_do_limite(
    cliente: str, classe: str, limite_atual: float, valor_em_aberto: float, calculo: dict, data_captura: date | None = None
) -> None:
    """Grava evento de auditoria SEMPRE que o saldo em aberto ultrapassa o
    limite cadastrado — mesmo dentro da tolerância normal."""
    if valor_em_aberto <= limite_atual:
        return
    data_captura = data_captura or date.today()
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tolerancia_eventos
                    (cliente, data_captura, classe, limite_atual, tolerancia_pct,
                     valor_maximo_liberado, valor_em_aberto, valor_acima_do_limite)
                VALUES (%(cliente)s, %(data)s, %(classe)s, %(limite)s, %(pct)s, %(max)s, %(aberto)s, %(acima)s)
                ON CONFLICT (cliente, data_captura) DO UPDATE SET
                    limite_atual = EXCLUDED.limite_atual,
                    tolerancia_pct = EXCLUDED.tolerancia_pct,
                    valor_maximo_liberado = EXCLUDED.valor_maximo_liberado,
                    valor_em_aberto = EXCLUDED.valor_em_aberto,
                    valor_acima_do_limite = EXCLUDED.valor_acima_do_limite
                """,
                {
                    "cliente": cliente,
                    "data": data_captura,
                    "classe": classe,
                    "limite": limite_atual,
                    "pct": calculo["tolerancia_pct"],
                    "max": calculo["valor_maximo_liberado"],
                    "aberto": valor_em_aberto,
                    "acima": round(valor_em_aberto - limite_atual, 2),
                },
            )
        conn.commit()


def registrar_eventos_em_lote(eventos: list[dict], conn=None) -> int:
    """Versão em lote de registrar_evento_se_acima_do_limite: grava todos os
    eventos da carteira de uma vez (antes: uma transação por cliente).
    Cada item: {cliente, data_captura, classe, limite_atual, calculo, valor_em_aberto}
    onde `calculo` é o retorno de calcular_valor_maximo_liberado."""
    linhas = [
        (
            e["cliente"],
            e["data_captura"],
            e["classe"],
            e["limite_atual"],
            e["calculo"]["tolerancia_pct"],
            e["calculo"]["valor_maximo_liberado"],
            e["valor_em_aberto"],
            round(e["valor_em_aberto"] - e["limite_atual"], 2),
        )
        for e in eventos
    ]
    with db.conn_ou_nova(conn) as c:
        with c.cursor() as cur:
            return db.bulk_upsert(
                cur,
                "tolerancia_eventos",
                ["cliente", "data_captura", "classe", "limite_atual", "tolerancia_pct",
                 "valor_maximo_liberado", "valor_em_aberto", "valor_acima_do_limite"],
                linhas,
                conflito=["cliente", "data_captura"],
                atualizar=["classe", "limite_atual", "tolerancia_pct", "valor_maximo_liberado",
                           "valor_em_aberto", "valor_acima_do_limite"],
            )


def contar_usos_no_trimestre_em_lote(clientes: list[str], conn) -> dict[str, int]:
    """Usos de tolerância nos últimos 90 dias de VÁRIOS clientes numa consulta
    só. Roda na conexão recebida para enxergar os eventos que acabaram de ser
    gravados na mesma transação."""
    if not clientes:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT cliente, COUNT(*) AS c FROM tolerancia_eventos
               WHERE cliente = ANY(%(cs)s) AND data_captura >= CURRENT_DATE - INTERVAL '90 days'
               GROUP BY cliente""",
            {"cs": list(clientes)},
        )
        return {r["cliente"]: r["c"] for r in cur.fetchall()}


def contar_usos_no_trimestre(cliente: str) -> int:
    """Quantidade de eventos de tolerância nos últimos 90 dias — usado
    pelo gatilho de reanálise (mais de N usos no trimestre)."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS c FROM tolerancia_eventos
                   WHERE cliente = %(c)s AND data_captura >= CURRENT_DATE - INTERVAL '90 days'""",
                {"c": cliente},
            )
            return cur.fetchone()["c"]


def fetch_eventos_cliente(cliente: str) -> pd.DataFrame:
    return db.read_df(
        "SELECT * FROM tolerancia_eventos WHERE cliente = %(c)s ORDER BY data_captura DESC",
        {"c": cliente},
    )
