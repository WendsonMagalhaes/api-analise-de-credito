"""
prazo_do_titulo: quantidade de dias entre emissão e vencimento de UM
título específico. É variável (8, 14 ou 21 dias — 21 é o teto máximo
permitido, nunca o valor padrão assumido), por isso toda fórmula das
novas funcionalidades (velocidade, aging, alertas...) usa o prazo do
título em questão, nunca uma constante fixa. A lista de prazos válidos
fica em configuracoes (não hardcoded) para o analista poder ajustar se
a política comercial mudar.
"""
from __future__ import annotations

import pandas as pd

from app.db import config

CHAVE_PRAZOS_PERMITIDOS = "prazos_permitidos_dias"
_PADRAO_PRAZOS_PERMITIDOS = [8, 14, 21]


def prazos_permitidos() -> list[int]:
    return config.get(CHAVE_PRAZOS_PERMITIDOS, _PADRAO_PRAZOS_PERMITIDOS)


def calcular_prazo_do_titulo(data_emissao, data_vencimento) -> int | None:
    """data_vencimento - data_emissao, em dias. None se alguma data faltar."""
    if pd.isna(data_emissao) or pd.isna(data_vencimento):
        return None
    return (pd.to_datetime(data_vencimento) - pd.to_datetime(data_emissao)).days


def validar_prazo(prazo: int | None) -> bool:
    """
    Um prazo fora da lista (8/14/21) não impede o título de ser gravado —
    o relatório do ERP é a fonte da verdade e pode ter exceções pontuais —
    mas fica marcado como fora do padrão pra quem for auditar depois.
    """
    if prazo is None:
        return True
    return prazo in prazos_permitidos()


def anexar_prazo(df: pd.DataFrame) -> pd.DataFrame:
    """Garante a coluna prazo_do_titulo num DataFrame que já tenha
    data_emissao/data_vencimento (recalcula em vez de confiar só no que
    veio do banco, útil quando o DataFrame foi montado na hora)."""
    if df.empty:
        df = df.copy()
        df["prazo_do_titulo"] = pd.Series(dtype="Int64")
        return df
    df = df.copy()
    if "prazo_do_titulo" not in df.columns or df["prazo_do_titulo"].isna().all():
        df["prazo_do_titulo"] = (
            pd.to_datetime(df["data_vencimento"]) - pd.to_datetime(df["data_emissao"])
        ).dt.days
    return df
