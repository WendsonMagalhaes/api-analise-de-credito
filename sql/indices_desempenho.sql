-- Rode no SQL do Neon, UMA instrução por vez (CREATE INDEX CONCURRENTLY não roda em transação).
-- Não bloqueia leituras nem escritas enquanto cria. Pode levar alguns minutos nas tabelas grandes.

-- Destaques (maior compra / maior atraso) filtram por período de emissão
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pagamentos_emissao ON pagamentos (data_emissao);

-- Tela do cliente: histórico e métricas filtram por cliente + período
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pagamentos_cliente_emissao ON pagamentos (cliente, data_emissao);

-- Títulos em aberto: sempre pegam a última foto (data_captura) e filtram por cliente
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_abertos_captura_cliente ON abertos_snapshot (data_captura, cliente);

-- Decisões de crédito: histórico do cliente ordenado por data
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_decisoes_cliente_criado ON decisoes_credito (cliente, criado_em DESC);

-- Atualiza as estatísticas para o planejador usar os índices
ANALYZE pagamentos;
ANALYZE abertos_snapshot;
