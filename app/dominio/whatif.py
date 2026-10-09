"""
Simulação "what-if" de novo pedido: função pura, não grava nada no
banco (só lê o estado atual do cliente). Serve pra o analista testar
"e se eu liberar mais R$ X pra esse cliente agora?" sem afetar nenhum
histórico.
"""
from __future__ import annotations

from app.dominio import tolerancia


def simular_novo_pedido(
    valor_pedido: float,
    limite_atual: float | None,
    valor_em_aberto: float,
    classe: str | None,
    atraso_medio_dias: float | None,
    valor_total_carteira: float,
    score_composto: float | None,
) -> dict:
    novo_saldo = round(valor_em_aberto + valor_pedido, 2)

    if limite_atual is None or not classe:
        return {
            "novo_saldo_em_aberto": novo_saldo,
            "novo_pct_utilizacao": None,
            "impacto_estimado_score": None,
            "observacao": "Cliente sem limite cadastrado e/ou classe de risco — não é possível estimar utilização/impacto.",
        }

    calculo_tolerancia = tolerancia.calcular_valor_maximo_liberado(
        limite_atual, classe, atraso_medio_dias, valor_em_aberto, valor_total_carteira
    )
    valor_maximo_liberado = calculo_tolerancia["valor_maximo_liberado"]

    novo_pct_utilizacao = (
        round((novo_saldo / valor_maximo_liberado) * 100, 1) if valor_maximo_liberado else None
    )

    # Impacto estimado no score: heurística simples e conservadora — usa
    # o quanto a exposição cresceria proporcionalmente ao teto liberável.
    # Não é o score real recalculado (isso exigiria rodar todo o pipeline
    # de scoring/classificação) — é uma ESTIMATIVA rápida pra orientar a
    # decisão antes de gravar o pedido de verdade.
    impacto = None
    if score_composto is not None and valor_maximo_liberado:
        delta_utilizacao_pct = ((novo_saldo - valor_em_aberto) / valor_maximo_liberado) * 100
        impacto = round(-delta_utilizacao_pct * 0.15, 1)  # cada 1pp de utilização a mais custa ~0.15 ponto de score

    return {
        "novo_saldo_em_aberto": novo_saldo,
        "novo_pct_utilizacao": novo_pct_utilizacao,
        "valor_maximo_liberado_considerando_tolerancia": valor_maximo_liberado,
        "ultrapassa_limite_com_tolerancia": novo_saldo > valor_maximo_liberado,
        "impacto_estimado_score": impacto,
        "observacao": None,
    }
