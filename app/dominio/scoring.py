"""
Cálculo do score de crédito por cliente, do limite de crédito sugerido e das
razões que explicam o score, a partir do histórico de pagamentos e da
última foto dos títulos em aberto.

Indicadores por cliente:
  - qtd_titulos_pagos, valor_total_pago
  - atraso_medio_dias, atraso_maximo_dias
  - pct_pago_em_atraso   (títulos pagos após o vencimento)
  - pct_pago_muito_atraso (pagos com mais de 15 dias de atraso)
  - tendencia            ('melhorando' | 'estavel' | 'piorando') comparando
                          o atraso médio dos últimos 90 dias com os 90 dias
                          anteriores
  - valor_em_aberto, qtd_titulos_aberto (última foto)
  - dias_vencido_max     (maior atraso já vencido hoje entre os em aberto)
  - score (0-100) e faixa (verde/amarelo/vermelho)
  - capacidade_mensal    (estimativa do quanto o cliente costuma pagar por
                          mês — base do limite sugerido)
  - limite_sugerido      (quanto seria razoável esse cliente dever no total,
                          juntando o que já está em aberto — calculado a
                          partir da capacidade de pagamento dentro de UM
                          CICLO da política de cobrança (ver
                          PRAZO_POLITICA_BOLETO_DIAS), não de um mês
                          inteiro — None quando não há histórico de
                          pagamento suficiente)
  - margem_disponivel    (limite_sugerido - valor_em_aberto: positivo = tem
                          espaço pra liberar mais crédito; negativo = já
                          está acima do recomendado pra faixa de risco
                          atual — None junto com limite_sugerido)
  - limite_atual         (limite de crédito hoje cadastrado no ERP pro
                          cliente, vindo do relatório de limite — None se
                          esse relatório ainda não foi importado pra ele)
  - margem_limite_atual  (limite_atual - valor_em_aberto: quanto do limite
                          JÁ CADASTRADO ainda está livre pra usar — essa é
                          a resposta mais direta pra "posso liberar mais
                          crédito dentro do limite que ele já tem?")
  - recomendacao_limite  ('aumentar' | 'manter' | 'reduzir' | 'sem_dados')
                          compara limite_sugerido com limite_atual pra
                          apontar se vale a pena rever o limite cadastrado
  - prazo_politica_dias  (o PRAZO_POLITICA_BOLETO_DIAS usado no cálculo,
                          repetido em cada linha só pra a tela poder
                          mostrar de onde veio o número sem hardcode)
  - motivos              (lista de frases explicando o que pesou no score,
                          pra usar como justificativa na decisão de crédito)
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
from app.core.formatacao import fmt_brl, fmt_num

# Política de crédito: prazo padrão dos boletos, em dias (hoje: 21). É a
# base do limite sugerido — não faz sentido sugerir vários meses de
# exposição se a cobrança roda num ciclo curto. Ajustável sem mexer no
# código via variável de ambiente, caso a política mude.
PRAZO_POLITICA_BOLETO_DIAS = int(os.environ.get("PRAZO_POLITICA_BOLETO_DIAS", "21"))

# Quanto da capacidade de pagamento DENTRO DE UM CICLO da política (não do
# mês inteiro) vira limite sugerido, por faixa de risco. Cliente vermelho
# não é recomendado receber mais crédito. Também ajustável por variável de
# ambiente (ver backend/.env.example).
MULTIPLICADOR_FAIXA = {
    "verde": float(os.environ.get("MULTIPLICADOR_LIMITE_VERDE", "1.5")),
    "amarelo": float(os.environ.get("MULTIPLICADOR_LIMITE_AMARELO", "0.8")),
    "vermelho": float(os.environ.get("MULTIPLICADOR_LIMITE_VERMELHO", "0.0")),
}


def _atraso_dias(row) -> int:
    venc = pd.to_datetime(row["data_vencimento"])
    pag = pd.to_datetime(row["data_pagamento"])
    return (pag - venc).days


_COLUNAS_HISTORICO = [
    "cliente",
    "qtd_titulos_pagos",
    "valor_total_pago",
    "atraso_medio_dias",
    "atraso_maximo_dias",
    "pct_pago_em_atraso",
    "pct_pago_muito_atraso",
    "tendencia",
    "capacidade_mensal",
]


def _indicadores_historico(
    p: pd.DataFrame, hoje: pd.Timestamp, corte_recente: pd.Timestamp, corte_anterior: pd.Timestamp
) -> pd.DataFrame:
    """
    Indicadores de pagamento de TODOS os clientes de uma vez (groupby
    vetorizado). Antes era um loop `for cliente, grp in groupby(...)` que
    refazia ~12 operações do pandas por cliente — segundos de CPU numa
    carteira de milhares de clientes. Os números são os mesmos.

    capacidade_mensal (base do limite sugerido): prioriza os últimos 90 dias
    (soma / 3) se o cliente tem >= 2 pagamentos nesse período; senão cai pra
    média mensal de todo o histórico (mínimo de 1 mês).
    """
    chave = p["cliente"]
    g = p.groupby("cliente")

    r = pd.DataFrame(
        {
            "qtd_titulos_pagos": g.size(),
            "valor_total_pago": g["valor_pago"].sum(),
            "atraso_medio_dias": g["atraso_dias"].mean(),
            "atraso_maximo_dias": g["atraso_dias"].max(),
            "pct_pago_em_atraso": (p["atraso_dias"] > 0).groupby(chave).mean() * 100,
            "pct_pago_muito_atraso": (p["atraso_dias"] > 15).groupby(chave).mean() * 100,
        }
    )

    recentes = p["data_pagamento"] >= corte_recente
    anteriores = (p["data_pagamento"] < corte_recente) & (p["data_pagamento"] >= corte_anterior)
    n_rec = recentes.groupby(chave).sum()
    n_ant = anteriores.groupby(chave).sum()
    diff = p["atraso_dias"].where(recentes).groupby(chave).mean() - p["atraso_dias"].where(
        anteriores
    ).groupby(chave).mean()
    com_dados = (n_rec >= 3) & (n_ant >= 3)
    r["tendencia"] = np.select(
        [com_dados & (diff <= -2), com_dados & (diff >= 2), com_dados],
        ["melhorando", "piorando", "estavel"],
        default="sem_dados",
    )

    soma_recente = p["valor_pago"].where(recentes).groupby(chave).sum()
    meses_historico = ((hoje - g["data_pagamento"].min()).dt.days / 30).clip(lower=1.0).fillna(1.0)
    r["capacidade_mensal"] = np.where(
        n_rec >= 2, soma_recente / 3, r["valor_total_pago"] / meses_historico
    )

    r["valor_total_pago"] = r["valor_total_pago"].round(2)
    r["atraso_medio_dias"] = r["atraso_medio_dias"].round(1)
    r["pct_pago_em_atraso"] = r["pct_pago_em_atraso"].round(1)
    r["pct_pago_muito_atraso"] = r["pct_pago_muito_atraso"].round(1)
    r["capacidade_mensal"] = r["capacidade_mensal"].round(2)
    return r.reset_index()[_COLUNAS_HISTORICO]


def calcular_score_clientes(
    pagamentos: pd.DataFrame,
    abertos_atual: pd.DataFrame,
    limite_atual_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if pagamentos.empty:
        pagamentos = pd.DataFrame(
            columns=["cliente", "data_vencimento", "data_pagamento", "valor_pago"]
        )

    pagamentos = pagamentos.copy()
    pagamentos["data_vencimento"] = pd.to_datetime(pagamentos["data_vencimento"])
    pagamentos["data_pagamento"] = pd.to_datetime(pagamentos["data_pagamento"])
    pagamentos["atraso_dias"] = (
        pagamentos["data_pagamento"] - pagamentos["data_vencimento"]
    ).dt.days

    hoje = pd.Timestamp(date.today())
    corte_recente = hoje - timedelta(days=90)
    corte_anterior = hoje - timedelta(days=180)

    if pagamentos.empty:
        df_score = pd.DataFrame(columns=_COLUNAS_HISTORICO)
    else:
        df_score = _indicadores_historico(pagamentos, hoje, corte_recente, corte_anterior)

    # --- exposição atual (última foto de títulos em aberto) ---
    if not abertos_atual.empty:
        ab = abertos_atual.copy()
        ab["data_vencimento"] = pd.to_datetime(ab["data_vencimento"])
        ab["dias_para_vencer"] = (ab["data_vencimento"] - hoje).dt.days
        exposicao = (
            ab.groupby("cliente")
            .agg(
                valor_em_aberto=("valor", "sum"),
                qtd_titulos_aberto=("valor", "count"),
                pior_situacao_dias=("dias_para_vencer", "min"),
            )
            .reset_index()
        )
        exposicao["dias_vencido_max"] = exposicao["pior_situacao_dias"].apply(
            lambda d: max(0, -d)
        )
        exposicao = exposicao.drop(columns=["pior_situacao_dias"])
    else:
        exposicao = pd.DataFrame(
            columns=["cliente", "valor_em_aberto", "qtd_titulos_aberto", "dias_vencido_max"]
        )

    df_final = pd.merge(df_score, exposicao, on="cliente", how="outer")

    # --- limite de crédito já cadastrado no ERP (relatório de limite) ---
    # outer join pra incluir também um cliente que só existe nesse
    # relatório (limite cadastrado mas ainda sem título nenhum lançado)
    if limite_atual_df is not None and not limite_atual_df.empty:
        df_final = pd.merge(
            df_final, limite_atual_df[["cliente", "limite_atual"]], on="cliente", how="outer"
        )
    else:
        df_final["limite_atual"] = None

    df_final[["qtd_titulos_pagos", "qtd_titulos_aberto"]] = df_final[
        ["qtd_titulos_pagos", "qtd_titulos_aberto"]
    ].fillna(0)
    df_final[["valor_total_pago", "valor_em_aberto", "capacidade_mensal"]] = df_final[
        ["valor_total_pago", "valor_em_aberto", "capacidade_mensal"]
    ].fillna(0)
    df_final["dias_vencido_max"] = df_final["dias_vencido_max"].fillna(0)
    df_final["tendencia"] = df_final["tendencia"].fillna("sem_dados")
    # limite_atual fica de fora do fillna de propósito: None aqui significa
    # "esse cliente ainda não está no relatório de limite", diferente de
    # ter limite 0.

    df_final["score"] = df_final.apply(_calcular_score_row, axis=1)
    df_final["faixa"] = df_final["score"].apply(_faixa)
    df_final["prazo_politica_dias"] = PRAZO_POLITICA_BOLETO_DIAS

    if df_final.empty:
        df_final["limite_sugerido"] = pd.Series(dtype="float64")
        df_final["margem_disponivel"] = pd.Series(dtype="float64")
        df_final["margem_limite_atual"] = pd.Series(dtype="float64")
        df_final["recomendacao_limite"] = pd.Series(dtype="object")
        df_final["motivos"] = pd.Series(dtype="object")
    else:
        limites = df_final.apply(_calcular_limite_sugerido, axis=1, result_type="expand")
        limites.columns = ["limite_sugerido", "margem_disponivel"]
        df_final = pd.concat([df_final, limites], axis=1)
        df_final["margem_limite_atual"] = df_final.apply(_calcular_margem_limite_atual, axis=1)
        df_final["recomendacao_limite"] = df_final.apply(_recomendar_limite, axis=1)
        df_final["motivos"] = df_final.apply(_motivos_score, axis=1)

    return df_final.sort_values("score").reset_index(drop=True)


def _calcular_score_row(row) -> int:
    """
    Score 0-100 (maior = melhor). Começa em 100 e perde pontos por:
      - atraso médio histórico
      - % de títulos pagos em atraso / muito atraso
      - tendência recente piorando
      - títulos em aberto já vencidos hoje
    Cliente sem histórico de pagamento nenhum recebe score neutro (60).
    """
    if row.get("qtd_titulos_pagos", 0) == 0:
        score = 60
    else:
        score = 100
        atraso_medio = row.get("atraso_medio_dias") or 0
        score -= min(40, max(0, atraso_medio) * 1.5)
        score -= min(20, (row.get("pct_pago_em_atraso") or 0) * 0.2)
        score -= min(20, (row.get("pct_pago_muito_atraso") or 0) * 0.4)
        if row.get("tendencia") == "piorando":
            score -= 10
        elif row.get("tendencia") == "melhorando":
            score += 5

    dias_vencido = row.get("dias_vencido_max") or 0
    score -= min(25, dias_vencido * 1.0)

    return int(max(0, min(100, round(score))))


def _faixa(score: int) -> str:
    if score >= 70:
        return "verde"
    if score >= 40:
        return "amarelo"
    return "vermelho"


def _calcular_limite_sugerido(row):
    """
    Traduz score + capacidade de pagamento em um limite de crédito sugerido
    (quanto o cliente poderia dever no total, somando o que já está em
    aberto) e na margem disponível (limite_sugerido - valor_em_aberto):
    positiva = ainda tem espaço pra liberar mais crédito; negativa = já
    está acima do recomendado pra faixa de risco atual.

    A base do cálculo é a capacidade de pagamento dentro de UM CICLO da
    política de cobrança (PRAZO_POLITICA_BOLETO_DIAS, hoje 21 dias) — não
    da capacidade mensal inteira. Cobrar em boletos de 21 dias e sugerir
    um limite equivalente a vários meses de compras não faz sentido: o
    cliente não deveria acumular mais do que uns poucos ciclos de exposição
    de cada vez.

    Sem histórico de pagamento nenhum, não dá pra estimar capacidade real
    de pagamento — melhor deixar em branco (None) do que sugerir um número
    que passe confiança demais num cliente novo. Nesse caso o limite
    inicial fica a critério do analista.
    """
    if row.get("qtd_titulos_pagos", 0) == 0:
        return None, None

    capacidade_mensal = row.get("capacidade_mensal") or 0
    capacidade_ciclo = capacidade_mensal * (PRAZO_POLITICA_BOLETO_DIAS / 30)
    multiplicador = MULTIPLICADOR_FAIXA.get(row.get("faixa"), 0)
    limite = round(capacidade_ciclo * multiplicador, 2)
    margem = round(limite - (row.get("valor_em_aberto") or 0), 2)
    return limite, margem


def _calcular_margem_limite_atual(row):
    """
    Quanto do limite JÁ CADASTRADO no ERP ainda está livre pra usar
    (limite_atual - valor_em_aberto). Essa é a pergunta mais direta de
    "posso liberar mais crédito dentro do limite que ele já tem?" —
    diferente de margem_disponivel, que compara com o limite SUGERIDO
    pelo score, não com o cadastrado.
    """
    limite_atual = row.get("limite_atual")
    if limite_atual is None or pd.isna(limite_atual):
        return None
    return round(limite_atual - (row.get("valor_em_aberto") or 0), 2)


def _recomendar_limite(row):
    """
    Compara o limite sugerido pelo score com o limite hoje cadastrado no
    ERP: se a diferença for grande (>= 15% do limite atual, ou pelo menos
    R$200), sinaliza que vale revisar o valor cadastrado.
    """
    limite_atual = row.get("limite_atual")
    limite_sugerido = row.get("limite_sugerido")
    if limite_atual is None or pd.isna(limite_atual) or limite_sugerido is None or pd.isna(limite_sugerido):
        return "sem_dados"

    limiar = max(200.0, limite_atual * 0.15)
    diferenca = limite_sugerido - limite_atual
    if diferenca >= limiar:
        return "aumentar"
    if diferenca <= -limiar:
        return "reduzir"
    return "manter"


def _motivos_score(row) -> list[str]:
    """Frases explicando o que pesou no score — pra justificar a decisão de crédito."""
    if row.get("qtd_titulos_pagos", 0) == 0:
        return [
            "Cliente sem histórico de pagamentos registrado — score neutro até "
            "haver dados; avalie o limite inicial manualmente."
        ]

    motivos = []
    atraso_medio = row.get("atraso_medio_dias")
    if atraso_medio is not None and atraso_medio > 0:
        motivos.append(f"Atraso médio histórico de {fmt_num(atraso_medio, 1)} dias no pagamento dos títulos.")
    elif atraso_medio is not None and atraso_medio <= 0:
        motivos.append("Histórico de pagamento em dia ou adiantado, em média.")

    pct_atraso = row.get("pct_pago_em_atraso") or 0
    if pct_atraso > 0:
        motivos.append(f"{pct_atraso:.0f}% dos títulos pagos vieram em atraso.")

    pct_muito_atraso = row.get("pct_pago_muito_atraso") or 0
    if pct_muito_atraso > 0:
        motivos.append(f"{pct_muito_atraso:.0f}% dos títulos pagos tiveram mais de 15 dias de atraso.")

    tendencia = row.get("tendencia")
    if tendencia == "piorando":
        motivos.append("Atraso vem aumentando nos últimos 90 dias em relação ao período anterior.")
    elif tendencia == "melhorando":
        motivos.append("Atraso vem diminuindo nos últimos 90 dias — tendência positiva.")

    dias_vencido = row.get("dias_vencido_max") or 0
    if dias_vencido > 0:
        motivos.append(f"Tem título(s) em aberto vencido(s) há até {int(dias_vencido)} dias hoje.")

    margem_limite_atual = row.get("margem_limite_atual")
    if margem_limite_atual is not None and pd.notna(margem_limite_atual):
        if margem_limite_atual < 0:
            motivos.append(
                f"Já está {fmt_brl(abs(margem_limite_atual))} acima do limite de crédito cadastrado hoje."
            )
        else:
            motivos.append(f"Ainda tem {fmt_brl(margem_limite_atual)} livres dentro do limite cadastrado hoje.")

    if not motivos:
        motivos.append("Sem atrasos registrados — histórico de pagamento consistente.")

    return motivos
