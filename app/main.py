"""Ponto de entrada da API: cria o app, configura middlewares e registra as rotas de `app/api/`.

Segurança:
  * Todas as rotas exigem token (JWT), exceto /api/auth/login e /api/health.
  * Não há CORS: o navegador nunca fala com esta API — quem fala é o servidor do
    front (proxy /api/backend). Qualquer site que tentar chamar a API por um
    navegador fica sem permissão de ler a resposta.
  * /docs e /openapi.json ficam desligados em produção.
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware

from app import db
from app.api import alertas, auth, clientes, codigo_cliente, configuracoes, creditos, dashboard, metricas_cliente, upload, usuarios
from app.core import cache
from app.core.autenticacao import exigir_admin, usuario_atual

EM_PRODUCAO = os.getenv("VERCEL_ENV") == "production" or os.getenv("AMBIENTE") == "producao"

app = FastAPI(
    title="Crédito Frios API",
    docs_url=None if EM_PRODUCAO else "/docs",
    redoc_url=None,
    openapi_url=None if EM_PRODUCAO else "/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=1024)

log_desempenho = logging.getLogger("desempenho")
LIMITE_LENTO_MS = int(os.getenv("LIMITE_LENTO_MS", "800"))


@app.middleware("http")
async def medir_tempo(request: Request, call_next):
    """Mede quanto cada requisição levou. Aparece no DevTools (cabeçalho Server-Timing)
    e, se passar de LIMITE_LENTO_MS, vai para o log (Vercel mostra nos logs da função)."""
    inicio = time.perf_counter()
    resposta = await call_next(request)
    ms = (time.perf_counter() - inicio) * 1000
    resposta.headers["Server-Timing"] = f"api;dur={ms:.0f}"
    if ms > LIMITE_LENTO_MS:
        log_desempenho.warning("lento %s %s %.0fms", request.method, request.url.path, ms)
    return resposta


@app.middleware("http")
async def invalidar_cache_em_escrita(request: Request, call_next):
    """Qualquer requisição que não seja leitura (upload, recálculo, decisão,
    aprovar reajuste, config...) limpa o cache de respostas — ver cache.py."""
    resposta = await call_next(request)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        cache.invalidar_tudo()
    return resposta


@app.middleware("http")
async def cabecalhos_de_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["Cache-Control"] = "no-store"  # dados financeiros: nada de cache em intermediários
    return resposta


db.init_db()

# Público: login (e /me, que exige token por conta própria).
app.include_router(auth.router)

# Protegidas: qualquer usuário ativo (perfil "leitura" só faz GET).
_protegido = [Depends(usuario_atual)]
app.include_router(alertas.router, dependencies=_protegido)
app.include_router(clientes.router, dependencies=_protegido)
app.include_router(metricas_cliente.router, dependencies=_protegido)
app.include_router(codigo_cliente.router, dependencies=_protegido)
app.include_router(creditos.router, dependencies=_protegido)
app.include_router(dashboard.router, dependencies=_protegido)
app.include_router(upload.router, dependencies=_protegido)

# Configurações do sistema: só administrador.
app.include_router(configuracoes.router, dependencies=[Depends(exigir_admin)])
app.include_router(usuarios.router, dependencies=[Depends(exigir_admin)])


@app.get("/api/health")
def health():
    return {"status": "ok"}
