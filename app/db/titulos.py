"""Títulos: pagamentos (histórico) e abertos_snapshot (foto diária dos títulos em aberto)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.db.conexao import bulk_upsert, get_conn, read_df
from app.db.conversores import date_ou_none, int_ou_none, num_ou_none
from app.db.exclusoes import filtro_exclusao


def _prazo_do_titulo_dias(data_emissao, data_vencimento) -> int | None:
    """
    prazo_do_titulo = data_vencimento - data_emissao, em dias. É variável
    por título (8, 14 ou 21 dias — 21 é só o teto máximo, nunca um valor
    fixo assumido), por isso é sempre recalculado a partir das duas datas
    do próprio título em vez de usar uma constante. None quando alguma
    das datas não veio no relatório do ERP.
    """
    emissao = date_ou_none(data_emissao)
    vencimento = date_ou_none(data_vencimento)
    if emissao is None or vencimento is None:
        return None
    return (vencimento - emissao).days


def _prazos_vetorizado(df: pd.DataFrame) -> list:
    """Mesmo cálculo de _prazo_do_titulo_dias, para o DataFrame inteiro de uma vez."""
    dias = (pd.to_datetime(df["data_vencimento"]) - pd.to_datetime(df["data_emissao"])).dt.days
    return [None if pd.isna(d) else int(d) for d in dias]


def _lista_ou_none(serie: pd.Series) -> list:
    return [None if pd.isna(v) else v for v in serie]


def _linhas_titulos(df: pd.DataFrame, tipo: str, data_captura: date | None) -> list[tuple]:
    """
    Monta as linhas de INSERT sem iterrows (que cria uma Series por linha —
    o grosso do tempo de gravação de um arquivo grande). A chave_natural é
    montada com EXATAMENTE os mesmos str() de antes: mudar esse texto faria
    os títulos já gravados deixarem de ser reconhecidos como duplicados.
    """
    cliente = df["cliente"].tolist()
    venda = df["venda_numero"].tolist()
    parcela = df["parcela_num"].tolist()
    prazos = _prazos_vetorizado(df)
    emissao = _lista_ou_none(df["data_emissao"])
    venc = _lista_ou_none(df["data_vencimento"])

    n = len(df)

    def _texto_ou_none(coluna: str) -> list:
        # coluna ausente no relatório ou célula em branco -> NULL
        if coluna not in df.columns:
            return [None] * n
        return [v.strip() if isinstance(v, str) and v.strip() else None for v in df[coluna].tolist()]

    if tipo == "pago":
        pgto = _lista_ou_none(df["data_pagamento"])
        valor_pago = df["valor_pago"].tolist()
        chaves = [
            "|".join(str(x) for x in (c, v, p, d, vp))
            for c, v, p, d, vp in zip(cliente, venda, parcela, pgto, valor_pago)
        ]
    else:
        prefixo = data_captura.isoformat()
        chaves = ["|".join(str(x) for x in (prefixo, c, v, p)) for c, v, p in zip(cliente, venda, parcela)]

    comuns = zip(
        chaves,
        cliente,
        df["titulo"].tolist(),
        [int_ou_none(v) for v in venda],
        [int_ou_none(v) for v in parcela],
        [int_ou_none(v) for v in df["parcela_total"].tolist()],
        df["vendedor"].tolist(),
        emissao,
        venc,
        [num_ou_none(v) for v in df["valor"].tolist()],
    )
    if tipo == "pago":
        return [
            (*c, num_ou_none(vp), num_ou_none(jm), d, pz)
            for c, vp, jm, d, pz in zip(
                comuns, valor_pago, df["juros_multa"].tolist(), pgto, prazos
            )
        ]
    plano, conta = _texto_ou_none("plano_conta"), _texto_ou_none("conta")
    return [
        (chave, data_captura, *resto, pz, pc, ct)
        for ((chave, *resto), pz, pc, ct) in zip(comuns, prazos, plano, conta)
    ]


def upsert_pagamentos(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"inseridos": 0, "duplicados": 0}

    rows = _linhas_titulos(df, "pago", None)
    colunas = [
        "chave_natural", "cliente", "titulo", "venda_numero", "parcela_num",
        "parcela_total", "vendedor", "data_emissao", "data_vencimento",
        "valor", "valor_pago", "juros_multa", "data_pagamento", "prazo_do_titulo",
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            inseridos = bulk_upsert(cur, "pagamentos", colunas, rows, conflito=["chave_natural"])
        conn.commit()
    return {"inseridos": inseridos, "duplicados": len(rows) - inseridos}


def upsert_abertos(df: pd.DataFrame, data_captura: date | None = None) -> dict:
    if df.empty:
        return {"inseridos": 0, "duplicados": 0}

    data_captura = data_captura or date.today()
    rows = _linhas_titulos(df, "aberto", data_captura)
    colunas = [
        "chave_natural", "data_captura", "cliente", "titulo", "venda_numero",
        "parcela_num", "parcela_total", "vendedor", "data_emissao",
        "data_vencimento", "valor", "prazo_do_titulo", "plano_conta", "conta",
    ]
    # Títulos já gravados ANTES de existir a coluna conta (ON CONFLICT DO NOTHING
    # não os tocaria) recebem conta/plano_conta na próxima importação — só onde
    # ainda estão vazios, então o resultado ("novos" x "já existiam") não muda.
    preencher = """
        UPDATE abertos_snapshot a
           SET conta = COALESCE(a.conta, t.conta), plano_conta = COALESCE(a.plano_conta, t.plano_conta)
          FROM {tmp} t
         WHERE a.chave_natural = t.chave_natural
           AND ((a.conta IS NULL AND t.conta IS NOT NULL)
             OR (a.plano_conta IS NULL AND t.plano_conta IS NOT NULL))
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inseridos = bulk_upsert(
                cur, "abertos_snapshot", colunas, rows, conflito=["chave_natural"], depois=preencher
            )
        conn.commit()
    return {"inseridos": inseridos, "duplicados": len(rows) - inseridos}


