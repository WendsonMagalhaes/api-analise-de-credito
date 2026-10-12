"""Dependências do FastAPI que exigem um usuário autenticado.

Toda rota (exceto /api/auth/login e /api/health) passa por `usuario_atual`:
  1. exige "Authorization: Bearer <jwt>" com assinatura e validade corretas;
  2. confere no banco (cache de 30 s por processo) se o usuário continua ativo
     e se a versão do token ainda é a vigente;
  3. perfil "leitura" só pode fazer GET.
"""
from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import seguranca
from app.db import usuarios

_bearer = HTTPBearer(auto_error=False)

_METODOS_LEITURA = {"GET", "HEAD", "OPTIONS"}
# POSTs que só calculam (não gravam nada) e por isso o perfil "leitura" pode usar.
_POSTS_SEM_ESCRITA = ("/simulacao/what-if",)
# Ações da PRÓPRIA conta (nome e senha): qualquer perfil pode fazer, inclusive "leitura".
_ESCRITAS_DA_PROPRIA_CONTA = ("/api/auth/perfil", "/api/auth/trocar-senha")

_TTL_CACHE_S = 30
_cache: dict[int, tuple[float, dict | None]] = {}


def _nao_autenticado() -> HTTPException:
    return HTTPException(401, "Não autenticado.", headers={"WWW-Authenticate": "Bearer"})


def invalidar(uid: int) -> None:
    """Esquece o cache deste usuário: a próxima requisição relê o banco.
    Chamar sempre que papel, status ou senha mudarem, para o efeito ser imediato."""
    _cache.pop(uid, None)


def _carregar(uid: int) -> dict | None:
    agora = time.monotonic()
    hit = _cache.get(uid)
    if hit and agora - hit[0] < _TTL_CACHE_S:
        return hit[1]
    u = usuarios.buscar_por_id(uid)
    _cache[uid] = (agora, u)
    return u


def usuario_atual(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if cred is None or cred.scheme.lower() != "bearer":
        raise _nao_autenticado()

    dados = seguranca.ler_token(cred.credentials)
    if not dados:
        raise _nao_autenticado()
    try:
        uid = int(dados["sub"])
    except (KeyError, ValueError):
        raise _nao_autenticado()

    u = _carregar(uid)
    if not u or not u["ativo"] or u["versao_token"] != dados.get("ver"):
        raise _nao_autenticado()

    if (
        u["papel"] == "leitura"
        and request.method not in _METODOS_LEITURA
        and not request.url.path.endswith(_POSTS_SEM_ESCRITA)
        and request.url.path not in _ESCRITAS_DA_PROPRIA_CONTA
    ):
        raise HTTPException(403, "Seu perfil é somente leitura.")
    return u


def exigir_admin(u: dict = Depends(usuario_atual)) -> dict:
    if u["papel"] != "admin":
        raise HTTPException(403, "Apenas administradores.")
    return u
