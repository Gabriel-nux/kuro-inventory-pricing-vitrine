from __future__ import annotations

import base64
import hmac
import json
from collections.abc import Sequence
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from erros import ErroKuro, ErroSeguranca


class ConfigInvalida(ErroKuro):
    pass


class Cofre:
    def __init__(self, chaves: Sequence[str]) -> None:
        if not chaves:
            raise ConfigInvalida("nenhuma chave de criptografia configurada")
        try:
            self._fernet = MultiFernet([Fernet(c.strip().encode()) for c in chaves])
        except (ValueError, TypeError) as e:
            raise ConfigInvalida("chave de criptografia inválida") from e

    @staticmethod
    def gerar_chave() -> str:
        return Fernet.generate_key().decode()

    def cifrar_json(self, contexto: str, dados: Any) -> bytes:
        envelope = json.dumps({"c": contexto, "d": dados}, ensure_ascii=False, separators=(",", ":"))
        return self._fernet.encrypt(envelope.encode())

    def decifrar_json(self, contexto: str, token: bytes) -> Any:
        try:
            envelope = json.loads(self._fernet.decrypt(bytes(token)))
        except (InvalidToken, ValueError) as e:
            raise ErroSeguranca("conteúdo armazenado adulterado ou chave incorreta") from e
        if not hmac.compare_digest(str(envelope.get("c", "")).encode(), contexto.encode()):
            raise ErroSeguranca("conteúdo armazenado não pertence a este registro")
        return envelope["d"]

    def cifrar_bytes(self, contexto: str, dados: bytes) -> bytes:
        return self.cifrar_json(contexto, base64.b64encode(dados).decode("ascii"))

    def decifrar_bytes(self, contexto: str, token: bytes) -> bytes:
        return base64.b64decode(self.decifrar_json(contexto, token))

    def rotacionar(self, token: bytes) -> bytes:
        try:
            return self._fernet.rotate(bytes(token))
        except InvalidToken as e:
            raise ErroSeguranca("conteúdo armazenado adulterado ou chave incorreta") from e
