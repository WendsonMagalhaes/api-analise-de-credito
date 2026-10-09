"""
Camada de acesso à tabela `configuracoes` (ver migrations.py, 0001).

Toda regra nova (prazos permitidos, percentuais de tolerância, tetos de
reajuste, intervalos de reanálise, limiar de concentração de carteira
etc.) lê o valor daqui em vez de ter a constante espalhada pelo código —
o analista ajusta em /configuracoes sem precisar de deploy.

Cache simples em memória (por processo): configuração muda raramente,
não vale ir ao banco a cada linha de um DataFrame de 5 mil títulos.
Quem grava uma config nova já atualiza o cache do próprio processo;
outros workers/processos (ex.: um segundo worker do uvicorn) só veem a
mudança depois de reiniciar ou de chamar invalidar_cache().
"""
from __future__ import annotations

from psycopg2.extras import Json

from app.db.conexao import get_conn

_CACHE: dict = {}


def get(chave: str, default=None):
    if chave in _CACHE:
        return _CACHE[chave]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT valor FROM configuracoes WHERE chave = %(c)s", {"c": chave})
            row = cur.fetchone()
    valor = row["valor"] if row else default
    _CACHE[chave] = valor
    return valor


def set(chave: str, valor, descricao: str | None = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO configuracoes (chave, valor, descricao)
                VALUES (%(c)s, %(v)s, %(d)s)
                ON CONFLICT (chave) DO UPDATE SET
                    valor = EXCLUDED.valor,
                    descricao = COALESCE(EXCLUDED.descricao, configuracoes.descricao),
                    atualizado_em = NOW()
                """,
                {"c": chave, "v": Json(valor), "d": descricao},
            )
        conn.commit()
    _CACHE[chave] = valor


def listar() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chave, valor, descricao, atualizado_em FROM configuracoes ORDER BY chave"
            )
            return cur.fetchall()


def invalidar_cache() -> None:
    _CACHE.clear()
