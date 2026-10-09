"""
Formatação de números em textos gerados pelo backend (motivos do score,
motivos de reajuste etc.), no padrão brasileiro: vírgula decimal e ponto de
milhar. Implementado à mão de propósito: o módulo `locale` depende de o
sistema operacional ter o pt_BR instalado, o que não dá para garantir no
servidor.
"""
from __future__ import annotations


def fmt_num(valor: float, casas: int = 1) -> str:
    """1234.5, 1 -> '1.234,5'"""
    return f"{valor:,.{casas}f}".replace(",", "\0").replace(".", ",").replace("\0", ".")


def fmt_num_livre(valor: float, max_casas: int = 2) -> str:
    """Sem zeros à direita: 10.0 -> '10'; 7.5 -> '7,5'; 1.25 -> '1,25'."""
    texto = f"{valor:.{max_casas}f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def fmt_brl(valor: float) -> str:
    """1234.5 -> 'R$ 1.234,50'"""
    return f"R$ {fmt_num(valor, 2)}"
