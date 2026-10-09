# Crédito Frios — Backend

API em FastAPI + PostgreSQL (Neon) para análise de crédito da carteira de clientes.

## Como rodar

```bash
# dentro da pasta backend/, com o ambiente virtual ativado
pip install -r requirements.txt
uvicorn main:app --reload --port 8000        # (ou: uvicorn app.main:app --reload --port 8000)
```

A conexão vem da variável `DATABASE_URL`, lida do arquivo `backend/.env`:

```
DATABASE_URL=postgresql://usuario:senha@host/banco?sslmode=require
```

Ao subir, a API cria as tabelas e aplica as migrations pendentes sozinha.
Documentação interativa dos endpoints: `http://localhost:8000/docs`.

## Estrutura

```
backend/
├── main.py                  atalho: mantém o comando `uvicorn main:app`
├── requirements.txt
└── app/
    ├── main.py              cria o FastAPI, middlewares e registra as rotas
    ├── schemas.py           modelos de entrada das requisições (Pydantic)
    │
    ├── api/                 ROTAS HTTP — uma por assunto, sem regra de negócio
    │   ├── upload.py            envio dos relatórios do ERP
    │   ├── dashboard.py         dashboard, visão geral, histórico, exportação, recálculo
    │   ├── clientes.py          tudo de um cliente (detalhe, decisões, IA, aging, what-if…)
    │   ├── alertas.py           alertas de faixa e alertas preditivos de prazo
    │   ├── creditos.py          painel de créditos: aging, concentração, fluxo de caixa, reajustes, reanálise
    │   └── configuracoes.py     parâmetros, clientes excluídos, períodos sazonais
    │
    ├── servicos/            ORQUESTRAÇÃO — junta banco + regras + gravação
    │   └── carteira.py          recalcular_e_salvar_carteira, montar_detalhe_cliente
    │
    ├── dominio/             REGRAS DE NEGÓCIO de crédito
    │   ├── scoring.py  classificacao.py  velocidade.py  recomendacao.py
    │   ├── aging.py  fluxo_caixa.py  concentracao.py  visao_geral.py
    │   ├── tolerancia.py  reajuste_limite.py  reanalise.py  whatif.py
    │   └── alertas_preditivos.py  prazos.py  sazonalidade.py
    │
    ├── db/                  BANCO — um arquivo por assunto/tabela
    │   ├── conexao.py           pool, read_df, fetch_all, run_parallel, bulk_upsert (COPY), init_db
    │   ├── schema.py            DDL base;  migrations.py = alterações posteriores
    │   ├── titulos.py           pagamentos e abertos_snapshot
    │   ├── scores.py            histórico de score
    │   ├── carteira.py          carteira_atual e consultas do dashboard
    │   ├── decisoes.py  exclusoes.py  limites.py
    │   ├── config.py            parâmetros ajustáveis (tabela configuracoes)
    │   └── conversores.py       NaN/NaT do pandas -> tipos do banco
    │
    ├── ingestao/parser.py   leitura dos relatórios do ERP (HTML .xls, .xlsx, .csv)
    ├── integracoes/ia.py    análise qualitativa por IA
    └── core/                utilitários sem dependência de ninguém: cache, filtros, formatacao, serializacao, telemetria
```

### Regra de dependência

Cada camada só importa das que estão **abaixo** dela:

```
api  →  servicos  →  dominio  →  db  →  core
```

Ou seja: `dominio` nunca importa `api`; `db` nunca importa `dominio`; `core` não importa nada do app.
Isso evita import circular e deixa cada parte testável isolada.

## Onde colocar o que é novo

| Preciso de…                                  | Vai em…                                                                    |
|----------------------------------------------|----------------------------------------------------------------------------|
| Um novo endpoint                             | `api/<assunto>.py` (novo arquivo? registre em `app/main.py`)               |
| Corpo de requisição novo                     | `schemas.py`                                                               |
| Uma regra/cálculo de crédito                 | `dominio/<regra>.py`                                                       |
| Juntar várias regras + gravar                | `servicos/`                                                                |
| Uma consulta SQL                             | `db/<tabela>.py` e exporte em `db/__init__.py` (lista e `__all__`)          |
| Uma coluna/tabela nova                       | nova entrada em `db/migrations.py` (nunca edite uma migration já aplicada) |
| Um formato de número/texto                   | `core/formatacao.py` (pt-BR: vírgula decimal)                              |

## Convenções

- Imports absolutos a partir de `app` (`from app.dominio import scoring`).
- Banco: `from app import db` e `db.read_df(...)`, `db.upsert_pagamentos(...)` — a fachada em `db/__init__.py` reexporta as funções públicas.
- Rotas de leitura pesadas usam `@cache.ttl_cache(60)`; qualquer POST/PUT/DELETE limpa esse cache (middleware em `app/main.py`).
- Rotas são síncronas (`def`) de propósito: o FastAPI as roda em threads e o event loop não trava com pandas/banco.
