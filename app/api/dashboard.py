"""Dashboard: carteira paginada, visão geral (mês, vencidos, carteira, vendedores), histórico, exportação e recálculo."""
from __future__ import annotations

from datetime import date
import io

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import db
from app.core import cache
from app.core.serializacao import clean_json
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


@router.get("/api/dashboard")
@cache.ttl_cache(60)
def dashboard(
    pagina: int = 1,
    tamanho_pagina: int = 25,
    busca: str | None = None,
    faixa: str | None = None,
    ordenar_por: str = "score",
    ordenar_dir: str = "asc",
):
    """
    Carteira paginada, lida direto do cache (carteira_atual) — rápido
    mesmo com muitos clientes, porque a busca/ordenação roda no banco e só
    a página pedida chega no front. O resumo geral (total em aberto,
    contagem por faixa) e os maiores expostos ignoram a paginação de
    propósito: são sempre sobre a carteira inteira.
    """
    pagina = max(1, pagina)
    tamanho_pagina = max(1, min(100, tamanho_pagina))

    # as 4 leituras são independentes: em paralelo, o tempo é o da mais lenta
    (df_pagina, total), atualizado_em, resumo_geral, maiores_expostos = db.run_parallel(
        lambda: db.fetch_carteira_paginada(
            pagina=pagina,
            tamanho_pagina=tamanho_pagina,
            busca=busca,
            faixa=faixa,
            ordenar_por=ordenar_por,
            ordenar_dir=ordenar_dir,
        ),
        db.fetch_carteira_atualizada_em,
        db.fetch_resumo_geral,
        db.fetch_maiores_expostos,
    )
    total_paginas = max(1, -(-total // tamanho_pagina))  # ceil sem importar math

    return {
        "atualizado_em": atualizado_em,
        "total_clientes": total,
        "pagina": pagina,
        "tamanho_pagina": tamanho_pagina,
        "total_paginas": total_paginas,
        "resumo_geral": resumo_geral,
        "maiores_expostos": clean_json(maiores_expostos),
        "clientes": clean_json(df_pagina),
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
