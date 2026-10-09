"""Acesso ao banco (PostgreSQL/Neon). `conexao` cuida do pool; os demais arquivos têm as consultas de cada tabela (`config` = parâmetros ajustáveis pelo analista).

O pacote reexporta tudo (`db.read_df`, `db.upsert_pagamentos`...), então o resto do sistema usa apenas `from app import db`."""
from __future__ import annotations

from app.db.conexao import (
    bulk_upsert,
    conn_ou_nova,
    fetch_all,
    get_conn,
    get_engine,
    init_db,
    read_df,
    run_parallel,
)
from app.db.titulos import (
    fetch_aberto_cliente_df,
    fetch_pagamentos_cliente_df,
    fetch_pagamentos_df,
    fetch_snapshots_historico_df,
    fetch_ultimo_snapshot_df,
    upsert_abertos,
    upsert_pagamentos,
)
from app.db.scores import (
    fetch_historico_score_cliente,
    fetch_score_snapshot_por_data,
    fetch_ultimas_duas_datas_snapshot,
    salvar_score_snapshot,
)
from app.db.carteira import (
    fetch_carteira_atualizada_em,
    fetch_carteira_cliente,
    fetch_carteira_completa_df,
    fetch_carteira_paginada,
    fetch_comparativo_carteira,
    fetch_maiores_expostos,
    fetch_resumo_geral,
    fetch_valor_em_aberto_df,
    salvar_carteira_atual,
)
from app.db.decisoes import (
    fetch_decisoes_cliente_df,
    fetch_decisoes_recentes_df,
    registrar_decisao,
)
from app.db.exclusoes import (
    adicionar_cliente_excluido,
    fetch_clientes_excluidos_df,
    fetch_clientes_excluidos_set,
    filtro_exclusao,
    remover_cliente_excluido,
)
from app.db.limites import (
    fetch_limite_atual_df,
    upsert_limite_atual,
)

__all__ = [
    "adicionar_cliente_excluido",
    "bulk_upsert",
    "conn_ou_nova",
    "fetch_aberto_cliente_df",
    "fetch_all",
    "fetch_carteira_atualizada_em",
    "fetch_carteira_cliente",
    "fetch_carteira_completa_df",
    "fetch_carteira_paginada",
    "fetch_clientes_excluidos_df",
    "fetch_clientes_excluidos_set",
    "fetch_comparativo_carteira",
    "fetch_decisoes_cliente_df",
    "fetch_decisoes_recentes_df",
    "fetch_historico_score_cliente",
    "fetch_limite_atual_df",
    "fetch_maiores_expostos",
    "fetch_pagamentos_cliente_df",
    "fetch_pagamentos_df",
    "fetch_resumo_geral",
    "fetch_score_snapshot_por_data",
    "fetch_snapshots_historico_df",
    "fetch_ultimas_duas_datas_snapshot",
    "fetch_ultimo_snapshot_df",
    "fetch_valor_em_aberto_df",
    "filtro_exclusao",
    "get_conn",
    "get_engine",
    "init_db",
    "read_df",
    "registrar_decisao",
    "remover_cliente_excluido",
    "run_parallel",
    "salvar_carteira_atual",
    "salvar_score_snapshot",
    "upsert_abertos",
    "upsert_limite_atual",
    "upsert_pagamentos",
]
