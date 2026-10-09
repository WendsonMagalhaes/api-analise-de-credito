"""Painel de créditos: aging, concentração, fluxo de caixa, reajustes de limite e reanálise."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import db
from app.core import cache
from app.core.serializacao import clean_json
from app.dominio import aging, alertas_preditivos, concentracao, fluxo_caixa, reajuste_limite, reanalise, velocidade
from app.schemas import DecisaoReajusteInput
from app.servicos.carteira import recalcular_e_salvar_carteira

router = APIRouter()


@router.post("/api/creditos/atualizar")
def atualizar_analise_credito():
    """
    Roda tudo que hoje depende de um job diário que ainda não tem
    agendador (velocidade, classificação A-E, tolerância, recomendação,
    alertas preditivos e gatilhos de reanálise). Enquanto não existir um
    cron/worker rodando isso sozinho todo dia, use este botão depois de
    cada upload (ou quando quiser forçar um recálculo fora do horário).
    """
    score_df = recalcular_e_salvar_carteira()
    novos_alertas = alertas_preditivos.rodar_job_diario()
    return {
        "clientes_recalculados": len(score_df),
        "novos_alertas_preditivos": len(novos_alertas),
    }


@router.get("/api/creditos/painel")
@cache.ttl_cache(60)
def painel_credito():
    """
    Tudo que a tela única de créditos precisa, numa chamada só: aging da
    carteira, concentração de risco, projeção de fluxo de caixa,
    reajustes de limite pendentes e pendências de reanálise. Evita 5
    idas e vindas ao backend pra montar 1 página — e as 5 leituras ao banco
    rodam em paralelo.
    """
    abertos, vel, valores_em_aberto, reajustes, pendentes = db.run_parallel(
        lambda: db.fetch_ultimo_snapshot_df(sem_categorias_contabeis=True),
        velocidade.fetch_ultimo_indice_por_cliente,
        db.fetch_valor_em_aberto_df,
        reajuste_limite.fetch_pendentes,
        reanalise.fetch_pendentes,
    )
    abertos_com_aging = aging.anexar_aging(abertos)

    return {
        "aging_resumo": aging.resumo_por_faixa(abertos_com_aging),
        "concentracao": clean_json(concentracao.calcular_ranking(valores_em_aberto).head(10)),
        "fluxo_caixa": fluxo_caixa.projetar(abertos, vel),
        "reajustes_pendentes": clean_json(reajustes),
        "reanalise_pendentes": clean_json(pendentes),
    }


@router.get("/api/aging/resumo")
@cache.ttl_cache(60)
def aging_resumo():
    """Carteira em aberto agregada pelas faixas de % do prazo decorrido
    (inicial/intermediária/reta final/vencido)."""
    abertos = aging.anexar_aging(db.fetch_ultimo_snapshot_df(sem_categorias_contabeis=True))
    return aging.resumo_por_faixa(abertos)


@router.get("/api/reajustes-limite")
def listar_reajustes_pendentes():
    return clean_json(reajuste_limite.fetch_pendentes())


@router.post("/api/reajustes-limite/{reajuste_id}/aprovar")
def aprovar_reajuste(reajuste_id: int, payload: DecisaoReajusteInput):
    try:
        reajuste_limite.aprovar(reajuste_id, payload.aprovado_por)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/api/reajustes-limite/{reajuste_id}/rejeitar")
def rejeitar_reajuste(reajuste_id: int, payload: DecisaoReajusteInput):
    reajuste_limite.rejeitar(reajuste_id, payload.aprovado_por)
    return {"ok": True}


@router.get("/api/reanalise/agenda")
def reanalise_agenda():
    return clean_json(reanalise.fetch_agenda())


@router.get("/api/reanalise/pendentes")
def reanalise_pendentes():
    """Gatilhos por evento (uso excessivo de tolerância, queda de classe
    etc.) ou externos (protesto, negativação...) ainda não resolvidos."""
    return clean_json(reanalise.fetch_pendentes())


@router.post("/api/reanalise/{gatilho_id}/resolver")
def resolver_gatilho_reanalise(gatilho_id: int):
    reanalise.marcar_resolvido(gatilho_id)
    return {"ok": True}


@router.get("/api/concentracao-risco")
@cache.ttl_cache(60)
def concentracao_risco():
    ranking = concentracao.calcular_ranking(db.fetch_valor_em_aberto_df())
    return clean_json(ranking)


@router.get("/api/fluxo-caixa/projecao")
@cache.ttl_cache(60)
def fluxo_caixa_projecao():
    abertos, vel = db.run_parallel(
        lambda: db.fetch_ultimo_snapshot_df(sem_categorias_contabeis=True),
        velocidade.fetch_ultimo_indice_por_cliente,
    )
    return fluxo_caixa.projetar(abertos, vel)
