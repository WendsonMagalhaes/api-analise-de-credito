"""Código curto e opaco para cada cliente, usado na URL no lugar do nome.

Algoritmo cyrb53 (mesmo cálculo do front, em lib/codigo-cliente.ts). Não é
segredo: serve para a URL não revelar o nome. Quem tem o nome consegue
calcular o código, mas quem só vê a URL não consegue ler o cliente.
"""
from __future__ import annotations

import struct

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _imul(a: int, b: int) -> int:
    return (a * b) & 0xFFFFFFFF


def _cyrb53(s: str) -> int:
    # JavaScript percorre código UTF-16; replicamos as mesmas unidades
    unidades = struct.unpack("<%dH" % (len(s.encode("utf-16-le")) // 2), s.encode("utf-16-le"))
    h1, h2 = 0xDEADBEEF, 0x41C6CE57
    for ch in unidades:
        h1 = _imul(h1 ^ ch, 2654435761)
        h2 = _imul(h2 ^ ch, 1597334677)
    h1 = _imul(h1 ^ (h1 >> 16), 2246822507)
    h1 ^= _imul(h2 ^ (h2 >> 13), 3266489909)
    h2 = _imul(h2 ^ (h2 >> 16), 2246822507)
    h2 ^= _imul(h1 ^ (h1 >> 13), 3266489909)
    return 4294967296 * (2097151 & h2) + h1


def _base36(n: int) -> str:
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _B36[r] + out
    return out


def codigo_de(nome: str) -> str:
    return _base36(_cyrb53(nome))
