"""Conversões de valores do pandas (NaN/NaT) para tipos aceitos pelo banco."""
from __future__ import annotations

import pandas as pd


def date_ou_none(d):
    return d if pd.notna(d) else None


def int_ou_none(v):
    return int(v) if pd.notna(v) else None


def num_ou_none(v):
    return float(v) if pd.notna(v) else None
