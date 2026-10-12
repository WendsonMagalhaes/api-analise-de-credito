"""Login e "quem sou eu". É o único router público (sem token)."""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core import limite_tentativas, seguranca
from app.core import autenticacao
from app.core.autenticacao import usuario_atual
from app.db import usuarios

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("auth")

# Segredo que só o servidor do front conhece. Com ele, o front repassa o IP
# real de quem está logando (X-Client-IP). Sem ele, a API ignora esse cabeçalho,
# porque qualquer um poderia forjá-lo.
_SEGREDO_PROXY = os.environ.get("PROXY_SHARED_SECRET", "")


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    senha: str = Field(min_length=1, max_length=seguranca.SENHA_MAX)


# Mesma mensagem para e-mail inexistente, senha errada, conta inativa e conta
# bloqueada: quem tenta adivinhar não descobre qual dos casos aconteceu.
def _recusar() -> HTTPException:
    return HTTPException(401, "E-mail ou senha inválidos, ou conta temporariamente bloqueada.")


def _ip_confiavel(request: Request) -> str | None:
    if not _SEGREDO_PROXY:
        return None
    enviado = request.headers.get("x-proxy-secret", "")
    if not hmac.compare_digest(enviado.encode(), _SEGREDO_PROXY.encode()):
        return None
    ip = request.headers.get("x-client-ip", "").strip()
    return ip[:45] or None


@router.post("/login")
def login(dados: LoginInput, request: Request):
    email = dados.email.strip().lower()

    # Primeiro de tudo: conta a tentativa e recusa antes de tocar na senha.
    espera = limite_tentativas.verificar(email, _ip_confiavel(request))
    if espera is not None:
        log.warning("login bloqueado: excesso de tentativas")
        raise HTTPException(
            429,
            "Muitas tentativas. Aguarde alguns minutos e tente de novo.",
            headers={"Retry-After": str(espera)},
        )

    u = usuarios.buscar_por_email(dados.email)

    if not u:
        seguranca.gastar_tempo_falso(dados.senha)
        log.warning("login recusado: e-mail desconhecido")
        raise _recusar()

    if u["bloqueado"]:
        # Conta bloqueada: nem confere a senha (não dá para forçar durante o bloqueio).
        log.warning("login recusado: conta %s bloqueada", u["id"])
        raise _recusar()

    senha_ok = seguranca.verificar_senha(u["senha_hash"], dados.senha)
    if not senha_ok:
        usuarios.registrar_falha(u["id"])
        log.warning("login recusado: senha errada (conta %s)", u["id"])
        raise _recusar()
    if not u["ativo"]:
        log.warning("login recusado: conta %s inativa", u["id"])
        raise _recusar()

    usuarios.registrar_sucesso(u["id"])
    limite_tentativas.sucesso(email)
    token, expira_em_s = seguranca.criar_token(u)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expira_em_s,
        "usuario": {"id": u["id"], "email": u["email"], "nome": u["nome"], "papel": u["papel"]},
    }


@router.get("/me")
def me(u: dict = Depends(usuario_atual)):
    return {"id": u["id"], "email": u["email"], "nome": u["nome"], "papel": u["papel"]}


class PerfilInput(BaseModel):
    nome: str = Field(min_length=2, max_length=120)


class TrocarSenhaInput(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=seguranca.SENHA_MAX)
    senha_nova: str = Field(min_length=1, max_length=seguranca.SENHA_MAX)


@router.patch("/perfil")
def atualizar_perfil(dados: PerfilInput, u: dict = Depends(usuario_atual)):
    """O próprio usuário altera o nome dele (não derruba a sessão)."""
    atualizado = usuarios.atualizar_por_id(u["id"], nome=dados.nome.strip())
    return {
        "id": atualizado["id"],
        "email": atualizado["email"],
        "nome": atualizado["nome"],
        "papel": atualizado["papel"],
    }


@router.post("/trocar-senha")
def trocar_senha(dados: TrocarSenhaInput, u: dict = Depends(usuario_atual)):
    """Troca a própria senha. Exige a senha atual e usa o mesmo limite de tentativas do login.
    Depois da troca, todos os tokens do usuário (inclusive este) deixam de valer."""
    chave = f"troca:{u['id']}"
    espera = limite_tentativas.verificar(chave, None)
    if espera is not None:
        raise HTTPException(
            429,
            "Muitas tentativas. Aguarde alguns minutos e tente de novo.",
            headers={"Retry-After": str(espera)},
        )

    registro = usuarios.buscar_por_email(u["email"])
    if not registro or not seguranca.verificar_senha(registro["senha_hash"], dados.senha_atual):
        raise HTTPException(400, "A senha atual está incorreta.")

    erro = seguranca.validar_forca_senha(dados.senha_nova)
    if erro:
        raise HTTPException(422, erro)
    if seguranca.verificar_senha(registro["senha_hash"], dados.senha_nova):
        raise HTTPException(422, "A nova senha precisa ser diferente da atual.")

    usuarios.atualizar_por_id(u["id"], senha_hash=seguranca.hash_senha(dados.senha_nova))
    autenticacao.invalidar(u["id"])
    limite_tentativas.sucesso(chave)
    return {"ok": True}
