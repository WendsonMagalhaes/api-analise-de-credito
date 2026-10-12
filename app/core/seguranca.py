"""Senhas (argon2id) e tokens de sessão (JWT assinado com segredo só do servidor)."""
from __future__ import annotations

import os
import re
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2id com os parâmetros padrão recomendados pela biblioteca.
_ph = PasswordHasher()

JWT_ALG = "HS256"
JWT_ISSUER = "credito-api"
JWT_TTL_S = int(os.environ.get("JWT_TTL_HORAS", "8")) * 3600

SENHA_MIN = 6
SENHA_MAX = 128  # teto: evita gastar CPU hasheando textos gigantes
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

_hash_falso: str | None = None


def _segredo() -> str:
    segredo = os.environ.get("JWT_SECRET", "")
    if len(segredo) < 32:
        raise RuntimeError(
            "JWT_SECRET ausente ou curto demais (mínimo 32 caracteres). "
            "Gere um com: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    return segredo


# ---------------------------------------------------------------- senhas
def hash_senha(senha: str) -> str:
    return _ph.hash(senha)


def verificar_senha(hash_guardado: str, senha: str) -> bool:
    try:
        return _ph.verify(hash_guardado, senha)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def gastar_tempo_falso(senha: str) -> None:
    """Quando o e-mail não existe, faz uma verificação de mentira para o tempo
    de resposta ser parecido com o de um e-mail que existe (evita descobrir
    quais e-mails estão cadastrados medindo a demora do login)."""
    global _hash_falso
    if _hash_falso is None:
        _hash_falso = _ph.hash("senha-falsa-apenas-para-igualar-o-tempo")
    verificar_senha(_hash_falso, senha)


def validar_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


def validar_forca_senha(senha: str) -> str | None:
    """Devolve a mensagem de erro, ou None se a senha é aceitável."""
    if len(senha) < SENHA_MIN:
        return f"A senha precisa ter pelo menos {SENHA_MIN} caracteres."
    if len(senha) > SENHA_MAX:
        return f"A senha pode ter no máximo {SENHA_MAX} caracteres."
    if not re.search(r"[A-Za-z]", senha) or not re.search(r"\d", senha):
        return "A senha precisa ter letras e números."
    if len(set(senha)) < 5:
        return "A senha é muito repetitiva."
    return None


# ---------------------------------------------------------------- tokens
def criar_token(usuario: dict) -> tuple[str, int]:
    """Devolve (token, segundos_de_validade). `ver` amarra o token à versão do
    usuário: trocar senha/papel/ativo incrementa a versão e derruba os tokens
    antigos."""
    agora = int(time.time())
    payload = {
        "iss": JWT_ISSUER,
        "sub": str(usuario["id"]),
        "papel": usuario["papel"],
        "ver": usuario["versao_token"],
        "iat": agora,
        "exp": agora + JWT_TTL_S,
    }
    return jwt.encode(payload, _segredo(), algorithm=JWT_ALG), JWT_TTL_S


def ler_token(token: str) -> dict | None:
    """Valida assinatura, emissor e validade. Qualquer problema vira None."""
    try:
        return jwt.decode(
            token,
            _segredo(),
            algorithms=[JWT_ALG],  # fixo: nunca aceita "none" nem outro algoritmo
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.PyJWTError:
        return None
