"""
Cache de respostas em memória (por processo), com validade curta.

O dashboard faz 4 chamadas ao backend e cada uma faz várias consultas ao banco
remoto; abrir o dashboard duas vezes seguidas refazia tudo. Aqui, a segunda
abertura dentro da validade sai da memória.

Regra de segurança: QUALQUER requisição que não seja leitura (POST/PUT/DELETE:
upload, recálculo, decisão, aprovar reajuste, config...) limpa o cache inteiro
— ver o middleware em main.py. Então o usuário nunca vê um dado velho depois
de uma ação que ele mesmo fez. Com mais de um worker do uvicorn cada processo
tem o seu cache; a validade curta (TTL) limita o quanto outro worker pode
demorar pra enxergar uma mudança.
"""
from __future__ import annotations

import threading
import time
from functools import wraps

_store: dict = {}
_geracao = 0
_lock = threading.Lock()

TTL_PADRAO_S = 60


def ttl_cache(segundos: int = TTL_PADRAO_S):
    def decorador(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            chave = (fn.__name__, args, tuple(sorted(kwargs.items())))
            agora = time.monotonic()
            with _lock:
                item = _store.get(chave)
                geracao_antes = _geracao
            if item and agora - item[0] < segundos:
                return item[1]
            valor = fn(*args, **kwargs)
            with _lock:
                # se algo foi gravado enquanto calculávamos, o resultado pode
                # já estar velho: devolve, mas não guarda
                if geracao_antes == _geracao:
                    _store[chave] = (agora, valor)
            return valor

        return wrapper

    return decorador


def invalidar_tudo() -> None:
    global _geracao
    with _lock:
        _geracao += 1
        _store.clear()
