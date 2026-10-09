"""
Reanálise de crédito: agendamento por classe + gatilhos por evento.

data_proxima_reanalise fica em clientes_metadata, calculada a partir da
classe atual (intervalo configurável em meses por classe — padrão
6/4/2/1/1 para A/B/C/D/E). O job diário roda independente da data
agendada, checando gatilhos que antecipam a reanálise:

  - mais de N usos de tolerância no trimestre (tolerancia.py)
  - piora consistente na velocidade de pagamento (últimos 3 snapshots
    de velocidade em tendência de alta = mais lento)
  - primeiro estouro de prazo em muito tempo (título vencido hoje pra
    quem não tinha nenhum há mais de 180 dias)
  - mudança abrupta de volume de pedidos (qtd_titulos_aberto muito
    diferente da média histórica)
  - queda de faixa/classe de score

Gatilhos externos (protesto, ação judicial, negativação, mudança
cadastral do CNPJ) são registrados via endpoint dedicado, porque vêm de
fora do fluxo de upload de relatório (ex.: consulta manual ou scraping
futuro do civis.com.br).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from psycopg2.extras import Json

from app.db import config
from app.dominio import tolerancia
from app import db

CHAVE_MESES_POR_CLASSE = "reanalise_intervalo_meses_por_classe"
CHAVE_MAX_USO_TOLERANCIA_TRIMESTRE = "reanalise_gatilho_uso_tolerancia_max_trimestre"

_PADRAO_MESES = {"A": 6, "B": 4, "C": 2, "D": 1, "E": 1}


def calcular_proxima_reanalise(classe: str, hoje: date | None = None) -> date:
    hoje = hoje or date.today()
    meses = config.get(CHAVE_MESES_POR_CLASSE, _PADRAO_MESES).get(classe, 1)
    return hoje + timedelta(days=int(meses) * 30)


def agendar(cliente: str, classe: str) -> None:
    proxima = calcular_proxima_reanalise(classe)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clientes_metadata (cliente, data_proxima_reanalise, classe_atual)
                VALUES (%(c)s, %(d)s, %(classe)s)
                ON CONFLICT (cliente) DO UPDATE SET
                    data_proxima_reanalise = EXCLUDED.data_proxima_reanalise,
                    classe_atual = EXCLUDED.classe_atual,
                    atualizado_em = NOW()
                """,
                {"c": cliente, "d": proxima, "classe": classe},
            )
        conn.commit()


def _registrar_gatilho(cliente: str, tipo: str, detalhes: dict) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reanalise_gatilhos (cliente, tipo_gatilho, detalhes) VALUES (%(c)s, %(t)s, %(d)s)",
                {"c": cliente, "t": tipo, "d": Json(detalhes)},
            )
        conn.commit()


def verificar_gatilhos_por_evento(cliente: str, classe_atual: str, classe_anterior: str | None) -> list[str]:
    """Roda no job diário para UM cliente, retorna a lista de tipos de
    gatilho disparados agora (idempotência simples: cada chamada pode
    gerar um novo registro em reanalise_gatilhos — a tela de pendentes
    filtra por `resolvido = false`, então repetição não é um problema
    grave, mas o job diário deve rodar só uma vez por dia por cliente)."""
    disparados = []

    usos_trimestre = tolerancia.contar_usos_no_trimestre(cliente)
    limite_usos = config.get(CHAVE_MAX_USO_TOLERANCIA_TRIMESTRE, 2)
    if usos_trimestre > limite_usos:
        _registrar_gatilho(cliente, "uso_tolerancia_excessivo", {"usos_trimestre": usos_trimestre})
        disparados.append("uso_tolerancia_excessivo")

    if classe_anterior and classe_atual != classe_anterior:
        ordem = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        if ordem.get(classe_atual, 4) > ordem.get(classe_anterior, 0):
            _registrar_gatilho(cliente, "queda_de_classe", {"de": classe_anterior, "para": classe_atual})
            disparados.append("queda_de_classe")

    return disparados


