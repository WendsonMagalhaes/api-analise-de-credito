"""
Migrations aditivas para as funcionalidades novas do score de crédito
(prazo variável por título, aging proporcional, velocidade de pagamento,
classificação de risco A-E, alertas preditivos, reajuste de limite,
margem de tolerância, reanálise, what-if, concentração de risco, fluxo
de caixa projetado, score duplo + motor de recomendação, sazonalidade).

Cada migration é (id, descrição, sql). Regra de ouro: uma migration já
aplicada em produção NUNCA é editada — para mudar algo, cria-se uma
nova migration. São aplicadas em ordem, uma única vez cada, e o
controle fica na tabela schema_migrations (não confundir com o SCHEMA
"de sempre" do db.py, que continua rodando do mesmo jeito por ser só
CREATE TABLE IF NOT EXISTS idempotente).

Nenhuma migration aqui altera coluna existente ou remove dado — só
adiciona tabela/coluna nova, seguindo a restrição de "migrations
aditivas" pedida.
"""
from __future__ import annotations

MIGRATIONS: list[tuple[str, str, str]] = [
    (
        "0001_configuracoes",
        "Tabela genérica de parâmetros configuráveis (evita hardcode) + seed dos valores padrão",
        """
        CREATE TABLE IF NOT EXISTS configuracoes (
            chave TEXT PRIMARY KEY,
            valor JSONB NOT NULL,
            descricao TEXT,
            atualizado_em TIMESTAMP DEFAULT NOW()
        );

        INSERT INTO configuracoes (chave, valor, descricao) VALUES
            ('prazos_permitidos_dias', '[8, 14, 21]',
             'Prazos de boleto válidos. 21 é o teto máximo, não o padrão — prazo real é sempre o do título.'),
            ('alertas_preditivos_percentuais', '[50, 85]',
             'Percentuais do prazo decorrido que disparam alerta preditivo (além do vencimento em si, 100%).'),
            ('tolerancia_percentual_por_classe', '{"A": 15, "B": 8, "C": 3, "D": 0, "E": 0}',
             'Margem de tolerância acima do limite, em % do limite atual, por classe de risco (5 níveis).'),
            ('tolerancia_classe_b_atraso_medio_max_dias', '5',
             'Classe B só recebe tolerância se o atraso médio do cliente for menor que este valor.'),
            ('tolerancia_classe_c_valor_maximo', '500',
             'Classe C só recebe tolerância para saldos de baixo valor — teto em R$ por liberação.'),
            ('tolerancia_teto_carteira_pct', '5',
             'Teto de proteção: a tolerância nunca pode levar o saldo de um cliente a ultrapassar esse % da carteira total em aberto.'),
            ('reajuste_percentual_maximo_por_classe', '{"A": 20, "B": 10}',
             'Aumento máximo de limite por revisão, em % do limite atual, por classe (só A e B são elegíveis).'),
            ('reajuste_ciclo_dias_por_classe', '{"A": 90, "B": 120}',
             'Intervalo mínimo entre revisões de aumento de limite, em dias, por classe.'),
            ('reajuste_teto_absoluto_valor', 'null',
             'Teto absoluto em R$ de aumento por revisão, além do percentual. null = sem teto absoluto configurado.'),
            ('reajuste_velocidade_media_maxima', '0.7',
             'Velocidade de pagamento média (índice) máxima para elegibilidade de reajuste — acima disso, cliente não é considerado rápido o suficiente.'),
            ('reajuste_minimo_ciclos_completos', '3',
             'Quantidade mínima de ciclos completos de compra/pagamento para elegibilidade de reajuste.'),
            ('reanalise_intervalo_meses_por_classe', '{"A": 6, "B": 4, "C": 2, "D": 1, "E": 1}',
             'De quanto em quanto tempo (meses) cada classe deve passar por reanálise de crédito agendada.'),
            ('reanalise_gatilho_uso_tolerancia_max_trimestre', '2',
             'Mais de N usos de tolerância no trimestre dispara gatilho de reanálise fora do calendário.'),
            ('concentracao_risco_alerta_pct', '15',
             'Alerta quando um único cliente ultrapassa esse % do saldo total em aberto da carteira.'),
            ('velocidade_media_movel_janela_titulos', '10',
             'Quantidade de títulos pagos mais recentes considerados na média móvel do índice de velocidade por cliente.')
        ON CONFLICT (chave) DO NOTHING;
        """,
    ),
    (
        "0002_prazo_do_titulo",
        "Coluna prazo_do_titulo (variável por título) em pagamentos e abertos_snapshot, com backfill",
        """
        ALTER TABLE pagamentos ADD COLUMN IF NOT EXISTS prazo_do_titulo INTEGER;
        ALTER TABLE abertos_snapshot ADD COLUMN IF NOT EXISTS prazo_do_titulo INTEGER;

        UPDATE pagamentos
           SET prazo_do_titulo = (data_vencimento - data_emissao)
         WHERE prazo_do_titulo IS NULL
           AND data_vencimento IS NOT NULL
           AND data_emissao IS NOT NULL;

        UPDATE abertos_snapshot
           SET prazo_do_titulo = (data_vencimento - data_emissao)
         WHERE prazo_do_titulo IS NULL
           AND data_vencimento IS NOT NULL
           AND data_emissao IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_abertos_prazo ON abertos_snapshot(prazo_do_titulo);
        """,
    ),
    (
        "0003_velocidade_pagamento_snapshot",
        "Histórico (append-only) da média móvel do índice de velocidade de pagamento por cliente",
        """
        CREATE TABLE IF NOT EXISTS velocidade_pagamento_snapshot (
            id SERIAL PRIMARY KEY,
            cliente TEXT NOT NULL,
            data_captura DATE NOT NULL,
            indice_medio_movel NUMERIC,
            qtd_titulos_considerados INTEGER,
            criado_em TIMESTAMP DEFAULT NOW(),
            UNIQUE (cliente, data_captura)
        );
        CREATE INDEX IF NOT EXISTS idx_velocidade_cliente ON velocidade_pagamento_snapshot(cliente);
        """,
    ),
    (
        "0004_classificacao_snapshot",
        "Histórico (append-only) da classificação de risco nova de 5 níveis (A-E), separada da faixa verde/amarelo/vermelho",
        """
        CREATE TABLE IF NOT EXISTS classificacao_snapshot (
            id SERIAL PRIMARY KEY,
            cliente TEXT NOT NULL,
            data_captura DATE NOT NULL,
            classe TEXT NOT NULL CHECK (classe IN ('A', 'B', 'C', 'D', 'E')),
            score_comportamento NUMERIC,
            score_exposicao NUMERIC,
            score_composto NUMERIC,
            criterio JSONB,
            criado_em TIMESTAMP DEFAULT NOW(),
            UNIQUE (cliente, data_captura)
        );
        CREATE INDEX IF NOT EXISTS idx_classificacao_cliente ON classificacao_snapshot(cliente);
        """,
    ),
    (
        "0005_alertas_prazo_disparados",
        "Idempotência dos alertas preditivos escalonados (50%/85%/vencimento) por título",
        """
        CREATE TABLE IF NOT EXISTS alertas_prazo_disparados (
            id SERIAL PRIMARY KEY,
            chave_natural TEXT NOT NULL,
            cliente TEXT NOT NULL,
            tipo_alerta TEXT NOT NULL,
            pct_decorrido_no_disparo NUMERIC,
            disparado_em TIMESTAMP DEFAULT NOW(),
            UNIQUE (chave_natural, tipo_alerta)
        );
        CREATE INDEX IF NOT EXISTS idx_alertas_prazo_cliente ON alertas_prazo_disparados(cliente);
        """,
    ),
    (
        "0006_reajustes_limite",
        "Sugestões de aumento gradual de limite (auditável), com aprovação manual",
        """
        CREATE TABLE IF NOT EXISTS reajustes_limite (
            id SERIAL PRIMARY KEY,
            cliente TEXT NOT NULL,
            classe TEXT NOT NULL,
            limite_anterior NUMERIC NOT NULL,
            limite_sugerido NUMERIC NOT NULL,
            percentual_aplicado NUMERIC NOT NULL,
            teto_absoluto_aplicado BOOLEAN DEFAULT FALSE,
            status TEXT NOT NULL DEFAULT 'sugerido',
            motivo JSONB,
            sugerido_em TIMESTAMP DEFAULT NOW(),
            decidido_em TIMESTAMP,
            aprovado_por TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reajustes_cliente ON reajustes_limite(cliente);
        CREATE INDEX IF NOT EXISTS idx_reajustes_status ON reajustes_limite(status);
        """,
    ),
    (
        "0007_tolerancia_eventos",
        "Auditoria de toda liberação acima do limite formal, mesmo dentro da tolerância",
        """
        CREATE TABLE IF NOT EXISTS tolerancia_eventos (
            id SERIAL PRIMARY KEY,
            cliente TEXT NOT NULL,
            data_captura DATE NOT NULL,
            classe TEXT,
            limite_atual NUMERIC,
            tolerancia_pct NUMERIC,
            valor_maximo_liberado NUMERIC,
            valor_em_aberto NUMERIC,
            valor_acima_do_limite NUMERIC,
            criado_em TIMESTAMP DEFAULT NOW(),
            UNIQUE (cliente, data_captura)
        );
        CREATE INDEX IF NOT EXISTS idx_tolerancia_cliente ON tolerancia_eventos(cliente);
        """,
    ),
    (
        "0008_clientes_metadata_e_reanalise",
        "Metadados por cliente (próxima reanálise) e log de gatilhos de reanálise",
        """
        CREATE TABLE IF NOT EXISTS clientes_metadata (
            cliente TEXT PRIMARY KEY,
            data_proxima_reanalise DATE,
            classe_atual TEXT,
            atualizado_em TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS reanalise_gatilhos (
            id SERIAL PRIMARY KEY,
            cliente TEXT NOT NULL,
            tipo_gatilho TEXT NOT NULL,
            detalhes JSONB,
            resolvido BOOLEAN DEFAULT FALSE,
            criado_em TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_reanalise_gatilhos_cliente ON reanalise_gatilhos(cliente);
        CREATE INDEX IF NOT EXISTS idx_reanalise_gatilhos_resolvido ON reanalise_gatilhos(resolvido);
        """,
    ),
    (
        "0009_periodos_sazonais",
        "Cadastro de períodos sazonais para não penalizar atraso pontual de pico de demanda",
        """
        CREATE TABLE IF NOT EXISTS periodos_sazonais (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            data_inicio DATE NOT NULL,
            data_fim DATE NOT NULL,
            criado_em TIMESTAMP DEFAULT NOW()
        );
        """,
    ),
    (
        "0010_carteira_atual_score_duplo",
        "Colunas novas no cache carteira_atual para o score duplo e a recomendação de ação",
        """
        ALTER TABLE carteira_atual ADD COLUMN IF NOT EXISTS score_comportamento NUMERIC;
        ALTER TABLE carteira_atual ADD COLUMN IF NOT EXISTS score_exposicao NUMERIC;
        ALTER TABLE carteira_atual ADD COLUMN IF NOT EXISTS classe_risco_5 TEXT;
        ALTER TABLE carteira_atual ADD COLUMN IF NOT EXISTS recomendacao_acao TEXT;
        ALTER TABLE carteira_atual ADD COLUMN IF NOT EXISTS regra_recomendacao TEXT;
        """,
    ),
    (
        "0011_indices_de_desempenho",
        "Índices para as consultas mais frequentes (detalhe do cliente, pendências, decisões recentes)",
        """
        CREATE INDEX IF NOT EXISTS idx_pagamentos_cliente_data ON pagamentos(cliente, data_pagamento);
        CREATE INDEX IF NOT EXISTS idx_abertos_cliente_captura ON abertos_snapshot(cliente, data_captura);
        CREATE INDEX IF NOT EXISTS idx_reanalise_gatilhos_abertos
            ON reanalise_gatilhos(cliente, tipo_gatilho) WHERE resolvido = FALSE;
        CREATE INDEX IF NOT EXISTS idx_decisoes_criado_em ON decisoes_credito(criado_em DESC);
        CREATE INDEX IF NOT EXISTS idx_alertas_prazo_disparado_em ON alertas_prazo_disparados(disparado_em DESC);
        CREATE INDEX IF NOT EXISTS idx_reajustes_cliente_sugerido ON reajustes_limite(cliente, sugerido_em DESC);
        """,
    ),
    (
        "0012_conta_e_plano_de_conta_nos_abertos",
        "Guarda Conta (carteira) e Plano de Conta dos títulos em aberto + índice por data de pagamento (dashboard por carteira/vendedor)",
        """
        ALTER TABLE abertos_snapshot ADD COLUMN IF NOT EXISTS plano_conta TEXT;
        ALTER TABLE abertos_snapshot ADD COLUMN IF NOT EXISTS conta TEXT;
        CREATE INDEX IF NOT EXISTS idx_pagamentos_data_pagamento ON pagamentos(data_pagamento);
        """,
    ),
    (
        "0013_usuarios",
        "Usuários do sistema: login, perfil (admin/analista/leitura), bloqueio por tentativas e invalidação de sessões",
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            nome TEXT NOT NULL,
            senha_hash TEXT NOT NULL,
            papel TEXT NOT NULL DEFAULT 'analista'
                CHECK (papel IN ('admin', 'analista', 'leitura')),
            ativo BOOLEAN NOT NULL DEFAULT TRUE,
            tentativas_falhas INTEGER NOT NULL DEFAULT 0,
            bloqueado_ate TIMESTAMPTZ,
            versao_token INTEGER NOT NULL DEFAULT 1,
            criado_em TIMESTAMP DEFAULT NOW(),
            ultimo_login TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_usuarios_email ON usuarios (LOWER(email));
        """,
    ),
]


def aplicar_migrations(conn) -> list[str]:
    """Aplica, em ordem, toda migration ainda não registrada em
    schema_migrations. Idempotente: seguro rodar a cada início da API."""
    aplicadas = []
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                descricao TEXT,
                aplicada_em TIMESTAMP DEFAULT NOW()
            )
            """
        )
        cur.execute("SELECT id FROM schema_migrations")
        ja_aplicadas = {r["id"] for r in cur.fetchall()}

        for id_, descricao, sql in MIGRATIONS:
            if id_ in ja_aplicadas:
                continue
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (id, descricao) VALUES (%(id)s, %(d)s)",
                {"id": id_, "d": descricao},
            )
            aplicadas.append(id_)
    conn.commit()
    return aplicadas
