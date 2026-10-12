"""Resolve o código opaco da URL para o nome do cliente."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core import cache
from app.core.codigo_cliente import codigo_de
from app.db.conexao import fetch_all

router = APIRouter()


@cache.ttl_cache(300)
def _mapa_codigos() -> dict[str, str]:
    linhas = fetch_all("SELECT DISTINCT cliente FROM carteira_atual", {})
    return {codigo_de(l["cliente"]): l["cliente"] for l in linhas}


@router.get("/api/clientes-por-codigo/{codigo}")
def cliente_por_codigo(codigo: str):
    nome = _mapa_codigos().get(codigo)
    if not nome:
        raise HTTPException(404, "Cliente não encontrado")
    return {"cliente": nome}
