"""DDL base das tabelas (as alterações posteriores ficam em migrations.py)."""
from __future__ import annotations



SCHEMA = """
CREATE TABLE IF NOT EXISTS pagamentos (
    id SERIAL PRIMARY KEY,
    chave_natural TEXT UNIQUE,
    cliente TEXT NOT NULL,
    titulo TEXT,
    venda_numero INTEGER,
    parcela_num INTEGER,
    parcela_total INTEGER,
    vendedor TEXT,
    data_emissao DATE,
    data_vencimento DATE,
    valor NUMERIC,
    valor_pago NUMERIC,
    juros_multa NUMERIC,
    data_pagamento DATE,
    importado_em TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS abertos_snapshot (
    id SERIAL PRIMARY KEY,
    chave_natural TEXT UNIQUE,
    data_captura DATE NOT NULL,
    cliente TEXT NOT NULL,
    titulo TEXT,
    venda_numero INTEGER,
    parcela_num INTEGER,
    parcela_total INTEGER,
    vendedor TEXT,
    data_emissao DATE,
    data_vencimento DATE,
    valor NUMERIC,
    importado_em TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS score_snapshot (
    id SERIAL PRIMARY KEY,
    data_captura DATE NOT NULL,
    cliente TEXT NOT NULL,
    score INTEGER NOT NULL,
    faixa TEXT NOT NULL,
    valor_em_aberto NUMERIC,
    UNIQUE (data_captura, cliente)
);

CREATE TABLE IF NOT EXISTS decisoes_credito (
    id SERIAL PRIMARY KEY,
    cliente TEXT NOT NULL,
    tipo TEXT NOT NULL,
    valor_solicitado NUMERIC,
    valor_aprovado NUMERIC,
    prazo_dias INTEGER,
    score_no_momento INTEGER,
    faixa_no_momento TEXT,
    analista TEXT,
    observacao TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clientes_excluidos (
    id SERIAL PRIMARY KEY,
    cliente TEXT UNIQUE NOT NULL,
    motivo TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS limite_atual_cliente (
    cliente TEXT PRIMARY KEY,
    limite_atual NUMERIC,
    atualizado_em TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS carteira_atual (
    cliente TEXT PRIMARY KEY,
    qtd_titulos_pagos INTEGER,
    valor_total_pago NUMERIC,
    atraso_medio_dias NUMERIC,
    atraso_maximo_dias INTEGER,
    pct_pago_em_atraso NUMERIC,
    pct_pago_muito_atraso NUMERIC,
    tendencia TEXT,
    valor_em_aberto NUMERIC,
    qtd_titulos_aberto INTEGER,
    dias_vencido_max INTEGER,
    capacidade_mensal NUMERIC,
    limite_sugerido NUMERIC,
    margem_disponivel NUMERIC,
    limite_atual NUMERIC,
    margem_limite_atual NUMERIC,
    recomendacao_limite TEXT,
    score INTEGER,
    faixa TEXT,
    motivos JSONB,
    atualizado_em TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pagamentos_cliente ON pagamentos(cliente);
CREATE INDEX IF NOT EXISTS idx_abertos_cliente ON abertos_snapshot(cliente);
CREATE INDEX IF NOT EXISTS idx_abertos_captura ON abertos_snapshot(data_captura);
CREATE INDEX IF NOT EXISTS idx_score_snapshot_cliente ON score_snapshot(cliente);
CREATE INDEX IF NOT EXISTS idx_score_snapshot_data ON score_snapshot(data_captura);
CREATE INDEX IF NOT EXISTS idx_decisoes_cliente ON decisoes_credito(cliente);
CREATE INDEX IF NOT EXISTS idx_carteira_atual_score ON carteira_atual(score);
CREATE INDEX IF NOT EXISTS idx_carteira_atual_faixa ON carteira_atual(faixa);
CREATE INDEX IF NOT EXISTS idx_carteira_atual_valor_aberto ON carteira_atual(valor_em_aberto);
"""
