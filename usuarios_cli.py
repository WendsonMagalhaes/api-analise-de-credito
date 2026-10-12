"""Gestão de usuários pela linha de comando (não existe rota HTTP para isso).

Rode na pasta da API, com o DATABASE_URL do .env apontando para o banco:

    python usuarios_cli.py criar  --email ana@empresa.com --nome "Ana" --papel admin
    python usuarios_cli.py listar
    python usuarios_cli.py senha  --email ana@empresa.com      # redefine a senha (e destrava a conta)
    python usuarios_cli.py papel  --email ana@empresa.com --papel analista
    python usuarios_cli.py desativar --email ana@empresa.com   # derruba as sessões na hora
    python usuarios_cli.py ativar    --email ana@empresa.com

Perfis: admin (tudo + configurações), analista (lê e grava), leitura (só consulta).
A senha é pedida no terminal (não aparece na tela nem fica no histórico).
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app import db  # carrega o .env
from app.core import seguranca
from app.db import usuarios

PAPEIS = ("admin", "analista", "leitura")


def _pedir_senha() -> str:
    while True:
        s1 = getpass.getpass("Senha: ")
        erro = seguranca.validar_forca_senha(s1)
        if erro:
            print(erro)
            continue
        if s1 != getpass.getpass("Repita a senha: "):
            print("As senhas não conferem.")
            continue
        return s1


def _mostrar(u: dict | None) -> None:
    if not u:
        sys.exit("Usuário não encontrado.")
    print(f"#{u['id']}  {u['email']}  ({u['nome']})  papel={u['papel']}  ativo={u['ativo']}")


def main() -> None:
    p = argparse.ArgumentParser(description="Gestão de usuários")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("criar")
    c.add_argument("--email", required=True)
    c.add_argument("--nome", required=True)
    c.add_argument("--papel", choices=PAPEIS, default="analista")

    sub.add_parser("listar")
    for nome in ("senha", "ativar", "desativar"):
        sub.add_parser(nome).add_argument("--email", required=True)
    pp = sub.add_parser("papel")
    pp.add_argument("--email", required=True)
    pp.add_argument("--papel", choices=PAPEIS, required=True)

    a = p.parse_args()
    db.init_db()  # garante que a tabela existe (aplica a migration 0013)

    if a.cmd == "criar":
        if not seguranca.validar_email(a.email):
            sys.exit("E-mail inválido.")
        try:
            _mostrar(usuarios.criar(a.email, a.nome, seguranca.hash_senha(_pedir_senha()), a.papel))
        except ValueError as e:
            sys.exit(str(e))
    elif a.cmd == "listar":
        for u in usuarios.listar():
            _mostrar(u)
    elif a.cmd == "senha":
        _mostrar(usuarios.atualizar(a.email, senha_hash=seguranca.hash_senha(_pedir_senha())))
    elif a.cmd == "papel":
        _mostrar(usuarios.atualizar(a.email, papel=a.papel))
    elif a.cmd == "ativar":
        _mostrar(usuarios.atualizar(a.email, ativo=True))
    elif a.cmd == "desativar":
        _mostrar(usuarios.atualizar(a.email, ativo=False))


if __name__ == "__main__":
    main()
