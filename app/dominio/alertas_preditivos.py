"""
Job diário de alertas preditivos: dispara quando um título em aberto
atinge os percentuais configurados do PRÓPRIO prazo decorrido (padrão
50% e 85%), mais o vencimento em si (100%) — usando prazo_do_titulo de
cada boleto, nunca um número fixo de dias, pra um título de 8 dias e um
de 21 dias serem tratados com a mesma régua proporcional.

Idempotente: cada (título, tipo de alerta) só dispara uma vez — ver
alertas_prazo_disparados. Rodar esse job de novo no mesmo dia não gera
alerta duplicado.
"""
from __future__ import annotations

import pandas as pd

from app.dominio import aging
from app.db import config
from app import db

CHAVE_PERCENTUAIS = "alertas_preditivos_percentuais"
_PADRAO_PERCENTUAIS = [50, 85]


def _tipo_alerta(pct_decorrido: float, percentuais: list[int]) -> str | None:
    """Maior percentual configurado já atingido (ex.: título em 90% dispara
    '85pct', não '50pct' de novo) — ou 'vencimento' se já passou de 100%."""
    if pct_decorrido > 100:
        return "vencimento"
    atingidos = [p for p in sorted(percentuais) if pct_decorrido >= p]
    return f"{atingidos[-1]}pct" if atingidos else None


def _ja_disparados(chaves_e_tipos: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """Dos candidatos, quais (título, tipo de alerta) já foram disparados.
    Consulta só as chaves candidatas — antes trazia a tabela inteira de
    alertas já disparados (cresce todo dia) só pra comparar em Python."""
    if not chaves_e_tipos:
        return set()
    chaves = list({c for c, _ in chaves_e_tipos})
    rows = db.fetch_all(
        "SELECT chave_natural, tipo_alerta FROM alertas_prazo_disparados WHERE chave_natural = ANY(%(c)s)",
        {"c": chaves},
    )
    return {(r["chave_natural"], r["tipo_alerta"]) for r in rows}


def rodar_job_diario() -> pd.DataFrame:
    """
    Verifica todos os títulos da foto mais recente de abertos, calcula o
    aging de cada um, decide quais atingiram um novo patamar de alerta e
    grava os disparos novos (idempotente). Devolve os alertas NOVOS desta
    execução, ordenados priorizando clientes com histórico de atraso.
    """
    percentuais = config.get(CHAVE_PERCENTUAIS, _PADRAO_PERCENTUAIS)
    abertos = db.fetch_ultimo_snapshot_df()
    if abertos.empty:
        return pd.DataFrame()

    abertos = aging.anexar_aging(abertos)
    abertos["tipo_alerta"] = [
        _tipo_alerta(p, percentuais) if pd.notna(p) else None for p in abertos["pct_prazo_decorrido"]
    ]
    candidatos = abertos.dropna(subset=["tipo_alerta"])
    if candidatos.empty:
        return pd.DataFrame()

    ja_disparados = _ja_disparados(
        list(zip(candidatos["chave_natural"], candidatos["tipo_alerta"]))
    )
    ja = pd.Series(
        [(c, t) in ja_disparados for c, t in zip(candidatos["chave_natural"], candidatos["tipo_alerta"])],
        index=candidatos.index,
    )
    novos = candidatos[~ja]
    if novos.empty:
        return pd.DataFrame()

    # prioriza clientes com histórico de atraso (via carteira_atual, se já
    # calculada) — quem tem pct_pago_em_atraso maior aparece primeiro
    carteira = db.read_df("SELECT cliente, pct_pago_em_atraso FROM carteira_atual")
    novos = pd.merge(novos, carteira, on="cliente", how="left")
    novos["pct_pago_em_atraso"] = novos["pct_pago_em_atraso"].fillna(0)
    novos = novos.sort_values("pct_pago_em_atraso", ascending=False)

    rows = list(
        zip(
            novos["chave_natural"].tolist(),
            novos["cliente"].tolist(),
            novos["tipo_alerta"].tolist(),
            novos["pct_prazo_decorrido"].tolist(),
        )
    )
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            db.bulk_upsert(
                cur,
                "alertas_prazo_disparados",
                ["chave_natural", "cliente", "tipo_alerta", "pct_decorrido_no_disparo"],
                rows,
                conflito=["chave_natural", "tipo_alerta"],
            )
        conn.commit()

    return novos[
        ["cliente", "titulo", "venda_numero", "valor", "prazo_do_titulo", "pct_prazo_decorrido", "tipo_alerta"]
    ].reset_index(drop=True)


def fetch_historico(limite: int = 100) -> pd.DataFrame:
    return db.read_df(
        """SELECT chave_natural, cliente, tipo_alerta, pct_decorrido_no_disparo, disparado_em
           FROM alertas_prazo_disparados ORDER BY disparado_em DESC LIMIT %(l)s""",
        {"l": limite},
    )
