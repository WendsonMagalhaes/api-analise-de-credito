"""Tabela `usuarios` (ver migration 0013). Todas as consultas usam parâmetros
(%(nome)s) — nenhum valor vindo de fora é concatenado no SQL."""
from __future__ import annotations

from psycopg2 import errors as pg_errors

from app.db.conexao import get_conn

MAX_TENTATIVAS = 5
BLOQUEIO_MINUTOS = 15

_PUBLICAS = "id, email, nome, papel, ativo, criado_em, ultimo_login"


def buscar_por_email(email: str) -> dict | None:
    """Para o login: traz o hash e se a conta está bloqueada neste instante."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, nome, senha_hash, papel, ativo, versao_token,
                       (bloqueado_ate IS NOT NULL AND bloqueado_ate > NOW()) AS bloqueado
                FROM usuarios
                WHERE LOWER(email) = %(e)s
                """,
                {"e": email.strip().lower()},
            )
            return cur.fetchone()


def buscar_por_id(uid: int) -> dict | None:
    """Para validar cada requisição: sem o hash da senha."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, nome, papel, ativo, versao_token FROM usuarios WHERE id = %(i)s",
                {"i": uid},
            )
            return cur.fetchone()


def registrar_falha(uid: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE usuarios SET
                    tentativas_falhas = tentativas_falhas + 1,
                    bloqueado_ate = CASE
                        WHEN tentativas_falhas + 1 >= %(max)s
                        THEN NOW() + make_interval(mins => %(min)s)
                        ELSE bloqueado_ate END
                WHERE id = %(i)s
                """,
                {"i": uid, "max": MAX_TENTATIVAS, "min": BLOQUEIO_MINUTOS},
            )
        conn.commit()


def registrar_sucesso(uid: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL,
                                    ultimo_login = NOW()
                WHERE id = %(i)s
                """,
                {"i": uid},
            )
        conn.commit()


# ---- usadas só pelo usuarios_cli.py (não há rota HTTP para gerir usuários) ----
def listar() -> list[dict]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_PUBLICAS} FROM usuarios ORDER BY id")  # _PUBLICAS é constante
            return cur.fetchall()


def criar(email: str, nome: str, senha_hash: str, papel: str) -> dict:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO usuarios (email, nome, senha_hash, papel)
                    VALUES (%(e)s, %(n)s, %(h)s, %(p)s)
                    RETURNING {_PUBLICAS}
                    """,
                    {"e": email.strip().lower(), "n": nome.strip(), "h": senha_hash, "p": papel},
                )
                row = cur.fetchone()
            conn.commit()
            return row
    except pg_errors.UniqueViolation:
        raise ValueError("Já existe um usuário com esse e-mail.")


def atualizar(
    email: str,
    *,
    papel: str | None = None,
    ativo: bool | None = None,
    senha_hash: str | None = None,
) -> dict | None:
    """Altera papel/ativo/senha. Qualquer mudança incrementa `versao_token`,
    o que invalida na hora todos os tokens já emitidos para o usuário. Trocar a
    senha também destrava a conta."""
    bump = 1 if (papel is not None or ativo is not None or senha_hash is not None) else 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE usuarios SET
                    papel = COALESCE(%(p)s, papel),
                    ativo = COALESCE(%(a)s, ativo),
                    senha_hash = COALESCE(%(h)s, senha_hash),
                    versao_token = versao_token + %(bump)s,
                    tentativas_falhas = CASE WHEN %(h)s IS NOT NULL THEN 0 ELSE tentativas_falhas END,
                    bloqueado_ate = CASE WHEN %(h)s IS NOT NULL THEN NULL ELSE bloqueado_ate END
                WHERE LOWER(email) = %(e)s
                RETURNING {_PUBLICAS}
                """,
                {"e": email.strip().lower(), "p": papel, "a": ativo, "h": senha_hash, "bump": bump},
            )
            row = cur.fetchone()
        conn.commit()
        return row


# ---- gestão de usuários pela API (administração) ----
def atualizar_por_id(
    uid: int,
    *,
    nome: str | None = None,
    papel: str | None = None,
    ativo: bool | None = None,
    senha_hash: str | None = None,
) -> dict | None:
    """Altera nome, papel, ativo e/ou senha pelo id. Mudança de papel, status ou senha
    incrementa `versao_token` (invalida os tokens já emitidos). Trocar a senha destrava a conta.
    Mudar só o nome não derruba a sessão."""
    bump = 1 if (papel is not None or ativo is not None or senha_hash is not None) else 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE usuarios SET
                    nome = COALESCE(%(n)s, nome),
                    papel = COALESCE(%(p)s, papel),
                    ativo = COALESCE(%(a)s, ativo),
                    senha_hash = COALESCE(%(h)s, senha_hash),
                    versao_token = versao_token + %(bump)s,
                    tentativas_falhas = CASE WHEN %(h)s IS NOT NULL THEN 0 ELSE tentativas_falhas END,
                    bloqueado_ate = CASE WHEN %(h)s IS NOT NULL THEN NULL ELSE bloqueado_ate END
                WHERE id = %(i)s
                RETURNING {_PUBLICAS}
                """,
                {"i": uid, "n": nome, "p": papel, "a": ativo, "h": senha_hash, "bump": bump},
            )
            row = cur.fetchone()
        conn.commit()
    return row


def contar_admins_ativos() -> int:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM usuarios WHERE papel = 'admin' AND ativo")
            return cur.fetchone()["n"]
