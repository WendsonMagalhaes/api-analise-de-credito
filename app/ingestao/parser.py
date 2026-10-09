"""
Parser dos relatórios exportados pelo ERP (Contas a Receber) e do relatório
de limite de crédito atual dos clientes.

Os relatórios de Contas a Receber vêm com extensão .xls mas o conteúdo é
HTML puro:

  1) TÍTULOS EM ABERTO (ainda não pagos)
     Colunas: Data Emissao, Título, Cliente, Vendedor, Plano de Conta,
              Conta, Valor, Data Vencimento

  2) TÍTULOS PAGOS (histórico de recebimentos)
     Colunas: Data Emissao, Título, Cliente, Vendedor, Plano de Conta,
              Conta, Valor, Data Vencimento, Valor Pago, Juros/Multa,
              Data Pagamento

O relatório de LIMITE DE CRÉDITO (3º tipo) pode vir tanto nesse mesmo
formato HTML quanto como planilha de verdade (.xlsx/.csv) — só precisa ter
uma coluna de cliente e uma coluna com "limite" no nome (ex.: "Limite de
Crédito", "Limite Atual"). Se os nomes de coluna do seu relatório forem
muito diferentes disso, o upload falha com uma mensagem mostrando as
colunas encontradas — me avise pra eu ajustar.

Este módulo detecta automaticamente qual dos três formatos foi enviado e
devolve um DataFrame limpo.
"""
from __future__ import annotations

import io
import re

import pandas as pd
from bs4 import BeautifulSoup

TITULO_RE = re.compile(
    r"PARCELA\s*\((\d+)/(\d+)\)\s*da venda\s*n[ºo]\s*(\d+)", re.IGNORECASE
)

_ACENTOS = str.maketrans("ÁÃÂÀÉÊÍÓÕÔÚÇ", "AAAAEEIOOOUC")


def _normalizar_coluna(col: str) -> str:
    return col.strip().upper().translate(_ACENTOS)


def _decodificar_html(file_bytes: bytes) -> str:
    """Mesma ideia do BeautifulSoup: charset declarado no HTML, depois UTF-8,
    depois windows-1252 (o que o ERP costuma exportar)."""
    cabecalho = file_bytes[:4096].decode("ascii", "ignore")
    m = re.search(r"charset=[\"']?([\w-]+)", cabecalho, re.IGNORECASE)
    tentativas = ([m.group(1)] if m else []) + ["utf-8", "cp1252"]
    for enc in tentativas:
        try:
            return file_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return file_bytes.decode("utf-8", "replace")


def _ler_html_lxml(file_bytes: bytes) -> pd.DataFrame | None:
    """Caminho rápido (lxml direto): ~1s para 45 mil linhas contra ~11s do
    BeautifulSoup com html.parser. Devolve exatamente o mesmo DataFrame."""
    import lxml.html

    doc = lxml.html.fromstring(_decodificar_html(file_bytes))
    table = doc.find(".//table")
    if table is None:
        return None
    rows = table.findall(".//tr")
    if not rows:
        return None
    header = [th.text_content().strip() for th in rows[0].iter("th")]
    if not header:
        return None
    data = []
    for tr in rows[1:]:
        cells = [td.text_content().strip() for td in tr.iter("td")]
        if cells:
            data.append(cells)
    return pd.DataFrame(data, columns=header)


def _ler_html_bs4(file_bytes: bytes) -> pd.DataFrame | None:
    soup = BeautifulSoup(file_bytes, "html.parser")
    table = soup.find("table")
    if table is None:
        return None
    rows = table.find_all("tr")
    if not rows:
        return None
    header = [th.get_text(strip=True) for th in rows[0].find_all("th")]
    if not header:
        return None
    data = []
    for tr in rows[1:]:
        cells = tr.find_all("td")
        if not cells:
            continue
        data.append([td.get_text(strip=True) for td in cells])
    return pd.DataFrame(data, columns=header)


def _tentar_ler_html(file_bytes: bytes) -> pd.DataFrame | None:
    """
    Lê a primeira <table> do HTML mantendo TODAS as células como texto cru
    (necessário porque pandas.read_html adivinha tipos numéricos errado com
    números em formato BR). Devolve None se o conteúdo não for esse HTML
    disfarçado de .xls — nesse caso quem chamou tenta ler como planilha de
    verdade (ver _ler_planilha_real).

    Usa lxml se estiver instalado (muito mais rápido); se não estiver, ou se
    ele falhar, cai no BeautifulSoup como antes.
    """
    try:
        df = _ler_html_lxml(file_bytes)
        if df is not None:
            return df
    except Exception:
        pass
    try:
        return _ler_html_bs4(file_bytes)
    except Exception:
        return None


