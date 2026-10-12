"""Limite de tentativas de login por janela de tempo.

Guardado no PostgreSQL (e não em memória), porque a API roda em instâncias
separadas na Vercel e cada uma enxergaria só a sua parte da contagem.

A cada tentativa contam duas chaves:
  * email:<e-mail>  -> protege uma conta contra adivinhação de senha;
  * ip:<ip>         -> protege contra varredura de muitas contas. Só é usada
                       quando o IP veio do servidor do front com o segredo
                       compartilhado (ver api/auth.py); sem isso, o IP seria o
                       do próprio servidor do front e bloquearia todo mundo.
Acertar a senha zera só a chave do e-mail.
"""
from __future__ import annotations

import threading

from app.db.conexao import get_conn

JANELA_S = 15 * 60
MAX_POR_EMAIL = 10
MAX_POR_IP = 50

_tabela_ok = False
_trava = threading.Lock()


def _garantir_tabela() -> None:
    global _tabela_ok
    if _tabela_ok:
        return
    with _trava:
        if _tabela_ok:
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS limite_tentativas_login (
                        chave TEXT PRIMARY KEY,
                        janela_inicio TIMESTAMPTZ NOT NULL,
                        tentativas INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
            conn.commit()
        _tabela_ok = True


def _registrar(chave: str) -> int:
    """Conta uma tentativa na janela atual e devolve o total dessa janela.
    Tudo numa instrução só (atômica), então duas tentativas simultâneas não se perdem."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO limite_tentativas_login AS t (chave, janela_inicio, tentativas)
                VALUES (%(k)s, NOW(), 1)
                ON CONFLICT (chave) DO UPDATE SET
                    janela_inicio = CASE
                        WHEN t.janela_inicio < NOW() - make_interval(secs => %(j)s) THEN NOW()
                        ELSE t.janela_inicio END,
                    tentativas = CASE
                        WHEN t.janela_inicio < NOW() - make_interval(secs => %(j)s) THEN 1
                        ELSE t.tentativas + 1 END
                RETURNING tentativas
                """,
                {"k": chave, "j": JANELA_S},
            )
            total = cur.fetchone()["tentativas"]
        conn.commit()
    return total


def verificar(email: str, ip: str | None) -> int | None:
    """Conta a tentativa. Devolve os segundos de espera se passou do limite, ou None."""
    _garantir_tabela()
    if _registrar(f"email:{email}") > MAX_POR_EMAIL:
        return JANELA_S
    if ip and _registrar(f"ip:{ip}") > MAX_POR_IP:
        return JANELA_S
    return None


def sucesso(email: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM limite_tentativas_login WHERE chave = %(k)s", {"k": f"email:{email}"})
        conn.commit()
