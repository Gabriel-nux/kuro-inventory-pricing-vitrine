from __future__ import annotations

import threading
import time
from collections.abc import Callable

from erros import IAIndisponivel


class Disjuntor:
    def __init__(self, falhas_max: int = 5, cooldown_s: float = 60, relogio: Callable[[], float] = time.monotonic) -> None:
        self._falhas_max = falhas_max
        self._cooldown = cooldown_s
        self._relogio = relogio
        self._falhas = 0
        self._aberto_em: float | None = None
        self._lock = threading.Lock()

    @property
    def estado(self) -> str:
        with self._lock:
            if self._aberto_em is None:
                return "fechado"
            return "meio_aberto" if self._relogio() - self._aberto_em >= self._cooldown else "aberto"

    def antes(self) -> None:
        with self._lock:
            if self._aberto_em is None:
                return
            if self._relogio() - self._aberto_em < self._cooldown:
                raise IAIndisponivel("IA temporariamente indisponível após falhas seguidas")
            self._aberto_em = self._relogio()

    def sucesso(self) -> None:
        with self._lock:
            self._falhas = 0
            self._aberto_em = None

    def falha(self) -> None:
        with self._lock:
            self._falhas += 1
            if self._falhas >= self._falhas_max or self._aberto_em is not None:
                self._aberto_em = self._relogio()
