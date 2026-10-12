"""Gestão de usuários: só administradores. Protegida em main.py por exigir_admin."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core import seguranca
from app.core import autenticacao
from app.core.autenticacao import exigir_admin
from app.db import usuarios

router = APIRouter(prefix="/api/usuarios", tags=["usuarios"])

Papel = Literal["admin", "analista", "leitura"]


class NovoUsuario(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    nome: str = Field(min_length=2, max_length=120)
    senha: str = Field(min_length=1, max_length=seguranca.SENHA_MAX)
    papel: Papel = "analista"


class AlterarUsuario(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2, max_length=120)
    papel: Optional[Papel] = None
    ativo: Optional[bool] = None
    senha: Optional[str] = Field(default=None, min_length=1, max_length=seguranca.SENHA_MAX)


@router.get("")
def listar():
    return usuarios.listar()


@router.post("", status_code=201)
def criar(dados: NovoUsuario):
    if not seguranca.validar_email(dados.email):
        raise HTTPException(422, "E-mail inválido.")
    erro = seguranca.validar_forca_senha(dados.senha)
    if erro:
        raise HTTPException(422, erro)
    try:
        return usuarios.criar(dados.email, dados.nome, seguranca.hash_senha(dados.senha), dados.papel)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.patch("/{uid}")
def alterar(uid: int, dados: AlterarUsuario, admin: dict = Depends(exigir_admin)):
    alvo = usuarios.buscar_por_id(uid)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")

    # quem hoje é admin ativo e perderia esse acesso com esta mudança
    era_admin_ativo = alvo["papel"] == "admin" and alvo["ativo"]
    perde_admin = era_admin_ativo and (
        (dados.papel is not None and dados.papel != "admin") or dados.ativo is False
    )
    if perde_admin and alvo["id"] == admin["id"]:
        raise HTTPException(400, "Você não pode tirar o próprio acesso de administrador.")
    if perde_admin and usuarios.contar_admins_ativos() <= 1:
        raise HTTPException(400, "Precisa existir pelo menos um administrador ativo.")

    senha_hash = None
    if dados.senha is not None:
        erro = seguranca.validar_forca_senha(dados.senha)
        if erro:
            raise HTTPException(422, erro)
        senha_hash = seguranca.hash_senha(dados.senha)

    atualizado = usuarios.atualizar_por_id(
        uid,
        nome=dados.nome.strip() if dados.nome else None,
        papel=dados.papel,
        ativo=dados.ativo,
        senha_hash=senha_hash,
    )
    autenticacao.invalidar(uid)
    return atualizado
