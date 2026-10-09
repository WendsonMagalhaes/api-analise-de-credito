"""Atalho de compatibilidade: mantém o comando de sempre (`uvicorn main:app --reload`).

A aplicação de verdade está em app/main.py (`uvicorn app.main:app` também funciona).
"""
from app.main import app

__all__ = ["app"]