def fetch_pagamentos_df() -> pd.DataFrame:
    """Só as colunas que o cálculo usa (score, velocidade) — SELECT * trazia
    também título, vendedor, chave_natural etc. do histórico inteiro pela
    rede, sem ninguém usar. `id` entra como desempate estável na ordenação."""
    return read_df(
        """SELECT id, cliente, data_emissao, data_vencimento, data_pagamento,
                  valor_pago, prazo_do_titulo
           FROM pagamentos"""
    )


def fetch_pagamentos_cliente_df(cliente: str) -> pd.DataFrame:
    """Como fetch_pagamentos_df, mas de UM cliente, com todas as colunas
    (tela de detalhe). Usa o índice idx_pagamentos_cliente_data."""
    return read_df(
        "SELECT * FROM pagamentos WHERE cliente = %(c)s ORDER BY data_pagamento DESC NULLS LAST",
        {"c": cliente},
    )


def fetch_ultimo_snapshot_df(sem_categorias_contabeis: bool = False) -> pd.DataFrame:
    """Títulos em aberto da captura mais recente — uma consulta só (antes:
    MAX(data_captura) numa ida e volta e o SELECT em outra).

    sem_categorias_contabeis=True tira AVARIA, QUEBRA DE ESTOQUE e demais
    "clientes" que são categorias contábeis (mesmo filtro do dashboard), para
    o aging e o "a receber" fecharem com o total em aberto."""
    if not sem_categorias_contabeis:
        return read_df(
            """SELECT * FROM abertos_snapshot
               WHERE data_captura = (SELECT MAX(data_captura) FROM abertos_snapshot)"""
        )
    excl, padroes = filtro_exclusao()
    return read_df(
        f"""SELECT * FROM abertos_snapshot
            WHERE data_captura = (SELECT MAX(data_captura) FROM abertos_snapshot) AND {excl}""",
        {"padroes_exclusao": padroes},
    )


def fetch_aberto_cliente_df(cliente: str) -> pd.DataFrame:
    """Títulos em aberto de UM cliente na captura mais recente, filtrado
    direto no banco (a tela de detalhe não precisa da foto inteira)."""
    return read_df(
        """
        SELECT * FROM abertos_snapshot
        WHERE cliente = %(c)s
          AND data_captura = (SELECT MAX(data_captura) FROM abertos_snapshot)
        """,
        {"c": cliente},
    )


def fetch_snapshots_historico_df() -> pd.DataFrame:
    """Total em aberto por data_captura — para ver a tendência da carteira."""
    return read_df(
        """SELECT data_captura, COUNT(*) AS qtd_titulos, SUM(valor) AS valor_total
           FROM abertos_snapshot GROUP BY data_captura ORDER BY data_captura"""
    )
