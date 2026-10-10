from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from erros import ErroSeguranca

PREFIXO_DOMINIO = b"kuro-ota-v1"
TAMANHO_MAX_EXECUTAVEL = 400 * 1024 * 1024
TAMANHO_MAX_MANIFESTO = 16 * 1024
CAMPOS = frozenset({"versao", "sha256", "tamanho", "publicado_em", "url", "assinatura"})

_SEMVER = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_URL = re.compile(r"https://[A-Za-z0-9.\-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~!$&'()*+,;=:@%/\-]*)?")


@dataclass(frozen=True)
class Manifesto:
    versao: str
    sha256: str
    tamanho: int
    publicado_em: str
    url: str
    assinatura: bytes = b""


def versao_como_tupla(versao: str) -> tuple[int, int, int]:
    m = _SEMVER.fullmatch(versao)
    if not m:
        raise ErroSeguranca("versão fora do formato X.Y.Z")
    return int(m[1]), int(m[2]), int(m[3])


def validar_campos(m: Manifesto) -> None:
    versao_como_tupla(m.versao)
    if not _SHA256.fullmatch(m.sha256):
        raise ErroSeguranca("hash do manifesto inválido")
    if isinstance(m.tamanho, bool) or not isinstance(m.tamanho, int) or not 0 < m.tamanho <= TAMANHO_MAX_EXECUTAVEL:
        raise ErroSeguranca("tamanho do manifesto inválido")
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", m.publicado_em):
            raise ValueError
        date.fromisoformat(m.publicado_em)
    except ValueError as e:
        raise ErroSeguranca("data do manifesto inválida") from e
    if len(m.url) > 2048 or not _URL.fullmatch(m.url):
        raise ErroSeguranca("endereço de download inválido (só https)")


def bytes_canonicos(m: Manifesto) -> bytes:
    validar_campos(m)
    linhas = [PREFIXO_DOMINIO.decode(), m.versao, m.sha256, str(m.tamanho), m.publicado_em, m.url]
    return "\n".join(linhas).encode("ascii")


def carregar_manifesto(bruto: bytes) -> Manifesto:
    if len(bruto) > TAMANHO_MAX_MANIFESTO:
        raise ErroSeguranca("manifesto grande demais")
    try:
        dados = json.loads(bruto)
    except (ValueError, UnicodeDecodeError) as e:
        raise ErroSeguranca("manifesto não é JSON válido") from e
    if not isinstance(dados, dict) or set(dados) != CAMPOS:
        raise ErroSeguranca("manifesto com campos diferentes dos esperados")
    textos = ("versao", "sha256", "publicado_em", "url", "assinatura")
    if not all(isinstance(dados[k], str) for k in textos) or not isinstance(dados["tamanho"], int):
        raise ErroSeguranca("manifesto com tipos inesperados")
    try:
        assinatura = base64.b64decode(dados["assinatura"], validate=True)
    except (binascii.Error, ValueError) as e:
        raise ErroSeguranca("assinatura em base64 inválido") from e
    m = Manifesto(dados["versao"], dados["sha256"], dados["tamanho"], dados["publicado_em"], dados["url"], assinatura)
    validar_campos(m)
    return m


def chave_publica_de_base64(b64: str) -> Ed25519PublicKey:
    try:
        cru = base64.b64decode(b64.strip(), validate=True)
        if len(cru) != 32:
            raise ValueError
        return Ed25519PublicKey.from_public_bytes(cru)
    except (binascii.Error, ValueError) as e:
        raise ErroSeguranca("chave pública de atualização inválida ou ausente") from e


def verificar(m: Manifesto, chave: Ed25519PublicKey) -> None:
    if len(m.assinatura) != 64:
        raise ErroSeguranca("assinatura com tamanho inválido")
    try:
        chave.verify(m.assinatura, bytes_canonicos(m))
    except InvalidSignature as e:
        raise ErroSeguranca("assinatura do manifesto não confere") from e
