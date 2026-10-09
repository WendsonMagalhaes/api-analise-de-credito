"""
Motor de recomendação: cruza o score duplo (comportamento x exposição)
com o status de limite/tolerância e devolve uma decisão sugerida, SEMPRE
com a regra que gerou a recomendação — pra servir de justificativa
auditável, nunca uma "caixa preta".

Ordem de avaliação (a primeira regra que bater decide):
  1. classe E, ou título vencido com aging "vencido" há mais de um ciclo
     inteiro → negar
  2. classe D, ou já ultrapassou o valor_maximo_liberado (mesmo com
     tolerância) → exigir garantia
  3. margem sobre o limite atual apertada (< 10% do limite livre) ou
     classe C → aprovar com limite reduzido
  4. caso contrário (classes A/B com margem saudável) → aprovar
"""
from __future__ import annotations


def recomendar(
    classe: str | None,
    dias_vencido_max: int,
    valor_em_aberto: float,
    limite_atual: float | None,
    valor_maximo_liberado: float | None,
    margem_limite_atual: float | None,
) -> dict:
    if classe == "E" or (dias_vencido_max or 0) > 21:
        return {
            "recomendacao": "negar",
            "regra": "Classe E ou título vencido há mais de um ciclo de prazo inteiro (>21 dias).",
        }

    if classe == "D" or (
        valor_maximo_liberado is not None and valor_em_aberto > valor_maximo_liberado
    ):
        return {
            "recomendacao": "exigir_garantia",
            "regra": "Classe D, ou saldo em aberto já ultrapassa o valor máximo liberável (limite + tolerância).",
        }

    margem_relativa = None
    if limite_atual and limite_atual > 0 and margem_limite_atual is not None:
        margem_relativa = margem_limite_atual / limite_atual

    if classe == "C" or (margem_relativa is not None and margem_relativa < 0.10):
        return {
            "recomendacao": "aprovar_com_limite_reduzido",
            "regra": "Classe C, ou margem livre sobre o limite atual abaixo de 10%.",
        }

    return {
        "recomendacao": "aprovar",
        "regra": "Classe A ou B, sem título vencido crítico e com margem saudável sobre o limite atual.",
    }
