"""
Integração com IA (Groq — https://groq.com, roda modelos abertos como
Llama numa infraestrutura própria super rápida, com API gratuita) pra
ajudar na análise qualitativa do histórico do cliente — um texto que
complementa o score numérico, útil como um segundo ponto de vista antes de
bater o martelo numa decisão de crédito. É sob demanda (o analista clica
um botão na tela do cliente), não roda automaticamente em toda visita à
página.

IMPORTANTE: Groq (com "q", esse aqui) é diferente do Grok da xAI (com "k",
o chatbot do Elon Musk) — são empresas diferentes. O Groq tem API key
gratuita (com limite de taxa, mas suficiente pra esse uso sob demanda:
30 req/min e 1.000 req/dia no plano free, folgado pra um analista clicando
o botão ocasionalmente); o Grok da xAI cobra por token.

Precisa da variável de ambiente GROQ_API_KEY (gerada em
https://console.groq.com/keys, é só criar conta, sem cartão de crédito).
Sem ela configurada, o endpoint retorna um erro claro em vez de travar o
resto do sistema — o resto do app funciona normalmente sem essa chave.

A API do Groq é compatível com o formato da OpenAI (POST
/openai/v1/chat/completions, Authorization: Bearer <chave>). Em vez de
um único modelo fixo, tentamos uma LISTA de modelos em ordem — se um
estourar o limite de taxa/tokens do plano gratuito (HTTP 429) ou sair
de linha (404), a gente cai automaticamente pro próximo da lista, sem
o analista perceber. Configure com a variável GROQ_MODELS, separada
por vírgula (ex.: "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b").
Sem essa variável, usa a lista padrão abaixo. A antiga variável
GROQ_MODEL (singular) ainda funciona e, se definida, entra como
primeira opção da lista. Vale checar de vez em quando
https://console.groq.com/docs/models — o catálogo muda com frequência
e modelos saem de linha (ex.: o antigo "llama-3.3-70b-versatile" foi
descontinuado em 2026).
"""
from __future__ import annotations

import os

import httpx

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Lista padrão de fallback — todos ativos no catálogo Groq em set/2026.
# gpt-oss-120b é o mais forte (mais lento/mais caro em tokens), os
# seguintes são mais leves e servem de rede de segurança quando o
# primeiro estoura limite de taxa.
_MODELOS_PADRAO = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]


def _montar_lista_modelos() -> list[str]:
    """Monta a ordem de tentativa: GROQ_MODELS (csv) > GROQ_MODEL (legado,
    entra na frente) > lista padrão. Remove duplicatas mantendo a ordem."""
    modelos: list[str] = []

    bruto = os.environ.get("GROQ_MODELS")
    if bruto:
        modelos.extend(m.strip() for m in bruto.split(",") if m.strip())

    legado = os.environ.get("GROQ_MODEL")
    if legado:
        modelos.insert(0, legado.strip())

    if not modelos:
        modelos = list(_MODELOS_PADRAO)

    vistos = set()
    ordenados = []
    for m in modelos:
        if m not in vistos:
            vistos.add(m)
            ordenados.append(m)
    return ordenados


MODELOS = _montar_lista_modelos()

PROMPT_SISTEMA = (
    "Você é um assistente que ajuda um analista de crédito de uma "
    "distribuidora de frios a decidir se libera mais crédito para um "
    "cliente. Você recebe o histórico de pagamentos, os títulos em "
    "aberto, o score já calculado pelo sistema e as decisões de crédito "
    "anteriores. Responda em português, em até 6 frases, direto ao "
    "ponto: diga se parece seguro liberar mais crédito, quais riscos "
    "chamam mais atenção, e o que você recomendaria observar antes de "
    "decidir. Não invente dado que não esteja no resumo enviado, e não "
    "repita os números crus — interprete-os."
)


