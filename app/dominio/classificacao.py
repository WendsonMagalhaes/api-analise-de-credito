"""
Score duplo (comportamento x exposição) e classificação A-E.

Independente da `faixa` (verde/amarelo/vermelho) que já roda em
produção em scoring.py — aquela é o score de risco "geral" usado hoje
no dashboard e não é alterada aqui. A classificação A-E é um modelo
novo, pensado especificamente para as regras que citam 5 classes
(reajuste de limite, tolerância, intervalo de reanálise):

  - score_comportamento (0-100): baseado em COMO o cliente paga —
    velocidade de pagamento normalizada pelo prazo do título
    (velocidade.py) e % de títulos pagos em atraso. Não usa dias
    absolutos de atraso (isso é papel do score antigo); usa o índice
    proporcional ao prazo, coerente com prazo_do_titulo ser variável.
  - score_exposicao (0-100): baseado em QUANTO o cliente representa de
    risco em valor — percentil do valor em aberto dele dentro da
    carteira inteira (quanto maior a fatia, menor o score) e margem
    sobre o limite já cadastrado.
  - score_composto: média ponderada dos dois eixos (peso configurável
    futuramente; por ora 60% comportamento / 40% exposição — comportamento
    pesa mais porque prevê melhor se o cliente vai honrar um limite maior).
  - classe: A (score_composto >= 85) até E (< 30), thresholds abaixo.

Ambos os eixos ficam gravados separados (colunas score_comportamento e
score_exposicao) mesmo depois de compostos, porque um cliente pode ser
ótimo pagador (comportamento alto) mas já muito exposto (exposição
baixa) — combinações que a UI e o motor de recomendação (recomendacao.py)
precisam distinguir, não só o número final.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app import db

PESO_COMPORTAMENTO = 0.6
PESO_EXPOSICAO = 0.4

_LIMIARES_CLASSE = [
    (85, "A"),
    (70, "B"),
    (50, "C"),
    (30, "D"),
]


def _classe_por_score(score_composto: float) -> str:
    for limiar, classe in _LIMIARES_CLASSE:
        if score_composto >= limiar:
            return classe
    return "E"


def calcular_score_comportamento(row) -> float:
    """
    Começa em 100 e desconta por:
      - índice de velocidade médio acima de 1 (atraso proporcional ao
        prazo do próprio título — não em dias fixos)
      - % de títulos pagos em atraso (histórico geral, vem de scoring.py)
    Sem histórico de pagamento (indice_medio_movel ausente): score
    neutro (60), igual ao critério já usado no score antigo.
    """
    indice = row.get("indice_medio_movel")
    if indice is None or pd.isna(indice):
        return 60.0

    score = 100.0
    if indice > 1:
        # cada 0.1 acima de 1.0 (10% do prazo em atraso) desconta 8 pontos,
        # até no máximo 60 — evita que um único atraso enorme zere o eixo
        score -= min(60.0, (indice - 1) * 10 * 8)
    else:
        # adiantamento consistente soma um pequeno bônus (até +5)
        score += min(5.0, (1 - indice) * 10)

    pct_atraso = row.get("pct_pago_em_atraso") or 0
    score -= min(20.0, pct_atraso * 0.2)

    return round(max(0.0, min(100.0, score)), 1)


def calcular_score_exposicao(row, mediana_valor_aberto: float, maximo_valor_aberto: float) -> float:
    """
    100 = exposição irrelevante perto da carteira; 0 = maior exposição da
    carteira. Usa a posição relativa (valor_em_aberto / maior valor da
    carteira) em vez de um valor absoluto fixo, pra continuar fazendo
    sentido conforme a carteira cresce.
    """
    valor = row.get("valor_em_aberto") or 0
    if maximo_valor_aberto <= 0:
        return 100.0
    posicao = valor / maximo_valor_aberto  # 0 a 1
    score = 100.0 * (1 - posicao)
    return round(max(0.0, min(100.0, score)), 1)


def classificar_carteira(
    carteira_df: pd.DataFrame, velocidade_df: pd.DataFrame, data_captura: date | None = None
) -> pd.DataFrame:
    """
    Recebe a carteira já calculada (scoring.calcular_score_clientes) e o
    índice de velocidade mais recente por cliente, e devolve com
    score_comportamento, score_exposicao, score_composto e classe (A-E).
    """
    if carteira_df.empty:
        for col in ("score_comportamento", "score_exposicao", "score_composto", "classe_risco_5"):
            carteira_df[col] = pd.Series(dtype="object")
        return carteira_df

    df = pd.merge(
        carteira_df,
        velocidade_df[["cliente", "indice_medio_movel"]] if not velocidade_df.empty else pd.DataFrame(columns=["cliente", "indice_medio_movel"]),
        on="cliente",
        how="left",
    )

    maximo_valor_aberto = float(df["valor_em_aberto"].fillna(0).max() or 0)

    df["score_comportamento"] = df.apply(calcular_score_comportamento, axis=1)
    df["score_exposicao"] = df.apply(
        lambda r: calcular_score_exposicao(r, 0, maximo_valor_aberto), axis=1
    )
    df["score_composto"] = (
        df["score_comportamento"] * PESO_COMPORTAMENTO + df["score_exposicao"] * PESO_EXPOSICAO
    ).round(1)
    df["classe_risco_5"] = df["score_composto"].apply(_classe_por_score)

    return df


def _num_ou_none(v):
    """Converte NaN/NaT do pandas para None — Json(...)/json.dumps grava
    NaN como o token literal `NaN`, que não é JSON válido e o Postgres
    rejeita na hora de gravar (era a causa do upload falhar com
    'invalid input syntax for type json ... Token "NaN" is invalid')."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v


