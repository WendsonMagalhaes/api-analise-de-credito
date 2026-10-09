"""Cronômetro por etapa, logado no console do uvicorn — mostra qual parte do processamento está lenta."""
from __future__ import annotations

import logging
import time


log = logging.getLogger("uvicorn.error")


class Etapas:
    """Cronômetro por etapa, logado no console do uvicorn — mostra na hora
    qual parte do processamento está lenta."""

    def __init__(self, nome: str):
        self.nome = nome
        self.inicio = self.ultimo = time.perf_counter()
        self.partes: list[str] = []

    def marca(self, etapa: str) -> None:
        agora = time.perf_counter()
        self.partes.append(f"{etapa}={agora - self.ultimo:.2f}s")
        self.ultimo = agora

    def fim(self) -> None:
        log.info("[%s] total=%.2fs | %s", self.nome, time.perf_counter() - self.inicio, " ".join(self.partes))
