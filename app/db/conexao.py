"""Conexão com o PostgreSQL: pool, leitura (read_df/fetch_all), leituras em paralelo, escrita em massa (COPY) e criação do schema."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import csv
from datetime import date
import io
import itertools
import json
import os
import threading
import time

import pandas as pd
import psycopg2
import psycopg2.extensions
from psycopg2.extras import RealDictCursor
import psycopg2.pool
from sqlalchemy import create_engine

from app.db import migrations
from app.db.schema import SCHEMA


DATABASE_URL = os.environ.get("DATABASE_URL")


# Neon suspende conexões ociosas (~5 min). Descartamos conexões mais velhas
# que isso ANTES de usar, em vez de descobrir que morreram no meio de uma
# requisição (erro 500 na cara do usuário).
CONN_MAX_AGE_S = int(os.environ.get("DB_CONN_MAX_AGE", "240"))


POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))


_engine = None


def get_engine():
    """Engine SQLAlchemy — mantido só por compatibilidade com módulos que
    ainda chamam pd.read_sql_query(..., db.get_engine()). Código novo deve
    usar db.read_df(). Em AUTOCOMMIT: sem BEGIN/ROLLBACK extras a cada leitura
    (cada um é uma ida e volta de rede com o banco remoto)."""
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL não está definida. Configure a connection string do "
                "Neon (ver backend/.env.example)."
            )
        _engine = create_engine(
            DATABASE_URL,
            isolation_level="AUTOCOMMIT",
            pool_size=5,
            max_overflow=5,
            pool_recycle=CONN_MAX_AGE_S,
            connect_args={
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 3,
                "connect_timeout": 10,
            },
        )
    return _engine


_pool: psycopg2.pool.ThreadedConnectionPool | None = None


# ThreadedConnectionPool lança PoolError na hora quando as 10 conexões estão em
# uso (ex.: o dashboard dispara 4 requisições em paralelo e cada uma pode abrir
# mais de uma consulta). O semáforo faz a requisição ESPERAR uma vaga.
_vagas = threading.BoundedSemaphore(POOL_MAX)


_nascimento: dict[int, float] = {}


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """
    Pool de conexões (reaproveita conexões em vez de abrir uma nova a cada
    consulta — abrir conexão com o Neon custa TLS + autenticação, centenas de
    ms). ThreadedConnectionPool é seguro entre threads, que é como o FastAPI
    roda rotas síncronas.
    """
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL não está definida. Configure a connection string do "
                "Neon (ver backend/.env.example)."
            )
        _pool = psycopg2.pool.ThreadedConnectionPool(
            1,
            POOL_MAX,
            DATABASE_URL,
            cursor_factory=RealDictCursor,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
            connect_timeout=10,
        )
    return _pool


def _emprestar_conexao():
    pool = _get_pool()
    for _ in range(POOL_MAX + 1):
        conn = pool.getconn()
        nasceu = _nascimento.setdefault(id(conn), time.monotonic())
        if conn.closed or (time.monotonic() - nasceu) > CONN_MAX_AGE_S:
            _nascimento.pop(id(conn), None)
            pool.putconn(conn, close=True)
            continue
        return conn
    return pool.getconn()


@contextmanager
def get_conn(autocommit: bool = False):
    """
    Empresta uma conexão do pool e devolve no final.

    autocommit=True é para LEITURAS: o psycopg2 em modo normal manda BEGIN
    (uma ida e volta), depois a query, depois COMMIT/ROLLBACK (outra). Com o
    banco remoto isso triplica a latência de cada SELECT. Escritas continuam
    no modo normal (transação + conn.commit() explícito).

    Se algo der errado dentro do `with`, desfaz a transação em aberto antes
    de devolver — senão a conexão voltaria pro pool numa transação pendurada.
    """
    _vagas.acquire()
    conn = None
    try:
        conn = _emprestar_conexao()
        if autocommit:
            conn.autocommit = True
        yield conn
    except Exception:
        if conn is not None and not conn.closed and not conn.autocommit:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        try:
            if conn is not None:
                quebrada = conn.closed
                if not quebrada and conn.autocommit:
                    conn.autocommit = False
                if quebrada:
                    _nascimento.pop(id(conn), None)
                _get_pool().putconn(conn, close=quebrada)
        finally:
            _vagas.release()


@contextmanager
def conn_ou_nova(conn=None):
    """Usa a conexão recebida (sem commit — quem chamou decide, o que permite
    várias gravações numa transação só) ou abre uma nova e já dá commit."""
    if conn is not None:
        yield conn
    else:
        with get_conn() as nova:
            yield nova
            nova.commit()


def read_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """SELECT -> DataFrame usando o pool (uma ida e volta, autocommit).
    Mesma conversão do pd.read_sql_query (Decimal -> float). Tenta de novo
    uma vez com conexão nova se a primeira estava morta (Neon suspendeu)."""
    for tentativa in (1, 2):
        try:
            with get_conn(autocommit=True) as conn:
                with conn.cursor(cursor_factory=psycopg2.extensions.cursor) as cur:
                    cur.execute(sql, params)
                    colunas = [d.name for d in cur.description]
                    linhas = cur.fetchall()
            return pd.DataFrame.from_records(linhas, columns=colunas, coerce_float=True)
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            if tentativa == 2:
                raise


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    """SELECT -> lista de dicts (uma ida e volta, autocommit)."""
    for tentativa in (1, 2):
        try:
            with get_conn(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            if tentativa == 2:
                raise


def run_parallel(*funcoes):
    """Roda várias leituras independentes ao mesmo tempo (cada uma pega a
    sua conexão) — o tempo total vira o da mais lenta, não a soma."""
    if len(funcoes) == 1:
        return [funcoes[0]()]
    with ThreadPoolExecutor(max_workers=len(funcoes)) as ex:
        futuros = [ex.submit(f) for f in funcoes]
        return [f.result() for f in futuros]


_seq_tmp = itertools.count(1)


def _valor_copy(v) -> str:
    """Valor -> texto do COPY (CSV). NULL = \\N (NaN/NaT/None do pandas viram NULL)."""
    if v is None or v is pd.NaT or v is pd.NA:
        return "\\N"
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, float):
        return "\\N" if v != v else repr(v)
    if isinstance(v, bool):
        return "t" if v else "f"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def bulk_upsert(
    cur,
    tabela: str,
    colunas: list[str],
    linhas: list[tuple],
    conflito: list[str] | None = None,
    atualizar: list[str] | None = None,
    extra_set: str | None = None,
    depois: str | None = None,
) -> int:
    """
    Grava N linhas com uma quantidade FIXA de idas e voltas ao banco (COPY ->
    tabela temporária -> INSERT ... SELECT), em vez de N ou N/100 (execute_values
    padrão manda páginas de 100 linhas: 45 mil linhas = 455 idas e voltas).

      conflito=None                  -> INSERT simples
      conflito=[...], atualizar=None -> ON CONFLICT DO NOTHING
      conflito=[...], atualizar=[..] -> ON CONFLICT DO UPDATE SET col=EXCLUDED.col
      extra_set="atualizado_em = NOW()" -> acrescentado ao DO UPDATE
      depois="UPDATE ... FROM {tmp} ..." -> SQL extra rodado logo após o INSERT,
                                     com {tmp} = nome da tabela temporária
                                     (o rowcount devolvido continua sendo o do INSERT)

    Devolve quantas linhas foram realmente inseridas/atualizadas (rowcount).
    Roda dentro da transação da conexão do `cur` — quem chama dá o commit.
    """
    if not linhas:
        return 0

    if conflito and atualizar is not None:
        # DO UPDATE não aceita a mesma chave duas vezes no mesmo comando:
        # mantém a última ocorrência de cada chave.
        idx = [colunas.index(c) for c in conflito]
        linhas = list({tuple(l[i] for i in idx): l for l in linhas}.values())

    tmp = f"_tmp_{tabela}_{next(_seq_tmp)}"
    cols_sql = ", ".join(colunas)
    cur.execute(
        f"CREATE TEMP TABLE {tmp} ON COMMIT DROP AS SELECT {cols_sql} FROM {tabela} WITH NO DATA"
    )

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for l in linhas:
        w.writerow([_valor_copy(v) for v in l])
    buf.seek(0)
    cur.copy_expert(f"COPY {tmp} ({cols_sql}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)

    sql = f"INSERT INTO {tabela} ({cols_sql}) SELECT {cols_sql} FROM {tmp}"
    if conflito:
        alvo = ", ".join(conflito)
        if atualizar is None:
            sql += f" ON CONFLICT ({alvo}) DO NOTHING"
        else:
            sets = [f"{c} = EXCLUDED.{c}" for c in atualizar]
            if extra_set:
                sets.append(extra_set)
            sql += f" ON CONFLICT ({alvo}) DO UPDATE SET " + ", ".join(sets)
    cur.execute(sql)
    inseridos = cur.rowcount
    if depois:
        cur.execute(depois.format(tmp=tmp))
    return inseridos  # a tabela temporária some sozinha no commit (ON COMMIT DROP)


def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
        # Migrations aditivas das funcionalidades novas (prazo variável,
        # aging, velocidade, classificação A-E, tolerância, reajuste,
        # reanálise, sazonalidade etc.) — ver migrations.py. Idempotente:
        # cada uma só roda uma vez, controlada por schema_migrations.
        migrations.aplicar_migrations(conn)
