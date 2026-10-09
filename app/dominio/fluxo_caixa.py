"""
Levantamento do que tem para receber, por faixa de vencimento — compara
o dia de HOJE com a data de vencimento de cada título em aberto. Cada
título cai em exatamente uma faixa (vence em até 8 dias, 9 a 14 dias,
15 a 21 dias, já vencido, ou mais de 21 dias), então as 5 fatias somam
100% do saldo em aberto na última foto importada. Os cortes 8 / 14 / 21
acompanham os prazos dos boletos (8, 14 e 21 dias).

Importante: a comparação é sempre com o dia de hoje. Se a última foto de
títulos em aberto for antiga, tudo que venceu desde então aparece como
"vencido" e as faixas a vencer ficam vazias — o diagnóstico devolvido
(dias_desde_captura / foto_desatualizada) existe para deixar isso claro.

Cada faixa traz o valor cheio (soma bruta dos títulos) e o valor
ponderado (a previsão real de recebimento), que pondera cada título
pela velocidade de pagamento histórica do cliente — um cliente que
historicamente paga com atraso não deve ser contado como se fosse
pagar 100% do valor dentro do prazo.

Peso por título = 1 / indice_medio_movel do cliente, limitado a no
máximo 1.0 (quem paga adiantado ou em dia não "ganha" peso > 1 — o
valor cheio já é o teto). Cliente sem histórico de velocidade ainda
recebe um peso conservador (configurável via PESO_SEM_HISTORICO)
em vez de contar o valor cheio ou zerar.

"Vencido" não tem valor ponderado — já devia ter entrado e não entrou,
então a "previsão" ali é o próprio valor cheio (título vencido cobrado
integralmente, sem desconto por velocidade).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

PESO_SEM_HISTORICO = 0.7

# Faixas exclusivas, em (dia_inicial, dia_final) contados a partir de
# hoje (0 = hoje). Cada título cai em uma única faixa.
FAIXAS = [
    ("ate_8_dias", 0, 8),
    ("9_a_14_dias", 9, 14),
    ("15_a_21_dias", 15, 21),
]


def _peso(indice_medio_movel: float | None) -> float:
    if indice_medio_movel is None or pd.isna(indice_medio_movel) or indice_medio_movel <= 0:
        return PESO_SEM_HISTORICO
    return min(1.0, 1 / indice_medio_movel)


def projetar(
    abertos_df: pd.DataFrame, velocidade_df: pd.DataFrame, hoje: date | None = None
) -> dict:
    hoje = hoje or date.today()
    vazio_faixa = {"valor_cheio": 0.0, "valor_ponderado": 0.0, "qtd_titulos": 0}
    vazio_bucket = {"valor_total": 0.0, "qtd_titulos": 0}
    if abertos_df.empty:
        return {
            **{nome: dict(vazio_faixa) for nome, _, _ in FAIXAS},
            "vencido": vazio_bucket,
            "mais_de_21_dias": vazio_bucket,
            "diagnostico": {
                "hoje": hoje.isoformat(),
                "data_captura": None,
                "total_titulos": 0,
                "valor_total": 0.0,
                "vencimento_min": None,
                "vencimento_max": None,
                "sem_data_vencimento": 0,
                "dias_desde_captura": None,
                "foto_desatualizada": False,
                "sem_vencimentos_futuros": False,
            },
        }

    df = abertos_df.copy()
    df["data_vencimento"] = pd.to_datetime(df["data_vencimento"])
    df = pd.merge(
        df,
        velocidade_df[["cliente", "indice_medio_movel"]] if not velocidade_df.empty else pd.DataFrame(columns=["cliente", "indice_medio_movel"]),
        on="cliente",
        how="left",
    )
    df["peso"] = df["indice_medio_movel"].apply(_peso)
    df["valor_ponderado"] = df["valor"] * df["peso"]

    resultado = {}
    hoje_ts = pd.Timestamp(hoje)

    for nome, dia_ini, dia_fim in FAIXAS:
        inicio = hoje_ts + timedelta(days=dia_ini)
        fim = hoje_ts + timedelta(days=dia_fim)
        na_faixa = df[(df["data_vencimento"] >= inicio) & (df["data_vencimento"] <= fim)]
        resultado[nome] = {
            "valor_cheio": round(float(na_faixa["valor"].sum()), 2),
            "valor_ponderado": round(float(na_faixa["valor_ponderado"].sum()), 2),
            "qtd_titulos": int(len(na_faixa)),
        }

    # já vencido e ainda em aberto — é dinheiro que já deveria ter entrado.
    vencidos = df[df["data_vencimento"] < hoje_ts]
    resultado["vencido"] = {
        "valor_total": round(float(vencidos["valor"].sum()), 2),
        "qtd_titulos": int(len(vencidos)),
    }

    # vai vencer, mas depois da última faixa (21 dias) — fecha o total:
    # vencido + 0-7 + 8-14 + 15-21 + isso aqui = 100% do saldo em aberto.
    limite_21 = hoje_ts + timedelta(days=21)
    mais_de_21 = df[df["data_vencimento"] > limite_21]
    resultado["mais_de_21_dias"] = {
        "valor_total": round(float(mais_de_21["valor"].sum()), 2),
        "qtd_titulos": int(len(mais_de_21)),
    }

    # diagnóstico: deixa claro de que foto e de que datas o cálculo saiu.
    # Se as faixas a vencer vierem zeradas, isso mostra na hora se é porque
    # a última importação é antiga (tudo já venceu de lá pra cá), se os
    # vencimentos estão fora de 21 dias, ou se faltam datas nos títulos.
    datas_validas = df["data_vencimento"].dropna()
    data_captura = None
    dias_desde_captura = None
    if "data_captura" in df.columns and df["data_captura"].notna().any():
        captura = pd.to_datetime(df["data_captura"]).max().date()
        data_captura = captura.isoformat()
        dias_desde_captura = (hoje - captura).days
    resultado["diagnostico"] = {
        "hoje": hoje.isoformat(),
        "data_captura": data_captura,
        "total_titulos": int(len(df)),
        "valor_total": round(float(df["valor"].sum()), 2),
        "vencimento_min": datas_validas.min().date().isoformat() if not datas_validas.empty else None,
        "vencimento_max": datas_validas.max().date().isoformat() if not datas_validas.empty else None,
        "sem_data_vencimento": int(df["data_vencimento"].isna().sum()),
        "dias_desde_captura": dias_desde_captura,
        "foto_desatualizada": bool(dias_desde_captura is not None and dias_desde_captura > 0),
        # Nenhum título vence depois de hoje. Numa carteira em atividade sempre
        # há títulos a vencer, então isso quase sempre significa que o relatório
        # do ERP foi exportado com filtro de vencimento "até hoje" — e aí
        # inicial/intermediária e as faixas de 8/14/21 dias não têm o que mostrar.
        "sem_vencimentos_futuros": bool(
            not datas_validas.empty and datas_validas.max() <= hoje_ts
        ),
    }

    return resultado
