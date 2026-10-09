"""
Reajuste de limite (aumento gradual), só pra classes A e B.

Elegibilidade (todas as condições):
  - classe A ou B nos últimos 3 snapshots de classificação (classificacao.py)
  - zero títulos vencidos hoje (dias_vencido_max == 0, do cache carteira_atual)
  - velocidade de pagamento média <= limiar configurável (padrão 0.7 —
    ou seja, historicamente paga em até 70% do prazo do título)
  - mínimo de N ciclos completos de compra/pagamento (padrão 3, contado
    por qtd_titulos_pagos)
  - respeita o intervalo mínimo entre revisões da própria classe (90 dias
    pra A, 120 pra B) — não sugere de novo antes disso

O aumento em si é sempre percentual sobre o limite atual (nunca um valor
fixo), limitado pelo teto por classe e, se configurado, por um teto
absoluto em R$ por revisão. Nunca libera 100% sozinho: grava como
'sugerido' e exige aprovação manual (ver aprovar/rejeitar).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from psycopg2.extras import Json

from app.dominio import classificacao
from app.db import config
from app import db
from app.core.formatacao import fmt_num_livre

CHAVE_PCT_MAX = "reajuste_percentual_maximo_por_classe"
CHAVE_CICLO_DIAS = "reajuste_ciclo_dias_por_classe"
CHAVE_TETO_ABSOLUTO = "reajuste_teto_absoluto_valor"
CHAVE_VELOCIDADE_MAX = "reajuste_velocidade_media_maxima"
CHAVE_MIN_CICLOS = "reajuste_minimo_ciclos_completos"

_PADRAO_PCT_MAX = {"A": 20, "B": 10}
_PADRAO_CICLO_DIAS = {"A": 90, "B": 120}


def _ultima_revisao(cliente: str) -> date | None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT MAX(sugerido_em) AS d FROM reajustes_limite
                   WHERE cliente = %(c)s AND status != 'rejeitado'""",
                {"c": cliente},
            )
            d = cur.fetchone()["d"]
            return d.date() if d else None


def avaliar_elegibilidade(cliente: str, linha_carteira: dict, indice_medio_movel: float | None) -> dict:
    """Devolve {'elegivel': bool, 'motivos': [...], 'classe': ...} — sempre
    com os motivos, elegível ou não, pra auditoria/transparência."""
    motivos = []
    classes_recentes = classificacao.fetch_ultimas_n_classes(cliente, n=3)
    classe_atual = classes_recentes[0] if classes_recentes else None

    if classe_atual not in ("A", "B"):
        return {"elegivel": False, "motivos": ["Classe atual não é A nem B."], "classe": classe_atual}
    if len(classes_recentes) < 3 or any(c not in ("A", "B") for c in classes_recentes):
        motivos.append("Precisa estar em A ou B nos últimos 3 snapshots de classificação.")

    if (linha_carteira.get("dias_vencido_max") or 0) > 0:
        motivos.append("Cliente tem título(s) vencido(s) em aberto hoje.")

    velocidade_max = config.get(CHAVE_VELOCIDADE_MAX, 0.7)
    if indice_medio_movel is None or indice_medio_movel > velocidade_max:
        motivos.append(f"Velocidade de pagamento média acima do limiar ({fmt_num_livre(velocidade_max)}).")

    min_ciclos = config.get(CHAVE_MIN_CICLOS, 3)
    if (linha_carteira.get("qtd_titulos_pagos") or 0) < min_ciclos:
        motivos.append(f"Menos de {min_ciclos} ciclos completos de compra/pagamento.")

    ciclo_dias = config.get(CHAVE_CICLO_DIAS, _PADRAO_CICLO_DIAS).get(classe_atual, 90)
    ultima = _ultima_revisao(cliente)
    if ultima and (date.today() - ultima).days < ciclo_dias:
        proxima = ultima + timedelta(days=ciclo_dias)
        motivos.append(f"Última revisão em {ultima.isoformat()} — próxima elegível em {proxima.isoformat()}.")

    return {"elegivel": len(motivos) == 0, "motivos": motivos, "classe": classe_atual}