def _montar_resumo_texto(
    cliente: str,
    resumo: dict | None,
    historico_pagamentos: list[dict],
    titulos_em_aberto: list[dict],
    decisoes: list[dict],
) -> str:
    linhas = [f"Cliente: {cliente}"]

    if resumo:
        linhas.append(
            "Score atual: {score} ({faixa}). Atraso médio: {atraso} dias. "
            "% pago em atraso: {pct_atraso}%. Tendência: {tendencia}. "
            "Em aberto hoje: R$ {aberto}. Dias vencido (máx.): {vencido}. "
            "Limite sugerido pelo score: {limite_sugerido}. Margem sobre o "
            "sugerido: {margem_sugerido}. Limite cadastrado no ERP: "
            "{limite_atual}. Margem sobre o limite cadastrado: "
            "{margem_atual}.".format(
                score=resumo.get("score"),
                faixa=resumo.get("faixa"),
                atraso=resumo.get("atraso_medio_dias"),
                pct_atraso=resumo.get("pct_pago_em_atraso"),
                tendencia=resumo.get("tendencia"),
                aberto=resumo.get("valor_em_aberto"),
                vencido=resumo.get("dias_vencido_max"),
                limite_sugerido=resumo.get("limite_sugerido"),
                margem_sugerido=resumo.get("margem_disponivel"),
                limite_atual=resumo.get("limite_atual"),
                margem_atual=resumo.get("margem_limite_atual"),
            )
        )

    if historico_pagamentos:
        recentes = historico_pagamentos[:10]
        linhas.append(f"Últimos pagamentos ({len(recentes)} mais recentes):")
        for p in recentes:
            linhas.append(
                f"  - venceu {p.get('data_vencimento')}, pago {p.get('data_pagamento')}, "
                f"valor R$ {p.get('valor_pago')}"
            )

    if titulos_em_aberto:
        linhas.append(f"Títulos em aberto hoje ({len(titulos_em_aberto)}):")
        for t in titulos_em_aberto[:10]:
            linhas.append(f"  - vence {t.get('data_vencimento')}, valor R$ {t.get('valor')}")

    if decisoes:
        linhas.append("Decisões de crédito anteriores (mais recentes primeiro):")
        for d in decisoes[:5]:
            linhas.append(
                f"  - {d.get('criado_em')}: {d.get('tipo')}, valor aprovado "
                f"R$ {d.get('valor_aprovado')}, obs: {d.get('observacao') or '—'}"
            )

    return "\n".join(linhas)


async def gerar_analise(
    cliente: str,
    resumo: dict | None,
    historico_pagamentos: list[dict],
    titulos_em_aberto: list[dict],
    decisoes: list[dict],
) -> tuple[str, str]:
    """Devolve (texto_da_analise, modelo_que_respondeu). Tenta cada modelo
    de MODELOS em ordem; se um estourar limite de taxa (429) ou não
    existir mais (404), cai pro próximo automaticamente."""
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY não está configurada. Crie uma conta gratuita em "
            "https://console.groq.com, gere uma chave em "
            "https://console.groq.com/keys e coloque em backend/.env "
            "(ver .env.example)."
        )

    resumo_texto = _montar_resumo_texto(
        cliente, resumo, historico_pagamentos, titulos_em_aberto, decisoes
    )

    erros: list[str] = []

    async with httpx.AsyncClient(timeout=30) as client:
        for modelo in MODELOS:
            payload = {
                "model": modelo,
                "messages": [
                    {"role": "system", "content": PROMPT_SISTEMA},
                    {"role": "user", "content": resumo_texto},
                ],
                "temperature": 0.3,
            }

            try:
                resp = await client.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.RequestError as e:
                erros.append(f"{modelo}: não consegui falar com a API do Groq ({e}).")
                continue

            # 429 = estourou limite de taxa/tokens do plano; 404 = modelo saiu
            # de linha ou não existe na conta — nos dois casos, tenta o
            # próximo modelo da lista em vez de falhar pro analista.
            if resp.status_code in (429, 404):
                erros.append(f"{modelo}: HTTP {resp.status_code} — {resp.text[:150]}")
                continue

            if resp.status_code != 200:
                erros.append(f"{modelo}: HTTP {resp.status_code} — {resp.text[:150]}")
                continue

            dados = resp.json()
            try:
                texto = dados["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, TypeError):
                erros.append(f"{modelo}: resposta em formato inesperado.")
                continue

            return texto, modelo

    detalhe = " | ".join(erros) if erros else "nenhum motivo registrado"
    raise RuntimeError(
        f"Todos os modelos configurados falharam (tentei: {', '.join(MODELOS)}). {detalhe}"
    )
