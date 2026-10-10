from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from erros import ErroValidacao

LIMITE_CENTAVOS = 10**12

_US = re.compile(r"^[+-]?\d{1,3}(,\d{3})+\.\d+$|^[+-]?\d{1,3}(,\d{3}){2,}$")
_BR = re.compile(r"^[+-]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
_PONTO = re.compile(r"^[+-]?\d+\.\d+$")
_SIMBOLOS = re.compile(r"(?i)r\$|\s")


def texto_para_decimal(texto: str) -> Decimal:
    limpo = _SIMBOLOS.sub("", str(texto))
    if len(limpo) > 30:
        raise ErroValidacao("valor numérico longo demais")
    if _US.match(limpo):
        canonico = limpo.replace(",", "")
    elif _BR.match(limpo):
        canonico = limpo.replace(".", "").replace(",", ".")
    elif _PONTO.match(limpo):
        canonico = limpo
    else:
        raise ErroValidacao("valor numérico em formato desconhecido")
    try:
        return Decimal(canonico)
    except InvalidOperation as e:
        raise ErroValidacao("valor numérico inválido") from e


def _x100(valor: Decimal) -> int:
    try:
        return int((valor * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except InvalidOperation as e:
        raise ErroValidacao("valor numérico fora do limite aceito") from e


def parse_dinheiro(texto: str) -> int:
    centavos = _x100(texto_para_decimal(texto))
    if abs(centavos) > LIMITE_CENTAVOS:
        raise ErroValidacao("valor monetário fora do limite aceito")
    return centavos


def parse_margem_bps(texto: str) -> int:
    bruto = str(texto)
    valor = texto_para_decimal(bruto.replace("%", ""))
    if "%" not in bruto and 0 < valor < 1:
        valor = valor * 100
    bps = _x100(valor)
    if not 0 <= bps < 10_000:
        raise ErroValidacao("margem fora do intervalo de 0% a menos de 100%")
    return bps


def margem_do_preco_bps(custo_centavos: int, preco_centavos: int) -> int | None:
    if preco_centavos <= 0:
        return None
    return (preco_centavos - custo_centavos) * 10_000 // preco_centavos
