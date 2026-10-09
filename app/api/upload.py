"""Envio dos relatórios do ERP (títulos pagos, em aberto, limite de crédito)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import db
from app.core.telemetria import Etapas
from app.ingestao.parser import parse_relatorio
from app.servicos.carteira import recalcular_e_salvar_carteira

router = APIRouter()


@router.post("/api/upload")
def upload(files: list[UploadFile] = File(...)):
    """
    Recebe os arquivos exportados do ERP: Contas a Receber (aberto e/ou
    pago) e, opcionalmente, o relatório de limite de crédito atual dos
    clientes. Detecta sozinho o tipo de cada arquivo e grava no
    histórico, ignorando duplicatas de dias anteriores.
    """
    # Rota SÍNCRONA de propósito: o FastAPI roda em thread separada. Antes era
    # `async def` fazendo parse (CPU) e gravação (rede) bloqueantes direto no
    # event loop — enquanto um upload rodava, NENHUMA outra requisição (nem o
    # dashboard) era atendida.
    et = Etapas("upload")
    resultado = {}
    for f in files:
        content = f.file.read()
        try:
            tipo, df = parse_relatorio(content, filename=f.filename or "")
        except Exception as e:
            raise HTTPException(400, f"Erro ao processar {f.filename}: {e}")
        et.marca(f"parse[{f.filename}]")

        if tipo == "pago":
            stats = db.upsert_pagamentos(df)
            resultado[f.filename] = {"tipo": "pago", **stats}
        elif tipo == "limite":
            stats = db.upsert_limite_atual(df)
            resultado[f.filename] = {"tipo": "limite", **stats}
        else:
            stats = db.upsert_abertos(df, data_captura=date.today())
            resultado[f.filename] = {"tipo": "aberto", **stats}
        et.marca(f"gravação[{f.filename}]")

    # recalcula e atualiza o cache do dashboard + o snapshot do dia (usado
    # pelos alertas de mudança de faixa) — ver recalcular_e_salvar_carteira
    recalcular_e_salvar_carteira()
    et.marca("recálculo")
    et.fim()

    return resultado
