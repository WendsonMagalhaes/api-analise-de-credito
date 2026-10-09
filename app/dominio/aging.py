"""
Aging proporcional ao prazo do título.

Faixas fixas de dias (0-7, 8-14...) só fariam sentido se todo boleto
tivesse o mesmo prazo — mas o prazo varia por título (8/14/21). Por
isso o aging aqui é sempre em % do prazo já decorrido
(dias_corridos / prazo_do_titulo), e a classificação é uma faixa desse
percentual: um título de 8 dias em seu 6º dia (75%) está tão "na reta
final" quanto um de 21 dias no 16º dia (76%), mesmo com contagens de
dias bem diferentes.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def calcular_pct_decorrido(data_emissao, prazo_do_titulo, hoje: date | None = None) -> float | None:
    if prazo_do_titulo in (None, 0) or pd.isna(data_emissao) or pd.isna(prazo_do_titulo):
        return None
    hoje = hoje or date.today()
    dias_corridos = (pd.Timestamp(hoje) - pd.to_datetime(data_emissao)).days
    return round((dias_corridos / prazo_do_titulo) * 100, 1)


def classificar(pct_decorrido: float | None) -> str:
    if pct_decorrido is None or pd.isna(pct_decorrido):
        return "sem_dados"
    if pct_decorrido > 100:
        return "vencido"
    if pct_decorrido >= 67:
        return "reta_final"
    if pct_decorrido >= 34:
        return "intermediaria"
    return "inicial"


def anexar_aging(df_abertos: pd.DataFrame, hoje: date | None = None) -> pd.DataFrame:
    """Recebe um DataFrame de títulos em aberto (com data_emissao e
    prazo_do_titulo) e devolve com pct_prazo_decorrido e
    classificacao_aging por título.

    Vetorizado: antes chamava pd.to_datetime/pd.Timestamp uma vez por título
    (df.apply linha a linha) — lento com dezenas de milhares de títulos, e o
    dashboard e os alertas rodam isso a cada carga."""
    df = df_abertos.copy()
    if df.empty:
        df["pct_prazo_decorrido"] = pd.Series(dtype="float64")
        df["classificacao_aging"] = pd.Series(dtype="object")
        return df

    hoje = hoje or date.today()
    dias_corridos = (pd.Timestamp(hoje) - pd.to_datetime(df["data_emissao"])).dt.days
    prazo = pd.to_numeric(df["prazo_do_titulo"], errors="coerce") if "prazo_do_titulo" in df else pd.Series(np.nan, index=df.index)
    valido = prazo.notna() & (prazo != 0) & dias_corridos.notna()
    pct = (dias_corridos / prazo * 100).where(valido).round(1)

    df["pct_prazo_decorrido"] = pct

    # Título com prazo 0 (emissão = vencimento: venda à vista, lançamento
    # interno) não tem % de prazo — a divisão por zero deixava tudo isso em
    # "sem dados". Nesses casos vale a data de vencimento: já passou = vencido;
    # vence hoje = reta final (100% do prazo, sem folga nenhuma).
    venc = pd.to_datetime(df["data_vencimento"]) if "data_vencimento" in df else pd.Series(pd.NaT, index=df.index)
    sem_pct = pct.isna()
    prazo_zero = sem_pct & (prazo == 0) & venc.notna()
    vencido_por_data = prazo_zero & (venc < pd.Timestamp(hoje))
    vence_hoje_prazo_zero = prazo_zero & ~vencido_por_data

    # título sem prazo/emissão conhecidos fica "sem_dados" (antes o NaN caía em "inicial")
    df["classificacao_aging"] = np.select(
        [vencido_por_data, vence_hoje_prazo_zero, sem_pct, pct > 100, pct >= 67, pct >= 34],
        ["vencido", "reta_final", "sem_dados", "vencido", "reta_final", "intermediaria"],
        default="inicial",
    )
    return df


def resumo_por_faixa(df_com_aging: pd.DataFrame) -> dict:
    """Valor total e quantidade de títulos por faixa de aging — para a
    view agregada da carteira (endpoint /api/aging/resumo)."""
    if df_com_aging.empty:
        return {}
    agrupado = df_com_aging.groupby("classificacao_aging").agg(
        qtd_titulos=("valor", "count"), valor_total=("valor", "sum")
    )
    resumo = agrupado.round(2).to_dict(orient="index")
    # As 4 faixas do aging sempre voltam, mesmo zeradas: sem isso, faixa sem
    # título simplesmente sumia da resposta e parecia que o sistema "não
    # pegava" os iniciais/intermediários. ("sem_dados" só volta se existir.)
    for faixa in ("inicial", "intermediaria", "reta_final", "vencido"):
        resumo.setdefault(faixa, {"qtd_titulos": 0, "valor_total": 0.0})
    return resumo
