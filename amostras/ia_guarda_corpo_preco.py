from __future__ import annotations

from dataclasses import dataclass

from erros import ErroValidacao

AJUSTE_MAX_BPS = 3000


@dataclass(frozen=True)
class Regras:
    margem_min_bps: int
    margem_max_bps: int
    arredondamento: str = "terminado_90"


def preco_por_margem(custo_centavos: int, margem_bps: int) -> int:
    if custo_centavos < 0:
        raise ErroValidacao("custo negativo")
    if not 0 <= margem_bps < 10_000:
        raise ErroValidacao("margem fora do intervalo de 0% a menos de 100%")
    return -(-custo_centavos * 10_000 // (10_000 - margem_bps))


def arredondar_preco(centavos: int, regra: str) -> int:
    if regra == "nenhum":
        return centavos
    if regra == "inteiro":
        return -(-centavos // 100) * 100
    if regra == "terminado_90":
        reais, resto = divmod(centavos, 100)
        return reais * 100 + 90 if resto <= 90 else (reais + 1) * 100 + 90
    raise ErroValidacao("regra de arredondamento desconhecida")


def faixa_de_preco(custo_centavos: int, regras: Regras) -> tuple[int, int]:
    piso = preco_por_margem(custo_centavos, regras.margem_min_bps)
    teto = custo_centavos * 10_000 // (10_000 - regras.margem_max_bps)
    return piso, max(teto, piso)


def limitar_preco(proposto: int, custo_centavos: int, regras: Regras) -> tuple[int, str | None]:
    piso, teto = faixa_de_preco(custo_centavos, regras)
    if proposto < piso:
        return piso, "abaixo da margem mínima"
    if proposto > teto:
        return teto, "acima da margem máxima"
    return proposto, None


def finalizar_preco(proposto: int, custo_centavos: int, regras: Regras) -> tuple[int, str | None]:
    preco, motivo = limitar_preco(proposto, custo_centavos, regras)
    arredondado = arredondar_preco(preco, regras.arredondamento)
    _, teto = faixa_de_preco(custo_centavos, regras)
    return (arredondado if arredondado <= teto else preco), motivo


def preco_a_partir_do_pedido_da_ia(
    referencia_centavos: int, ajuste_bps: int | None, custo_centavos: int, regras: Regras
) -> tuple[int, bool]:
    """O modelo só pede um ajuste percentual; quem faz a conta e corta é o código."""
    if ajuste_bps is None:
        return referencia_centavos, False
    if isinstance(ajuste_bps, bool) or not -AJUSTE_MAX_BPS <= ajuste_bps <= AJUSTE_MAX_BPS:
        raise ErroValidacao("ajuste pedido pela IA fora do intervalo permitido")
    proposto = referencia_centavos * (10_000 + ajuste_bps) // 10_000
    preco, motivo = finalizar_preco(proposto, custo_centavos, regras)
    return preco, motivo is not None
