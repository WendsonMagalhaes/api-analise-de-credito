"""Modelos de entrada (corpo das requisições) da API."""
from __future__ import annotations

from pydantic import BaseModel


class DecisaoInput(BaseModel):
    tipo: str  # "liberacao" | "negacao" | "revisao"
    valor_solicitado: float | None = None
    valor_aprovado: float | None = None
    prazo_dias: int | None = None
    score_no_momento: int | None = None
    faixa_no_momento: str | None = None
    analista: str | None = None
    observacao: str | None = None


class ClienteExcluidoInput(BaseModel):
    cliente: str
    motivo: str | None = None


class ConfigInput(BaseModel):
    valor: object
    descricao: str | None = None


class PeriodoSazonalInput(BaseModel):
    nome: str
    data_inicio: str
    data_fim: str


class GatilhoExternoInput(BaseModel):
    tipo: str  # "protesto" | "acao_judicial" | "negativacao" | "mudanca_cadastral"
    detalhes: dict | None = None


class WhatIfInput(BaseModel):
    valor_pedido: float


class DecisaoReajusteInput(BaseModel):
    aprovado_por: str | None = None
