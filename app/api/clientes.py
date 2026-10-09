"""Tudo que é de um cliente: detalhe, decisões, análise por IA, aging, velocidade, classificação, tolerância, reajustes, what-if e recomendação."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
import pandas as pd

from app import db
from app.core import cache
from app.core.serializacao import clean_json
from app.dominio import aging, classificacao, reajuste_limite, reanalise, tolerancia, velocidade, whatif
from app.integracoes import ia
from app.schemas import DecisaoInput, GatilhoExternoInput, WhatIfInput
from app.servicos.carteira import montar_detalhe_cliente

router = APIRouter()


@router.get("/api/clientes/{cliente}")
def detalhe_cliente(cliente: str):
    return montar_detalhe_cliente(cliente)


@router.get("/api/clientes/{cliente}/historico-score")
def historico_score_cliente(cliente: str):
    """Evolução do score do cliente ao longo do tempo, pra ver a tendência num gráfico."""
    return clean_json(db.fetch_historico_score_cliente(cliente))


@router.get("/api/clientes/{cliente}/decisoes")
def listar_decisoes_cliente(cliente: str):
    return clean_json(db.fetch_decisoes_cliente_df(cliente))


@router.post("/api/clientes/{cliente}/decisoes")
def registrar_decisao_cliente(cliente: str, decisao: DecisaoInput):
    """Registra uma decisão de crédito (liberação, negação ou revisão) para o cliente."""
    novo_id = db.registrar_decisao(
        cliente=cliente,
        tipo=decisao.tipo,
        valor_solicitado=decisao.valor_solicitado,
        valor_aprovado=decisao.valor_aprovado,
        prazo_dias=decisao.prazo_dias,
        score_no_momento=decisao.score_no_momento,
        faixa_no_momento=decisao.faixa_no_momento,
        analista=decisao.analista,
        observacao=decisao.observacao,
    )
    return {"id": novo_id}


@router.post("/api/clientes/{cliente}/analise-ia")
async def analise_ia_cliente(cliente: str):
    """
    Pede pra IA (Groq) uma leitura qualitativa do histórico do cliente,
    complementando o score numérico — um segundo ponto de vista antes de
    decidir. Sob demanda: só roda quando o analista pede na tela do
    cliente.
    """
    detalhe = await run_in_threadpool(montar_detalhe_cliente, cliente)
    decisoes = clean_json(await run_in_threadpool(db.fetch_decisoes_cliente_df, cliente))

    try:
        texto, modelo = await ia.gerar_analise(
            cliente=cliente,
            resumo=detalhe["resumo"],
            historico_pagamentos=detalhe["historico_pagamentos"],
            titulos_em_aberto=detalhe["titulos_em_aberto"],
            decisoes=decisoes,
        )
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    return {"analise": texto, "modelo": modelo}


@router.get("/api/decisoes")
@cache.ttl_cache(60)
def decisoes_recentes(limite: int = 50):
    """Últimas decisões de crédito registradas, de todos os clientes."""
    return clean_json(db.fetch_decisoes_recentes_df(limite))


@router.get("/api/clientes/{cliente}/aging")
def aging_cliente(cliente: str):
    abertos = aging.anexar_aging(db.fetch_aberto_cliente_df(cliente))
    return clean_json(abertos)


@router.get("/api/clientes/{cliente}/velocidade-pagamento")
def velocidade_pagamento_cliente(cliente: str):
    return clean_json(velocidade.fetch_historico_cliente(cliente))


@router.get("/api/clientes/{cliente}/classificacao")
def classificacao_cliente(cliente: str):
    return clean_json(classificacao.fetch_historico_cliente(cliente))


@router.get("/api/clientes/{cliente}/reajustes-limite")
def historico_reajustes_cliente(cliente: str):
    """Histórico completo (sugerido/aprovado/rejeitado) de reajustes de
    limite deste cliente — pra mostrar na tela de detalhe."""
    return clean_json(reajuste_limite.fetch_historico_cliente(cliente))


@router.get("/api/clientes/{cliente}/tolerancia")
def tolerancia_cliente(cliente: str):
    return clean_json(tolerancia.fetch_eventos_cliente(cliente))


@router.post("/api/clientes/{cliente}/reanalise/gatilho-externo")
def registrar_gatilho_externo(cliente: str, payload: GatilhoExternoInput):
    reanalise.registrar_gatilho_externo(cliente, payload.tipo, payload.detalhes)
    return {"ok": True}


@router.post("/api/clientes/{cliente}/simulacao/what-if")
def simulacao_what_if(cliente: str, payload: WhatIfInput):
    linha = db.fetch_carteira_cliente(cliente)
    if linha.empty:
        raise HTTPException(404, "Cliente não encontrado na carteira calculada.")
    r = linha.iloc[0]
    valor_total_carteira = float(db.fetch_resumo_geral()["total_aberto"])
    resultado = whatif.simular_novo_pedido(
        valor_pedido=payload.valor_pedido,
        limite_atual=float(r["limite_atual"]) if pd.notna(r.get("limite_atual")) else None,
        valor_em_aberto=float(r.get("valor_em_aberto") or 0),
        classe=r.get("classe_risco_5"),
        atraso_medio_dias=r.get("atraso_medio_dias"),
        valor_total_carteira=valor_total_carteira,
        score_composto=None,
    )
    return resultado


@router.get("/api/clientes/{cliente}/recomendacao")
def recomendacao_cliente(cliente: str):
    linha = db.fetch_carteira_cliente(cliente)
    if linha.empty:
        raise HTTPException(404, "Cliente não encontrado na carteira calculada.")
    r = linha.iloc[0]
    return {
        "classe_risco_5": r.get("classe_risco_5"),
        "score_comportamento": r.get("score_comportamento"),
        "score_exposicao": r.get("score_exposicao"),
        "recomendacao_acao": r.get("recomendacao_acao"),
        "regra_recomendacao": r.get("regra_recomendacao"),
    }