def gerar_sugestao(cliente: str, linha_carteira: dict, indice_medio_movel: float | None) -> dict | None:
    """Calcula e GRAVA (status='sugerido') a sugestão de aumento, se
    elegível. Devolve None se não elegível."""
    avaliacao = avaliar_elegibilidade(cliente, linha_carteira, indice_medio_movel)
    if not avaliacao["elegivel"]:
        return None

    classe = avaliacao["classe"]
    limite_atual = float(linha_carteira.get("limite_atual") or 0)
    if limite_atual <= 0:
        return None

    pct_max = config.get(CHAVE_PCT_MAX, _PADRAO_PCT_MAX).get(classe, 0)
    aumento = limite_atual * (pct_max / 100)

    teto_absoluto = config.get(CHAVE_TETO_ABSOLUTO)
    teto_aplicado = False
    if teto_absoluto is not None and aumento > float(teto_absoluto):
        aumento = float(teto_absoluto)
        teto_aplicado = True

    limite_sugerido = round(limite_atual + aumento, 2)

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reajustes_limite
                    (cliente, classe, limite_anterior, limite_sugerido, percentual_aplicado,
                     teto_absoluto_aplicado, motivo)
                VALUES (%(cliente)s, %(classe)s, %(anterior)s, %(sugerido)s, %(pct)s, %(teto)s, %(motivo)s)
                RETURNING id
                """,
                {
                    "cliente": cliente,
                    "classe": classe,
                    "anterior": limite_atual,
                    "sugerido": limite_sugerido,
                    "pct": pct_max,
                    "teto": teto_aplicado,
                    "motivo": Json({"regra": f"Classe {classe}: até {fmt_num_livre(pct_max)}% do limite atual, a cada revisão."}),
                },
            )
            novo_id = cur.fetchone()["id"]
        conn.commit()

    return {
        "id": novo_id,
        "cliente": cliente,
        "classe": classe,
        "limite_anterior": limite_atual,
        "limite_sugerido": limite_sugerido,
        "percentual_aplicado": pct_max,
        "teto_absoluto_aplicado": teto_aplicado,
    }


def fetch_pendentes() -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM reajustes_limite WHERE status = 'sugerido' ORDER BY sugerido_em DESC",
        db.get_engine(),
    )


def fetch_historico_cliente(cliente: str) -> pd.DataFrame:
    """Todo o histórico de reajustes (sugerido/aprovado/rejeitado) de um
    cliente específico, mais recente primeiro — usado na tela de detalhe
    do cliente pra mostrar o histórico de aumento de limite."""
    return pd.read_sql_query(
        "SELECT * FROM reajustes_limite WHERE cliente = %(c)s ORDER BY sugerido_em DESC",
        db.get_engine(),
        params={"c": cliente},
    )


def aprovar(reajuste_id: int, aprovado_por: str | None) -> None:
    """Aprova com um clique: atualiza o status E já reflete o novo valor
    em limite_atual_cliente (fonte usada pelo score/dashboard)."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cliente, limite_sugerido FROM reajustes_limite WHERE id = %(id)s AND status = 'sugerido'",
                {"id": reajuste_id},
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Reajuste não encontrado ou já decidido.")

            cur.execute(
                """UPDATE reajustes_limite SET status = 'aprovado', decidido_em = NOW(), aprovado_por = %(por)s
                   WHERE id = %(id)s""",
                {"id": reajuste_id, "por": aprovado_por},
            )
            cur.execute(
                """INSERT INTO limite_atual_cliente (cliente, limite_atual) VALUES (%(c)s, %(v)s)
                   ON CONFLICT (cliente) DO UPDATE SET limite_atual = EXCLUDED.limite_atual, atualizado_em = NOW()""",
                {"c": row["cliente"], "v": row["limite_sugerido"]},
            )
        conn.commit()


def rejeitar(reajuste_id: int, aprovado_por: str | None) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE reajustes_limite SET status = 'rejeitado', decidido_em = NOW(), aprovado_por = %(por)s
                   WHERE id = %(id)s AND status = 'sugerido'""",
                {"id": reajuste_id, "por": aprovado_por},
            )
        conn.commit()