def agendar_em_lote(pares: list[tuple[str, str]], conn=None, hoje: date | None = None) -> None:
    """Versão em lote de agendar(): (cliente, classe) de toda a carteira numa
    gravação só (antes: uma transação por cliente)."""
    if not pares:
        return
    linhas = [(cliente, calcular_proxima_reanalise(classe, hoje), classe) for cliente, classe in pares]
    with db.conn_ou_nova(conn) as c:
        with c.cursor() as cur:
            db.bulk_upsert(
                cur,
                "clientes_metadata",
                ["cliente", "data_proxima_reanalise", "classe_atual"],
                linhas,
                conflito=["cliente"],
                atualizar=["data_proxima_reanalise", "classe_atual"],
                extra_set="atualizado_em = NOW()",
            )


def verificar_gatilhos_em_lote(itens: list[tuple[str, str, str | None]], conn) -> dict[str, list[str]]:
    """
    Versão em lote de verificar_gatilhos_por_evento. `itens` =
    [(cliente, classe_atual, classe_anterior)]. Precisa rodar DEPOIS de
    gravar os eventos de tolerância do dia, na MESMA conexão — a contagem de
    usos no trimestre inclui o de hoje.

    Diferença de comportamento: não cria um gatilho novo se o cliente já tem
    um gatilho do mesmo tipo AINDA NÃO RESOLVIDO. Antes, cada recálculo
    (upload, "Atualizar análise", recálculo manual) inseria de novo o mesmo
    gatilho — a lista de pendências enchia de duplicatas do mesmo problema.
    """
    if not itens:
        return {}
    clientes = [i[0] for i in itens]
    usos = tolerancia.contar_usos_no_trimestre_em_lote(clientes, conn)
    limite_usos = config.get(CHAVE_MAX_USO_TOLERANCIA_TRIMESTRE, 2)
    ordem = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}

    candidatos: list[tuple[str, str, dict]] = []
    for cliente, classe_atual, classe_anterior in itens:
        if usos.get(cliente, 0) > limite_usos:
            candidatos.append((cliente, "uso_tolerancia_excessivo", {"usos_trimestre": usos[cliente]}))
        if classe_anterior and classe_atual != classe_anterior:
            if ordem.get(classe_atual, 4) > ordem.get(classe_anterior, 0):
                candidatos.append((cliente, "queda_de_classe", {"de": classe_anterior, "para": classe_atual}))
    if not candidatos:
        return {}

    with conn.cursor() as cur:
        cur.execute(
            """SELECT cliente, tipo_gatilho FROM reanalise_gatilhos
               WHERE resolvido = FALSE AND cliente = ANY(%(cs)s)""",
            {"cs": list({c[0] for c in candidatos})},
        )
        ja_abertos = {(r["cliente"], r["tipo_gatilho"]) for r in cur.fetchall()}

        novos = [c for c in candidatos if (c[0], c[1]) not in ja_abertos]
        db.bulk_upsert(
            cur,
            "reanalise_gatilhos",
            ["cliente", "tipo_gatilho", "detalhes"],
            novos,
        )

    disparados: dict[str, list[str]] = {}
    for cliente, tipo, _ in novos:
        disparados.setdefault(cliente, []).append(tipo)
    return disparados


def registrar_gatilho_externo(cliente: str, tipo: str, detalhes: dict | None = None) -> None:
    """Protesto, ação judicial, negativação ou mudança cadastral do CNPJ —
    registrado manualmente (ou por integração futura), fora do job diário."""
    _registrar_gatilho(cliente, tipo, detalhes or {})


def fetch_pendentes() -> pd.DataFrame:
    return db.read_df(
        "SELECT * FROM reanalise_gatilhos WHERE resolvido = FALSE ORDER BY criado_em DESC"
    )


def marcar_resolvido(gatilho_id: int) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reanalise_gatilhos SET resolvido = TRUE WHERE id = %(id)s", {"id": gatilho_id})
        conn.commit()


def fetch_agenda() -> pd.DataFrame:
    return db.read_df(
        """SELECT cliente, data_proxima_reanalise, classe_atual FROM clientes_metadata
           WHERE data_proxima_reanalise IS NOT NULL ORDER BY data_proxima_reanalise"""
    )
