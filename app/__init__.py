"""Crédito Frios — API de análise de crédito."""
from dotenv import load_dotenv

# Lê backend/.env (ver .env.example) ANTES de qualquer módulo do app ser importado:
# app/db/conexao.py lê DATABASE_URL no momento do import.
load_dotenv()
