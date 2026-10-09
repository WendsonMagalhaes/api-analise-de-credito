"""Cache da carteira calculada (carteira_atual) e as consultas do dashboard."""
from __future__ import annotations

import json

import pandas as pd

from app.db.conexao import bulk_upsert, conn_ou_nova, fetch_all, read_df
from app.db.conversores import int_ou_none, num_ou_none
from app.db.exclusoes import filtro_exclusao


def _parse_motivos(v) -> list:
    """motivos vem salvo como JSONB; dependendo do driver, o psycopg2 pode
    devolver já como lista/dict ou como texto — trata os dois casos."""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return []
    return []


def _pos_processar_carteira_df(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and "motivos" in df.columns:
        df = df.copy()
        df["motivos"] = df["motivos"].apply(_parse_motivos)
    return df


_COLUNAS_CARTEIRA = [
    "cliente", "qtd_titulos_pagos", "valor_total_pago", "atraso_medio_dias",
    "atraso_maximo_dias", "pct_pago_em_atraso", "pct_pago_muito_atraso",
    "tendencia", "valor_em_aberto", "qtd_titulos_aberto", "dias_vencido_max",
    "capacidade_mensal", "limite_sugerido", "margem_disponivel",
    "limite_atual", "margem_limite_atual", "recomendacao_limite",
    "score", "faixa", "motivos",
    "score_comportamento", "score_exposicao", "classe_risco_5",
    "recomendacao_acao", "regra_recomendacao",
]


def salvar_carteira_atual(score_df: pd.DataFrame, conn=None) -> None:
    """
    Recria o cache da carteira do zero a partir do score já calculado.
    Chamado depois de cada upload (ver main.py) e pelo recálculo manual
    (/api/carteira/recalcular). Guarda TODOS os clientes, inclusive os
    excluídos — o filtro de categoria contábil é aplicado só na leitura
    (ver filtro_exclusao), assim uma exclusão nova ou removida em
    /configuracoes já reflete na hora, sem precisar reimportar nada.

    O DELETE e o INSERT ficam na mesma transação: quem lê nunca vê a
    tabela vazia no meio do recálculo.
    """
    rows = []
    if not score_df.empty:
        conversores = {
            "qtd_titulos_pagos": int_ou_none, "atraso_maximo_dias": int_ou_none,
            "qtd_titulos_aberto": int_ou_none, "dias_vencido_max": int_ou_none,
            "score": int,
        }
        colunas_num = {
            "valor_total_pago", "atraso_medio_dias", "pct_pago_em_atraso", "pct_pago_muito_atraso",
            "valor_em_aberto", "capacidade_mensal", "limite_sugerido", "margem_disponivel",
            "limite_atual", "margem_limite_atual", "score_comportamento", "score_exposicao",
        }
        listas = []
        for col in _COLUNAS_CARTEIRA:
            if col == "motivos":
                serie = score_df["motivos"] if "motivos" in score_df else [None] * len(score_df)
                listas.append([json.dumps(m if isinstance(m, list) else (m or []), ensure_ascii=False) for m in serie])
            elif col in score_df:
                valores = score_df[col].tolist()
                if col in conversores:
                    valores = [conversores[col](v) for v in valores]
                elif col in colunas_num:
                    valores = [num_ou_none(v) for v in valores]
                else:
                    valores = [None if (v is None or (isinstance(v, float) and v != v)) else v for v in valores]
                listas.append(valores)
            else:
                listas.append([None] * len(score_df))
        rows = list(zip(*listas))

    with conn_ou_nova(conn) as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM carteira_atual")
            bulk_upsert(cur, "carteira_atual", _COLUNAS_CARTEIRA, rows)


def fetch_carteira_atualizada_em() -> str | None:
    m = fetch_all("SELECT MAX(atualizado_em) AS m FROM carteira_atual")[0]["m"]
    return m.isoformat() if m else None


def fetch_carteira_paginada(
    pagina: int = 1,
    tamanho_pagina: int = 25,
    busca: str | None = None,
    faixa: str | None = None,
    ordenar_por: str = "score",
    ordenar_dir: str = "asc",
) -> tuple[pd.DataFrame, int]:
    """
    Lê uma página da carteira direto do cache (carteira_atual), com busca
    e ordenação aplicadas no banco — rápido mesmo com uma carteira grande,
    porque nunca traz todo mundo pro Python de uma vez. O total vem na mesma
    consulta (COUNT(*) OVER ()), sem uma segunda ida e volta só pra contar.
    """
    colunas_ordenaveis = {
        "score",
        "valor_em_aberto",
        "atraso_medio_dias",
        "dias_vencido_max",
        "margem_disponivel",
        "margem_limite_atual",
    }
    if ordenar_por not in colunas_ordenaveis:
        ordenar_por = "score"
    ordenar_dir_sql = "DESC" if (ordenar_dir or "").lower() == "desc" else "ASC"

    clausula_exclusao, padroes_exclusao = filtro_exclusao()
    condicoes = [clausula_exclusao]
    params: dict = {"padroes_exclusao": padroes_exclusao}
    if busca:
        condicoes.append("cliente ILIKE %(busca)s")
        params["busca"] = f"%{busca}%"
    if faixa and faixa != "todas":
        condicoes.append("faixa = %(faixa)s")
        params["faixa"] = faixa
    where_sql = "WHERE " + " AND ".join(condicoes)

    offset = max(0, (pagina - 1) * tamanho_pagina)
    query = f"""
        SELECT *, COUNT(*) OVER () AS _total FROM carteira_atual
        {where_sql}
        ORDER BY {ordenar_por} {ordenar_dir_sql} NULLS LAST, cliente ASC
        LIMIT %(limite)s OFFSET %(offset)s
    """
    df = read_df(query, {**params, "limite": tamanho_pagina, "offset": offset})

    if not df.empty:
        total = int(df["_total"].iloc[0])
        df = df.drop(columns=["_total"])
    elif offset > 0:
        # página além do fim: a janela não devolve linha nenhuma pra ler o total
        total = fetch_all(f"SELECT COUNT(*) AS total FROM carteira_atual {where_sql}", params)[0]["total"]
    else:
        total = 0
    return _pos_processar_carteira_df(df), total


def fetch_resumo_geral() -> dict:
    """Totais e contagem por faixa de TODA a carteira (ignora
    paginação/busca — é o resumo fixo que aparece no topo do dashboard).
    Uma consulta só: totais e contagem por faixa juntos (FILTER)."""
    clausula_exclusao, padroes_exclusao = filtro_exclusao()
    t = fetch_all(
        f"""
        SELECT
            COALESCE(SUM(valor_em_aberto), 0) AS total_aberto,
            COALESCE(SUM(limite_atual), 0) AS total_limite_atual,
            COALESCE(SUM(limite_sugerido), 0) AS total_limite_sugerido,
            COALESCE(AVG(score), 0) AS score_medio,
            COUNT(*) AS total_clientes,
            COUNT(*) FILTER (WHERE faixa = 'verde') AS verde,
            COUNT(*) FILTER (WHERE faixa = 'amarelo') AS amarelo,
            COUNT(*) FILTER (WHERE faixa = 'vermelho') AS vermelho
        FROM carteira_atual WHERE {clausula_exclusao}
        """,
        {"padroes_exclusao": padroes_exclusao},
    )[0]

    return {
        "total_aberto": float(t["total_aberto"] or 0),
        "total_limite_atual": float(t["total_limite_atual"] or 0),
        "total_limite_sugerido": float(t["total_limite_sugerido"] or 0),
        "score_medio": round(float(t["score_medio"] or 0), 1),
        "total_clientes": t["total_clientes"],
        "contagem_faixas": {"verde": t["verde"], "amarelo": t["amarelo"], "vermelho": t["vermelho"]},
    }


def fetch_maiores_expostos(limite: int = 5) -> pd.DataFrame:
    """Top clientes por valor em aberto — concentração de risco da carteira."""
    clausula_exclusao, padroes_exclusao = filtro_exclusao()
    where_sql = f"WHERE {clausula_exclusao} AND valor_em_aberto > 0"
    return read_df(
        f"""SELECT cliente, valor_em_aberto FROM carteira_atual {where_sql}
            ORDER BY valor_em_aberto DESC LIMIT %(l)s""",
        {"padroes_exclusao": padroes_exclusao, "l": limite},
    )


def fetch_carteira_cliente(cliente: str) -> pd.DataFrame:
    """Linha do cache pra um cliente específico (não aplica o filtro de
    exclusão — a tela de detalhe de um cliente deve abrir mesmo que ele
    tenha sido marcado como categoria contábil, pra permitir conferência)."""
    df = read_df("SELECT * FROM carteira_atual WHERE cliente = %(c)s", {"c": cliente})
    return _pos_processar_carteira_df(df)


def fetch_carteira_completa_df() -> pd.DataFrame:
    """Carteira inteira (sem paginação), já sem os excluídos — usada na
    exportação em Excel."""
    clausula_exclusao, padroes_exclusao = filtro_exclusao()
    where_sql = f"WHERE {clausula_exclusao}"
    df = read_df(
        f"SELECT * FROM carteira_atual {where_sql} ORDER BY score",
        {"padroes_exclusao": padroes_exclusao},
    )
    return _pos_processar_carteira_df(df)


def fetch_valor_em_aberto_df() -> pd.DataFrame:
    """Só cliente e valor_em_aberto (sem excluídos) — o que a concentração de
    risco precisa. fetch_carteira_completa_df traz as 25 colunas, inclusive
    o JSON de motivos de todo cliente, só pra o ranking usar duas."""
    clausula_exclusao, padroes_exclusao = filtro_exclusao()
    return read_df(
        f"SELECT cliente, valor_em_aberto FROM carteira_atual WHERE {clausula_exclusao}",
        {"padroes_exclusao": padroes_exclusao},
    )


def fetch_comparativo_carteira(cliente: str) -> dict | None:
    """
    Compara o cliente com o resto da carteira: percentil de atraso e de
    exposição, pra dar contexto ('esse atraso é normal ou tá entre os
    piores?'). Usa o cache (carteira_atual) e calcula tudo no banco numa
    consulta só — antes baixava a carteira inteira (25 colunas por cliente,
    inclusive o JSON de motivos) só pra contar quantos estavam abaixo do
    valor deste cliente.
    """
    clausula_exclusao, padroes_exclusao = filtro_exclusao()
    r = fetch_all(
        f"""
        WITH alvo AS (
            SELECT atraso_medio_dias AS atraso, valor_em_aberto AS aberto
            FROM carteira_atual WHERE cliente = %(cliente)s
        )
        SELECT
            COUNT(*) AS total,
            BOOL_OR(cliente = %(cliente)s) AS na_carteira,
            AVG(atraso_medio_dias) AS media_atraso,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY valor_em_aberto) AS mediana_exposicao,
            AVG((atraso_medio_dias <= (SELECT atraso FROM alvo))::int)
                FILTER (WHERE atraso_medio_dias IS NOT NULL) AS pct_atraso,
            AVG((valor_em_aberto <= (SELECT aberto FROM alvo))::int)
                FILTER (WHERE valor_em_aberto IS NOT NULL) AS pct_exposicao
        FROM carteira_atual WHERE {clausula_exclusao}
        """,
        {"cliente": cliente, "padroes_exclusao": padroes_exclusao},
    )[0]

    # cliente excluído da carteira (categoria contábil) ou inexistente: sem comparativo
    if not r["total"] or not r["na_carteira"]:
        return None

    def _pct(v):
        return None if v is None else round(float(v) * 100, 1)

    return {
        "total_clientes_carteira": int(r["total"]),
        "media_atraso_carteira": round(float(r["media_atraso"]), 1) if r["media_atraso"] is not None else None,
        "mediana_exposicao_carteira": round(float(r["mediana_exposicao"] or 0), 2),
        "percentil_atraso": _pct(r["pct_atraso"]),
        "percentil_exposicao": _pct(r["pct_exposicao"]),
    }
