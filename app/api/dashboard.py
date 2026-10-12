"""Dashboard: carteira paginada, visão geral (mês, vencidos, carteira, vendedores), histórico, exportação e recálculo."""
from __future__ import annotations

from datetime import date
import io

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import db
from app.core import cache, periodo as periodo_mod
from app.core.serializacao import clean_json
from app.db import metricas
from app.dominio import visao_geral
from app.servicos.carteira import recalcular_e_salvar_carteira

router = APIRouter()


@router.post("/api/carteira/recalcular")
def recalcular_carteira():
    """
    Refaz o cálculo da carteira sem precisar subir um relatório novo —
    útil depois de mudar a lista de clientes excluídos, por exemplo (essa
    mudança já vale na hora pra leitura, mas isso força atualizar também
    o snapshot do dia usado nos alertas).
    """
    score_df = recalcular_e_salvar_carteira()
    return {"total_clientes": len(score_df)}


@cache.ttl_cache(60)
def _resumo_base():
    """Dados que não mudam com a página/busca/ordem da tabela."""
    return db.fetch_carteira_atualizada_em(), db.fetch_resumo_geral(), db.fetch_maiores_expostos()


@cache.ttl_cache(60)
def _destaques(periodo: str):
    """Maior compra e maior atraso da carteira no período (varre pagamentos: por isso fica em cache)."""
    return metricas.fetch_destaques(periodo_mod.data_inicio(periodo))


@router.get("/api/dashboard")
@cache.ttl_cache(60)
def dashboard(
    pagina: int = 1,
    tamanho_pagina: int = 25,
    busca: str | None = None,
    faixa: str | None = None,
    ordenar_por: str = "score",
    ordenar_dir: str = "asc",
    periodo: str = "tudo",
):
    """
    Carteira paginada, lida direto do cache (carteira_atual). O `periodo`
    (mes | 6m | tudo, padrão tudo) define o intervalo de emissão usado nas
    métricas Maior compra e Maior atraso hoje. O score, o limite e o valor em
    aberto não mudam com o período, porque são calculados sobre o histórico todo.
    """
    pagina = max(1, pagina)
    tamanho_pagina = max(1, min(100, tamanho_pagina))
    periodo = periodo_mod.normalizar(periodo)
    inicio = periodo_mod.data_inicio(periodo)

    # Só a página da tabela depende de paginação, busca e ordenação. O resumo e os
    # destaques ficam em cache próprio: trocar de página não recalcula nada disso.
    atualizado_em, resumo_geral, maiores_expostos = _resumo_base()
    destaques = _destaques(periodo)
    df_pagina, total = db.fetch_carteira_paginada(
        pagina=pagina,
        tamanho_pagina=tamanho_pagina,
        busca=busca,
        faixa=faixa,
        ordenar_por=ordenar_por,
        ordenar_dir=ordenar_dir,
    )
    total_paginas = max(1, -(-total // tamanho_pagina))  # ceil sem importar math

    clientes = clean_json(df_pagina)
    # métricas só dos clientes desta página (uma consulta, não a carteira toda)
    por_nome = {
        m["cliente"]: m
        for m in clean_json(metricas.fetch_metricas_clientes([c["cliente"] for c in clientes], inicio))
    }
    for c in clientes:
        m = por_nome.get(c["cliente"], {})
        c["maior_compra"] = m.get("maior_compra")
        c["maior_atraso_hoje"] = m.get("maior_atraso_hoje")

    return {
        "atualizado_em": atualizado_em,
        "total_clientes": total,
        "pagina": pagina,
        "tamanho_pagina": tamanho_pagina,
        "total_paginas": total_paginas,
        "periodo": periodo,
        "resumo_geral": resumo_geral,
        "maiores_expostos": clean_json(maiores_expostos),
        "destaques": destaques,
        "clientes": clientes,
    }


@router.get("/api/dashboard/visao-geral")
@cache.ttl_cache(60)
def dashboard_visao_geral():
    """Em aberto no mês, vencidos, recebido no mês e quebra por carteira
    (Plano de Conta do ERP) e por vendedor — ver visao_geral.py."""
    return visao_geral.calcular()


@router.get("/api/carteira/historico")
@cache.ttl_cache(60)
def historico_carteira():
    """Evolução do total em aberto dia a dia (para gráfico de tendência)."""
    return clean_json(db.fetch_snapshots_historico_df())


@router.get("/api/carteira/export")
def exportar_carteira():
    """Baixa a carteira atual (com score, limite sugerido e limite cadastrado) em .xlsx."""
    score_df = db.fetch_carteira_completa_df()

    colunas = {
        "cliente": "Cliente",
        "score": "Score",
        "faixa": "Faixa",
        "atraso_medio_dias": "Atraso médio (dias)",
        "pct_pago_em_atraso": "% pago em atraso",
        "tendencia": "Tendência",
        "valor_em_aberto": "Valor em aberto (R$)",
        "dias_vencido_max": "Dias vencido (máx.)",
        "limite_atual": "Limite cadastrado (R$)",
        "margem_limite_atual": "Margem s/ limite cadastrado (R$)",
        "limite_sugerido": "Limite sugerido (R$)",
        "margem_disponivel": "Margem s/ limite sugerido (R$)",
        "recomendacao_limite": "Recomendação",
    }
    colunas_existentes = [c for c in colunas if c in score_df.columns]
    df_export = score_df[colunas_existentes].rename(columns=colunas)

    buffer = io.BytesIO()
    df_export.to_excel(buffer, index=False, sheet_name="Carteira")
    buffer.seek(0)

    nome_arquivo = f"carteira_credito_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
