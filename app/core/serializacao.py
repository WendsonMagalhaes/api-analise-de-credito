"""Conversão de DataFrames para JSON válido."""
from __future__ import annotations

import json

import pandas as pd


def clean_json(df: pd.DataFrame) -> list[dict]:
    """
    df.to_dict() deixa NaN como NaN (não é JSON válido). Passar por
    to_json()/json.loads() converte NaN -> null corretamente, e também
    resolve tipos numpy (int64 etc.) que o encoder padrão não entende.
    """
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))
