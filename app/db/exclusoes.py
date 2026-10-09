"""Clientes excluídos da análise (categorias contábeis como AVARIA) e o filtro SQL correspondente."""
from __future__ import annotations

import pandas as pd

from app.core import filtros
from app.db.conexao import fetch_all, get_conn, read_df


def fetch_clientes_excluidos_df() -> pd.DataFrame:
    return read_df("SELECT * FROM clientes_excluidos ORDER BY cliente")


def fetch_clientes_excluidos_set() -> set[str]:
    return {r["cliente"] for r in fetch_all("SELECT cliente FROM clientes_excluidos")}


def adicionar_cliente_excluido(cliente: str, motivo: str | None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clientes_excluidos (cliente, motivo) VALUES (%s, %s)
                ON CONFLICT (cliente) DO UPDATE SET motivo = EXCLUDED.motivo
                """,
                (cliente, motivo),
            )
        conn.commit()


def remover_cliente_excluido(cliente: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM clientes_excluidos WHERE cliente = %s", (cliente,))
        conn.commit()


def filtro_exclusao(coluna: str = "cliente") -> tuple[str, list[str]]:
    """
    Trecho de SQL (pra usar num WHERE) que deixa de fora tanto os nomes
    excluídos manualmente (clientes_excluidos) quanto os que batem com as
    palavras-chave padrão de categoria contábil (ver filtros.py).

    Devolve (sql, padroes): os padrões de LIKE (ex.: '%AVARIA%') vão como
    parâmetro de verdade (%(padroes_exclusao)s), nunca embutidos como texto
    no SQL — um '%' literal solto no meio da query confunde o parser de
    parâmetros do psycopg2 quando outros parâmetros também são passados.
    """
    padroes = [f"%{p.upper()}%" for p in filtros.PALAVRAS_CHAVE_PADRAO]
    sql = (
        f"{coluna} NOT IN (SELECT cliente FROM clientes_excluidos) "
        f"AND NOT (UPPER({coluna}) LIKE ANY(%(padroes_exclusao)s))"
    )
    return sql, padroes
