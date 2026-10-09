"""Recálculo da carteira (score, classes, tolerância, recomendação, reanálise) e montagem do detalhe de um cliente."""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
import pandas as pd

from app import db
from app.core.serializacao import clean_json
from app.core.telemetria import Etapas
from app.dominio import classificacao, reanalise, recomendacao, scoring, tolerancia, velocidade


def recalcular_e_salvar_carteira() -> pd.DataFrame:
    """
    Recalcula o score de todos os clientes (histórico completo de
    pagamentos + última foto de abertos + limite atual cadastrado) e
    atualiza tanto o cache que o dashboard lê (carteira_atual) quanto o
    snapshot do dia usado pelos alertas de mudança de faixa. Chamado
    depois de cada upload e pelo recálculo manual.

    Também recalcula, na mesma passada, as funcionalidades novas que
    dependem do score/exposição de cada cliente: velocidade de pagamento
    (histórico), classificação A-E (score duplo), tolerância/valor
    máximo liberável, motor de recomendação e agenda de reanálise. Tudo
    isso é derivado do MESMO score_df já calculado.

    Estrutura (por desempenho, com o banco remoto no Neon):
      1) LEITURA: 3 consultas em paralelo.
      2) CÁLCULO: tudo em memória, sem tocar no banco.
      3) GRAVAÇÃO: todas as tabelas numa única transação, cada uma em lote
         (COPY). Antes eram várias transações POR CLIENTE (agendar reanálise,
         evento de tolerância, contagem de usos, gatilhos...) — milhares de
         idas e voltas de rede — e uma falha no meio deixava os dados pela
         metade. Agora é tudo ou nada.
    """
    et = Etapas("recálculo da carteira")
    hoje = date.today()

    pagamentos_df, abertos_df, limite_atual_df = db.run_parallel(
        db.fetch_pagamentos_df, db.fetch_ultimo_snapshot_df, db.fetch_limite_atual_df
    )
    et.marca("leitura")

    score_df = scoring.calcular_score_clientes(pagamentos_df, abertos_df, limite_atual_df)
    et.marca("score")

    # --- velocidade de pagamento (histórico, ver velocidade.py) ---
    pagamentos_com_indice = velocidade.calcular_indice_por_titulo(pagamentos_df)
    medias_velocidade = velocidade.media_movel_por_cliente(pagamentos_com_indice)

    # --- classificação A-E (score duplo), separada da faixa verde/amarelo/vermelho ---
    score_df = classificacao.classificar_carteira(score_df, medias_velocidade, hoje)
    et.marca("velocidade+classes")

    # capturado ANTES de gravar o snapshot de hoje, pra detectar queda de
    # classe corretamente mesmo se o recálculo rodar 2x no mesmo dia.
    # Uma consulta só pra carteira inteira (não uma por cliente).
    classes_anteriores = classificacao.fetch_classes_anteriores(
        score_df["cliente"].tolist(), hoje
    )
    et.marca("classes_anteriores")

    valor_total_carteira = float(score_df["valor_em_aberto"].fillna(0).sum())

    # --- tolerância, recomendação e agenda de reanálise, linha a linha (só memória) ---
    recomendacoes, regras = [], []
    eventos_tolerancia, agenda, itens_gatilho = [], [], []
    for r in score_df.to_dict("records"):
        classe = r.get("classe_risco_5")
        limite_atual = r.get("limite_atual")
        valor_em_aberto = float(r.get("valor_em_aberto") or 0)

        calculo_tolerancia = None
        if limite_atual is not None and pd.notna(limite_atual) and classe:
            calculo_tolerancia = tolerancia.calcular_valor_maximo_liberado(
                float(limite_atual), classe, r.get("atraso_medio_dias"), valor_em_aberto, valor_total_carteira
            )
            # auditoria: toda vez que o saldo passa do limite cadastrado
            if valor_em_aberto > float(limite_atual):
                eventos_tolerancia.append(
                    {
                        "cliente": r["cliente"],
                        "data_captura": hoje,
                        "classe": classe,
                        "limite_atual": float(limite_atual),
                        "calculo": calculo_tolerancia,
                        "valor_em_aberto": valor_em_aberto,
                    }
                )

        rec = recomendacao.recomendar(
            classe=classe,
            dias_vencido_max=r.get("dias_vencido_max") or 0,
            valor_em_aberto=valor_em_aberto,
            limite_atual=float(limite_atual) if pd.notna(limite_atual) else None,
            valor_maximo_liberado=(calculo_tolerancia or {}).get("valor_maximo_liberado"),
            margem_limite_atual=r.get("margem_limite_atual"),
        )
        recomendacoes.append(rec["recomendacao"])
        regras.append(rec["regra"])

        if classe:
            agenda.append((r["cliente"], classe))
            # gatilhos por evento (uso excessivo de tolerância, queda de classe)
            itens_gatilho.append((r["cliente"], classe, classes_anteriores.get(r["cliente"])))

    score_df["recomendacao_acao"] = recomendacoes
    score_df["regra_recomendacao"] = regras
    et.marca("regras")

    # --- gravação: tudo numa transação só ---
    with db.get_conn() as conn:
        db.salvar_score_snapshot(score_df, hoje, conn=conn)
        velocidade.salvar_snapshot(medias_velocidade, hoje, conn=conn)
        classificacao.salvar_snapshot(score_df, hoje, conn=conn)
        tolerancia.registrar_eventos_em_lote(eventos_tolerancia, conn=conn)
        reanalise.agendar_em_lote(agenda, conn=conn, hoje=hoje)
        # depois dos eventos de tolerância: a contagem de usos do trimestre
        # precisa enxergar o evento de hoje (mesma transação)
        reanalise.verificar_gatilhos_em_lote(itens_gatilho, conn)
        db.salvar_carteira_atual(score_df, conn=conn)
        conn.commit()
    et.marca("gravação")
    et.fim()
    return score_df


def montar_detalhe_cliente(cliente: str) -> dict:
    hist, aberto_cli, resumo_df, comparativo = db.run_parallel(
        lambda: db.fetch_pagamentos_cliente_df(cliente),
        lambda: db.fetch_aberto_cliente_df(cliente),
        lambda: db.fetch_carteira_cliente(cliente),
        lambda: db.fetch_comparativo_carteira(cliente),
    )

    if hist.empty and aberto_cli.empty:
        raise HTTPException(404, "Cliente não encontrado")

    return {
        "cliente": cliente,
        "resumo": clean_json(resumo_df)[0] if not resumo_df.empty else None,
        "comparativo": comparativo,
        "historico_pagamentos": clean_json(hist),
        "titulos_em_aberto": clean_json(aberto_cli),
    }
