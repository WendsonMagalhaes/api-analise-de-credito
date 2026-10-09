"""Parâmetros do sistema, clientes excluídos e períodos sazonais."""
from __future__ import annotations

from fastapi import APIRouter

from app import db
from app.core.serializacao import clean_json
from app.db import config as cfg
from app.dominio import sazonalidade
from app.schemas import ClienteExcluidoInput, ConfigInput, PeriodoSazonalInput

router = APIRouter()


@router.get("/api/config/clientes-excluidos")
def listar_clientes_excluidos():
    return clean_json(db.fetch_clientes_excluidos_df())


@router.post("/api/config/clientes-excluidos")
def adicionar_cliente_excluido(payload: ClienteExcluidoInput):
    db.adicionar_cliente_excluido(payload.cliente.strip(), payload.motivo)
    return {"ok": True}


@router.delete("/api/config/clientes-excluidos/{cliente}")
def remover_cliente_excluido(cliente: str):
    db.remover_cliente_excluido(cliente)
    return {"ok": True}


@router.get("/api/config")
def listar_configuracoes():
    return cfg.listar()


@router.put("/api/config/{chave}")
def atualizar_configuracao(chave: str, payload: ConfigInput):
    cfg.set(chave, payload.valor, payload.descricao)
    return {"ok": True}


@router.get("/api/config/periodos-sazonais")
def listar_periodos_sazonais():
    return clean_json(sazonalidade.fetch_periodos())


@router.post("/api/config/periodos-sazonais")
def criar_periodo_sazonal(payload: PeriodoSazonalInput):
    novo_id = sazonalidade.cadastrar_periodo(payload.nome, payload.data_inicio, payload.data_fim)
    return {"id": novo_id}


@router.delete("/api/config/periodos-sazonais/{periodo_id}")
def deletar_periodo_sazonal(periodo_id: int):
    sazonalidade.remover_periodo(periodo_id)
    return {"ok": True}
