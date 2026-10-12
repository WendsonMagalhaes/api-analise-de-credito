"""Período do filtro das telas: mês atual, últimos 6 meses ou tudo (padrão)."""
from __future__ import annotations

from datetime import date

PERIODOS = ("mes", "6m", "tudo")
PADRAO = "tudo"


def normalizar(periodo: str | None) -> str:
    """Valor desconhecido ou ausente vira o padrão (tudo), nunca erro."""
    return periodo if periodo in PERIODOS else PADRAO


def data_inicio(periodo: str | None, hoje: date | None = None) -> date | None:
    """Primeiro dia do período, ou None para 'tudo' (sem filtro de data).

    '6m' = do dia 1 de cinco meses atrás até hoje (seis meses contando o atual).
    """
    hoje = hoje or date.today()
    p = normalizar(periodo)
    if p == "mes":
        return hoje.replace(day=1)
    if p == "6m":
        ano, mes = hoje.year, hoje.month - 5
        while mes <= 0:
            mes += 12
            ano -= 1
        return date(ano, mes, 1)
    return None
