from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from erros import ErroIA, ErroSeguranca, IAIndisponivel, RequisicaoRecusada

HOSTS_LOCAIS = frozenset({"localhost", "127.0.0.1", "::1"})
NUM_CTX = 8192
NUM_PREDICT = 3000


def validar_url_ia(url: str) -> str:
    try:
        partes = urlsplit(url.strip())
        host = partes.hostname
        porta = partes.port
    except ValueError as e:
        raise ErroSeguranca("URL da IA inválida") from e
    if partes.scheme not in ("http", "https"):
        raise ErroSeguranca("URL da IA deve usar http ou https")
    if partes.username or partes.password:
        raise ErroSeguranca("URL da IA não pode conter credenciais")
    if host is None or host.lower() not in HOSTS_LOCAIS:
        raise ErroSeguranca("a IA só pode rodar nesta máquina: host externo recusado")
    if partes.path not in ("", "/") or partes.query or partes.fragment:
        raise ErroSeguranca("URL da IA deve ser só esquema, host e porta")
    base = f"{partes.scheme}://{'[::1]' if host == '::1' else host.lower()}"
    return base + (f":{porta}" if porta else "")


class ClienteOllama:
    def __init__(
        self,
        url: str,
        modelo: str,
        *,
        timeout_s: float = 120,
        tentativas: int = 3,
        transporte: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = validar_url_ia(url)
        self.modelo = modelo
        self._tentativas = tentativas
        self._dormir = dormir
        self._http = httpx.Client(
            base_url=self._url,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_s, connect=5.0),
            transport=transporte,
        )

    def verificar(self) -> None:
        try:
            r = self._http.get("/api/tags", timeout=httpx.Timeout(10.0, connect=5.0))
            r.raise_for_status()
            instalados = [m["name"] for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            raise IAIndisponivel("o Ollama local não respondeu") from e
        if not any(n == self.modelo or n.startswith(self.modelo + ":") for n in instalados):
            raise IAIndisponivel(f"modelo '{self.modelo}' não está instalado")

    def conversar_json(self, sistema: str, usuario: str, *, temperatura: float = 0.0) -> dict[str, Any]:
        corpo = {
            "model": self.modelo,
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
            "stream": False,
            "format": "json",
            "options": {"temperature": temperatura, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
        }
        ultimo: ErroIA = ErroIA("falha desconhecida")
        for tentativa in range(1, self._tentativas + 1):
            try:
                r = self._http.post("/api/chat", json=corpo)
                if 400 <= r.status_code < 500:
                    raise RequisicaoRecusada(f"o servidor recusou a requisição (HTTP {r.status_code})")
                r.raise_for_status()
                return self._interpretar(r.json()["message"]["content"])
            except RequisicaoRecusada:
                raise
            except httpx.ConnectError:
                ultimo = IAIndisponivel("sem conexão com o servidor de IA local")
            except httpx.TimeoutException:
                ultimo = ErroIA("tempo esgotado esperando o modelo")
            except httpx.HTTPStatusError as e:
                ultimo = ErroIA(f"erro do servidor de IA (HTTP {e.response.status_code})")
            except (ValueError, KeyError, TypeError):
                ultimo = ErroIA("resposta do modelo fora do formato esperado")
            except httpx.HTTPError:
                ultimo = ErroIA("falha de comunicação com o servidor de IA")
            if tentativa < self._tentativas:
                self._dormir(2 ** (tentativa - 1))
        raise type(ultimo)(f"{ultimo} (após {self._tentativas} tentativas)")

    @staticmethod
    def _interpretar(conteudo: str) -> dict[str, Any]:
        dados = json.loads(conteudo)
        if not isinstance(dados, dict):
            raise ValueError("a resposta não é um objeto JSON")
        return dados

    def fechar(self) -> None:
        self._http.close()
