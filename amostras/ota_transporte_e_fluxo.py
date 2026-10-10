from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from urllib.parse import urljoin

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from erros import ErroSeguranca
from ota_manifesto_ed25519 import (
    TAMANHO_MAX_MANIFESTO,
    Manifesto,
    carregar_manifesto,
    verificar,
    versao_como_tupla,
)

MAX_REDIRECIONAMENTOS = 3
PRAZO_DOWNLOAD_S = 30 * 60
TAMANHO_BLOCO = 256 * 1024
CABECALHOS = {"User-Agent": "kuro-ota", "Accept": "*/*", "Accept-Encoding": "identity"}


def exigir_https(url: str) -> str:
    if not url.startswith("https://"):
        raise ErroSeguranca("o OTA só fala HTTPS")
    return url


class Transporte:
    def __init__(self, *, transporte: httpx.BaseTransport | None = None) -> None:
        self._cliente = httpx.Client(follow_redirects=False, trust_env=False, transport=transporte,
                                     timeout=httpx.Timeout(30.0), headers=CABECALHOS)

    def _abrir(self, url: str) -> httpx.Response:
        atual = exigir_https(url)
        for _ in range(MAX_REDIRECIONAMENTOS + 1):
            resposta = self._cliente.send(self._cliente.build_request("GET", atual), stream=True)
            if resposta.status_code in (301, 302, 303, 307, 308):
                destino = resposta.headers.get("location")
                resposta.close()
                if not destino:
                    raise ErroSeguranca("redirecionamento sem destino")
                atual = exigir_https(urljoin(atual, destino))
                continue
            return resposta
        raise ErroSeguranca("redirecionamentos demais")

    def obter_limitado(self, url: str, limite: int) -> bytes:
        resposta = self._abrir(url)
        try:
            if resposta.status_code != 200:
                raise OSError(f"HTTP {resposta.status_code}")
            partes: list[bytes] = []
            total = 0
            for bloco in resposta.iter_bytes(TAMANHO_BLOCO):
                total += len(bloco)
                if total > limite:
                    raise ErroSeguranca("resposta maior que o limite")
                partes.append(bloco)
            return b"".join(partes)
        finally:
            resposta.close()

    def baixar(self, url: str, destino: Path, limite: int) -> tuple[str, int]:
        resposta = self._abrir(url)
        h = hashlib.sha256()
        total = 0
        fim = time.monotonic() + PRAZO_DOWNLOAD_S
        try:
            if resposta.status_code != 200:
                raise OSError(f"HTTP {resposta.status_code}")
            with open(destino, "wb") as f:
                for bloco in resposta.iter_bytes(TAMANHO_BLOCO):
                    total += len(bloco)
                    if total > limite:
                        raise ErroSeguranca("download maior que o tamanho assinado")
                    if time.monotonic() > fim:
                        raise ErroSeguranca("download demorou além do prazo")
                    h.update(bloco)
                    f.write(bloco)
        finally:
            resposta.close()
        return h.hexdigest(), total


class Resultado(StrEnum):
    SEM_NOVIDADE = "sem_novidade"
    ERRO_REDE = "erro_rede"
    REJEITADO = "rejeitado"
    OCUPADO = "ocupado"
    PRONTO_PARA_INSTALAR = "pronto_para_instalar"


def limpar_pasta(pasta: Path) -> None:
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True, exist_ok=True)


def sha256_do_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


class Atualizador:
    def __init__(self, *, url: str, versao_atual: str, chave_publica: Ed25519PublicKey, pasta_temp: Path,
                 transporte: Transporte, ocupado: Callable[[], bool],
                 registrar: Callable[..., None] = lambda evento, **dados: None) -> None:
        self.url, self.versao_atual, self.chave = url, versao_atual, chave_publica
        self.pasta_temp, self.transporte, self.ocupado, self.registrar = pasta_temp, transporte, ocupado, registrar

    def _rejeitar(self, motivo: str, **dados: object) -> Resultado:
        limpar_pasta(self.pasta_temp)
        self.registrar("ota.alerta_seguranca", motivo=motivo, **dados)
        return Resultado.REJEITADO

    def _manifesto_assinado(self) -> Manifesto | Resultado:
        try:
            bruto = self.transporte.obter_limitado(self.url, TAMANHO_MAX_MANIFESTO)
        except (OSError, httpx.HTTPError):
            return Resultado.ERRO_REDE
        except ErroSeguranca:
            return self._rejeitar("manifesto_recusado_na_rede")
        try:
            manifesto = carregar_manifesto(bruto)
        except ErroSeguranca:
            return self._rejeitar("manifesto_malformado")
        try:
            verificar(manifesto, self.chave)
        except ErroSeguranca:
            return self._rejeitar("assinatura_do_manifesto_invalida", versao_anunciada=manifesto.versao)
        return manifesto

    def _baixar_e_conferir(self, m: Manifesto) -> Path | Resultado:
        limpar_pasta(self.pasta_temp)
        parcial = self.pasta_temp / "novo.exe.part"
        try:
            sha, total = self.transporte.baixar(m.url, parcial, m.tamanho)
        except (OSError, httpx.HTTPError):
            limpar_pasta(self.pasta_temp)
            return Resultado.ERRO_REDE
        except ErroSeguranca:
            return self._rejeitar("download_fora_dos_limites_assinados", versao=m.versao)
        if total != m.tamanho or not hmac.compare_digest(sha, m.sha256):
            return self._rejeitar("hash_ou_tamanho_nao_confere", versao=m.versao)
        final = self.pasta_temp / "novo.exe"
        os.replace(parcial, final)
        return final

    def verificar_uma_vez(self) -> tuple[Resultado, Path | None]:
        self.pasta_temp.mkdir(parents=True, exist_ok=True)
        manifesto = self._manifesto_assinado()
        if isinstance(manifesto, Resultado):
            return manifesto, None
        if versao_como_tupla(manifesto.versao) <= versao_como_tupla(self.versao_atual):
            return Resultado.SEM_NOVIDADE, None
        if self.ocupado():
            return Resultado.OCUPADO, None
        arquivo = self._baixar_e_conferir(manifesto)
        if isinstance(arquivo, Resultado):
            return arquivo, None
        if self.ocupado():
            limpar_pasta(self.pasta_temp)
            return Resultado.OCUPADO, None
        if not hmac.compare_digest(sha256_do_arquivo(arquivo), manifesto.sha256):
            return self._rejeitar("arquivo_alterado_em_disco_apos_validacao", versao=manifesto.versao), None
        return Resultado.PRONTO_PARA_INSTALAR, arquivo