def _ler_planilha_real(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Fallback pra quando o arquivo não é o HTML disfarçado de .xls do ERP
    — usado principalmente pelo relatório de limite de crédito, que pode
    vir como planilha .xlsx/.csv mantida à parte."""
    nome = (filename or "").lower()
    buffer = io.BytesIO(file_bytes)
    if nome.endswith(".csv"):
        return pd.read_csv(buffer, sep=None, engine="python", dtype=str)
    return pd.read_excel(buffer, dtype=str)


def _parse_valor_brl(series: pd.Series) -> pd.Series:
    """Converte '1.234,56' (string, formato BR) em float 1234.56."""
    return (
        series.astype(str)
        .str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .replace({"nan": None, "": None})
        .astype(float)
    )


def _parse_valor_flexivel(series: pd.Series) -> pd.Series:
    """
    Como _parse_valor_brl, mas também aceita números que já vêm 'limpos'
    (ex.: '1234.56'), pro caso do relatório de limite vir de uma planilha
    real em vez do HTML do ERP — aí a célula já é numérica e não tem
    separador de milhar.
    """

    def _parse_um(v):
        if v is None:
            return None
        s = str(v).strip()
        if s == "" or s.lower() == "nan":
            return None
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    return series.apply(_parse_um)


def _parse_data_br(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, format="%d/%m/%Y", errors="coerce").dt.date


def _extract_venda_parcela(titulo: pd.Series) -> pd.DataFrame:
    extracted = titulo.astype(str).str.extract(TITULO_RE)
    extracted.columns = ["parcela_num", "parcela_total", "venda_numero"]
    for col in ["parcela_num", "parcela_total", "venda_numero"]:
        extracted[col] = pd.to_numeric(extracted[col], errors="coerce").astype("Int64")
    return extracted


def _detectar_tipo(colunas: list[str]) -> str:
    normalizadas = {_normalizar_coluna(c) for c in colunas}
    if "DATA PAGAMENTO" in normalizadas:
        return "pago"
    if any("LIMITE" in c for c in normalizadas):
        return "limite"
    return "aberto"


def _processar_limite(df: pd.DataFrame) -> pd.DataFrame:
    """
    Processa o relatório de limite de crédito atual. Aceita variações
    comuns de nome de coluna (Cliente / Limite de Crédito / Limite Atual /
    Limite) — se o relatório usar nomes bem diferentes disso, a mensagem
    de erro abaixo mostra as colunas encontradas pra eu ajustar.
    """
    coluna_cliente = None
    coluna_limite = None
    for col in df.columns:
        norm = _normalizar_coluna(col)
        if coluna_cliente is None and norm == "CLIENTE":
            coluna_cliente = col
        elif coluna_limite is None and "LIMITE" in norm:
            coluna_limite = col

    if coluna_cliente is None or coluna_limite is None:
        raise ValueError(
            "Não encontrei as colunas 'Cliente' e 'Limite' nesse arquivo. "
            f"Colunas encontradas: {list(df.columns)}"
        )

    df = df.rename(columns={coluna_cliente: "cliente", coluna_limite: "limite_atual"})
    df = df[["cliente", "limite_atual"]].copy()
    df["cliente"] = df["cliente"].astype(str).str.strip()
    df["limite_atual"] = _parse_valor_flexivel(df["limite_atual"])
    df = df[df["cliente"].astype(bool)].dropna(subset=["cliente"])
    return df.reset_index(drop=True)


def _processar_titulos(df: pd.DataFrame, tipo: str) -> pd.DataFrame:
    df = df.rename(
        columns={
            "Data Emissao": "data_emissao",
            "Título": "titulo",
            "Cliente": "cliente",
            "Vendedor": "vendedor",
            "Plano de Conta": "plano_conta",
            "Conta": "conta",
            "Valor": "valor",
            "Data Vencimento": "data_vencimento",
            "Valor Pago": "valor_pago",
            "Juros/Multa": "juros_multa",
            "Data Pagamento": "data_pagamento",
        }
    )

    df["cliente"] = df["cliente"].astype(str).str.strip()
    df["data_emissao"] = _parse_data_br(df["data_emissao"])
    df["data_vencimento"] = _parse_data_br(df["data_vencimento"])
    df["valor"] = _parse_valor_brl(df["valor"])

    venda_parcela = _extract_venda_parcela(df["titulo"])
    df = pd.concat([df, venda_parcela], axis=1)

    if tipo == "pago":
        df["valor_pago"] = _parse_valor_brl(df["valor_pago"])
        df["juros_multa"] = _parse_valor_brl(df["juros_multa"])
        df["data_pagamento"] = _parse_data_br(df["data_pagamento"])

    return df


def parse_relatorio(file_bytes: bytes, filename: str = "") -> tuple[str, pd.DataFrame]:
    """
    Recebe os bytes brutos de um arquivo exportado do ERP (Contas a Receber
    ou limite de crédito). Retorna (tipo, dataframe) onde tipo é 'aberto',
    'pago' ou 'limite'.
    """
    df_bruto = _tentar_ler_html(file_bytes)
    if df_bruto is None:
        df_bruto = _ler_planilha_real(file_bytes, filename)

    if df_bruto is None or df_bruto.empty or len(df_bruto.columns) == 0:
        raise ValueError("Não consegui identificar nenhuma coluna nesse arquivo.")

    tipo = _detectar_tipo(list(df_bruto.columns))

    if tipo == "limite":
        return "limite", _processar_limite(df_bruto)
    return tipo, _processar_titulos(df_bruto, tipo)
