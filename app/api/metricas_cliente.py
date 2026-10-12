"""Métricas de UM cliente no período escolhido (mês atual | 6 meses | tudo)."""
from __future__ import annotations

from fastapi import APIRouter

from app.core import cache, periodo as periodo_mod
from app.core.serializacao import clean_json
from app.db import metricas

router = APIRouter()


@router.get("/api/clientes/{cliente}/metricas")
@cache.ttl_cache(60)
def metricas_cliente(cliente: str, periodo: str = "tudo"):
    p = periodo_mod.normalizar(periodo)
    linhas = clean_json(metricas.fetch_metricas_clientes([cliente], periodo_mod.data_inicio(p)))
    linha = linhas[0] if linhas else {}
    return {
        "periodo": p,
        "maior_compra": linha.get("maior_compra"),
        "maior_atraso_hoje": linha.get("maior_atraso_hoje"),
    }
