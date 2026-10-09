"""
Filtro de nomes que aparecem no relatório do ERP como se fossem clientes,
mas na verdade são categorias contábeis internas (avaria, quebra de
estoque, bonificação etc.) — o README já alertava pra isso, e agora que o
sistema sugere limite de crédito automaticamente é ainda mais importante
não deixar esses nomes entrarem na conta.

Duas camadas de filtro:
  1) uma lista padrão de palavras-chave comuns em distribuidoras
  2) uma lista manual, cadastrada pelo analista em /configuracoes e
     guardada na tabela clientes_excluidos (ver db.py)
"""
from __future__ import annotations

import pandas as pd

PALAVRAS_CHAVE_PADRAO = [
    "AVARIA",
    "QUEBRA DE ESTOQUE",
    "QUEBRA ESTOQUE",
    "BONIFICA",
    "DEVOLU",
    "PERDA",
    "AJUSTE DE ESTOQUE",
    "AJUSTE ESTOQUE",
    "TROCA DE MERCADORIA",
    "BRINDE",
    "AMOSTRA GR",
    "TRANSFERENCIA",
    "TRANSFERÊNCIA",
    "CONSUMO INTERNO",
    "USO E CONSUMO",
    "DOACAO",
    "DOAÇÃO",
]


def _parece_categoria_contabil(nome: str) -> bool:
    nome_upper = (nome or "").upper()
    return any(p in nome_upper for p in PALAVRAS_CHAVE_PADRAO)


def filtrar_clientes_df(
    df: pd.DataFrame,
    excluidos_manual: set[str] | None = None,
    coluna: str = "cliente",
) -> pd.DataFrame:
    """
    Remove linhas cujo 'cliente' é uma categoria contábil (padrão ou
    cadastrada manualmente), sem alterar o DataFrame original.
    """
    if df.empty or coluna not in df.columns:
        return df
    excluidos_manual = excluidos_manual or set()
    mask_manual = df[coluna].isin(excluidos_manual)
    mask_padrao = df[coluna].apply(_parece_categoria_contabil)
    return df[~(mask_manual | mask_padrao)].reset_index(drop=True)