def salvar_snapshot(df_classificado: pd.DataFrame, data_captura: date, conn=None) -> None:
    """Histórico append-only da classificação A-E (não sobrescreve datas
    anteriores; upsert só reaplica na MESMA data em reimportação).
    `conn` opcional: participa da transação de quem chamou."""
    if df_classificado.empty:
        return
    rows = []
    for r in df_classificado.to_dict("records"):
        criterio = {
            "peso_comportamento": PESO_COMPORTAMENTO,
            "peso_exposicao": PESO_EXPOSICAO,
            "indice_medio_movel": _num_ou_none(r.get("indice_medio_movel")),
            "pct_pago_em_atraso": _num_ou_none(r.get("pct_pago_em_atraso")),
        }
        rows.append(
            (
                r["cliente"],
                data_captura,
                r["classe_risco_5"],
                _num_ou_none(r.get("score_comportamento")),
                _num_ou_none(r.get("score_exposicao")),
                _num_ou_none(r.get("score_composto")),
                criterio,
            )
        )
    with db.conn_ou_nova(conn) as c:
        with c.cursor() as cur:
            db.bulk_upsert(
                cur,
                "classificacao_snapshot",
                ["cliente", "data_captura", "classe", "score_comportamento",
                 "score_exposicao", "score_composto", "criterio"],
                rows,
                conflito=["cliente", "data_captura"],
                atualizar=["classe", "score_comportamento", "score_exposicao", "score_composto", "criterio"],
            )


def fetch_historico_cliente(cliente: str) -> pd.DataFrame:
    return db.read_df(
        """SELECT data_captura, classe, score_comportamento, score_exposicao, score_composto
           FROM classificacao_snapshot WHERE cliente = %(c)s ORDER BY data_captura""",
        {"c": cliente},
    )


def fetch_ultimas_n_classes(cliente: str, n: int = 3) -> list[str]:
    """Últimas N classes do cliente, mais recente primeiro — usado na
    elegibilidade de reajuste de limite (precisa de A ou B nos últimos 3)."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT classe FROM classificacao_snapshot
                   WHERE cliente = %(c)s ORDER BY data_captura DESC LIMIT %(n)s""",
                {"c": cliente, "n": n},
            )
            return [r["classe"] for r in cur.fetchall()]


def fetch_classe_anterior(cliente: str, antes_de) -> str | None:
    """Classe do snapshot mais recente ANTES de `antes_de` (normalmente
    hoje) — usado pra detectar queda de classe sem se confundir com uma
    segunda execução do recálculo no mesmo dia (ver reanalise.py).
    Mantida pra compatibilidade; pra recalcular a carteira inteira, use
    fetch_classes_anteriores (uma consulta só em vez de uma por cliente)."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT classe FROM classificacao_snapshot
                   WHERE cliente = %(c)s AND data_captura < %(d)s
                   ORDER BY data_captura DESC LIMIT 1""",
                {"c": cliente, "d": antes_de},
            )
            row = cur.fetchone()
            return row["classe"] if row else None


def fetch_classes_anteriores(clientes: list[str], antes_de) -> dict[str, str]:
    """Como fetch_classe_anterior, mas para TODOS os clientes de uma vez
    numa única consulta — usada no recálculo da carteira inteira depois
    de cada upload. Antes, era uma consulta por cliente dentro de um
    loop (_recalcular_e_salvar_carteira em main.py): centenas de idas e
    vindas ao banco, uma atrás da outra, o que pode deixar o upload
    "travado" por bastante tempo sem erro nenhum — sobretudo com o
    banco hospedado fora da máquina local (Neon), onde cada ida e volta
    tem uma latência de rede real."""
    if not clientes:
        return {}
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (cliente) cliente, classe
                FROM classificacao_snapshot
                WHERE cliente = ANY(%(clientes)s) AND data_captura < %(d)s
                ORDER BY cliente, data_captura DESC
                """,
                {"clientes": list(clientes), "d": antes_de},
            )
            return {row["cliente"]: row["classe"] for row in cur.fetchall()}
