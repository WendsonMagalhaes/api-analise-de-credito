"""Ponto de entrada da API: cria o app, configura middlewares e registra as rotas de `app/api/`."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import db
from app.api import alertas, clientes, configuracoes, creditos, dashboard, upload
from app.core import cache

app = FastAPI(title="Crédito Frios API")

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    
    allow_origins=[
    "http://localhost:3000",
    "https://analise-de-credito-sigma.vercel.app",
],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def invalidar_cache_em_escrita(request: Request, call_next):
    """Qualquer requisição que não seja leitura (upload, recálculo, decisão,
    aprovar reajuste, config...) limpa o cache de respostas — ver cache.py."""
    resposta = await call_next(request)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        cache.invalidar_tudo()
    return resposta


db.init_db()

app.include_router(alertas.router)
app.include_router(clientes.router)
app.include_router(configuracoes.router)
app.include_router(creditos.router)
app.include_router(dashboard.router)
app.include_router(upload.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
