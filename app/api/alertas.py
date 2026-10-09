"""Alertas de mudança de faixa e alertas preditivos de prazo."""
from __future__ import annotations

from fastapi import APIRouter
import pandas as pd

from app import db
from app.core import cache, filtros
from app.core.serializacao import clean_json
from app.dominio import alertas_preditivos

router = APIRouter()


@router.get("/api/alertas")
@cache.ttl_cache(60)
def alertas():
    """
    Clientes que mudaram de faixa de risco (verde/amarelo/vermelho) entre as
    duas últimas datas em que relatórios foram importados — pra avisar
    proativamente quando alguém piora (ou melhora) antes que vire problema.
    """
    datas = db.fetch_ultimas_duas_datas_snapshot()
    if len(datas) < 2:
        return {
            "disponivel": False,
            "mensagem": (
                "Ainda não há duas capturas de score pra comparar. Os alertas "
                "aparecem a partir da segunda vez que você importar relatórios "
                "em dias diferentes."
            ),
            "alertas": [],
        }

    data_atual, data_anterior = datas[0], datas[1]
    snap_atual, snap_anterior, excluidos = db.run_parallel(
        lambda: db.fetch_score_snapshot_por_data(data_atual),
        lambda: db.fetch_score_snapshot_por_data(data_anterior),
        db.fetch_clientes_excluidos_set,
    )
    atual = filtros.filtrar_clientes_df(snap_atual, excluidos)
    anterior = filtros.filtrar_clientes_df(snap_anterior, excluidos)

    if atual.empty or anterior.empty:
        return {
            "disponivel": True,
            "data_atual": data_atual.isoformat(),
            "data_anterior": data_anterior.isoformat(),
            "alertas": [],
        }

    ordem_faixa = {"vermelho": 0, "amarelo": 1, "verde": 2}
    merged = pd.merge(
        atual[["cliente", "score", "faixa", "valor_em_aberto"]],
        anterior[["cliente", "score", "faixa"]],
        on="cliente",
        suffixes=("_atual", "_anterior"),
        how="inner",
    )
    merged["ordem_atual"] = merged["faixa_atual"].map(ordem_faixa)
    merged["ordem_anterior"] = merged["faixa_anterior"].map(ordem_faixa)
    mudou = merged[merged["ordem_atual"] != merged["ordem_anterior"]].copy()
    mudou["direcao"] = mudou.apply(
        lambda r: "piorou" if r["ordem_atual"] < r["ordem_anterior"] else "melhorou", axis=1
    )
    mudou = mudou.sort_values(["direcao", "score_atual"], ascending=[False, True])
    mudou = mudou.drop(columns=["ordem_atual", "ordem_anterior"])

    return {
        "disponivel": True,
        "data_atual": data_atual.isoformat(),
        "data_anterior": data_anterior.isoformat(),
        "alertas": clean_json(mudou),
    }


@router.post("/api/jobs/alertas-preditivos")
def rodar_alertas_preditivos():
    """Job diário — dispara alertas novos (idempotente) e devolve só os
    que acabaram de ser disparados nesta execução."""
    novos = alertas_preditivos.rodar_job_diario()
    return {"novos_alertas": clean_json(novos)}


@router.get("/api/alertas/preditivos")
def historico_alertas_preditivos(limite: int = 100):
    return clean_json(alertas_preditivos.fetch_historico(limite))
