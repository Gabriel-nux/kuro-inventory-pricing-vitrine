from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from erros import ErroIA

_PADROES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(senha|password|token|secret|api[_-]?key)\s*[:=]\s*\S+"), r"\1=[SEGREDO]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"), "[CNPJ]"),
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "[CPF]"),
    (re.compile(r"\(\d{2}\)\s?9?\d{4}-?\d{4}|\b\d{2}\s?9\d{4}-\d{4}\b"), "[TELEFONE]"),
)
_CONTROLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
RISCOS = frozenset({"baixo", "medio", "alto"})


def sanitizar(texto: str) -> str:
    saida = str(texto)
    for padrao, marcador in _PADROES:
        saida = padrao.sub(marcador, saida)
    return saida


def limpar_controle(texto: str) -> str:
    return _CONTROLE.sub("", unicodedata.normalize("NFC", str(texto)))


def escapar_dados(texto: str, limite: int = 200) -> str:
    limpo = limpar_controle(texto).replace("<", "‹").replace(">", "›")
    return limpo[:limite]


def embrulhar_dados(origem: str, texto: str, limite: int = 200) -> str:
    origem_segura = re.sub(r"[^a-z0-9_]", "", origem.lower())[:30] or "planilha"
    return f"<dados origem={origem_segura}>{escapar_dados(sanitizar(texto), limite)}</dados>"


@dataclass(frozen=True)
class InsightBruto:
    n: int
    risco: str
    resumo: str
    acao: str
    ajuste_preco_bps: int | None


def _sem_valores_em_reais(texto: str) -> str:
    frases = re.split(r"(?<=[.!?])\s+", " ".join(texto.split()))
    return " ".join(f for f in frases if "$" not in f).strip()


def _insight_ou_none(entrada: Any) -> InsightBruto | None:
    if not isinstance(entrada, dict):
        return None
    n, risco, resumo, acao = entrada.get("n"), entrada.get("risco"), entrada.get("resumo"), entrada.get("acao")
    pct = entrada.get("ajuste_preco_pct")
    if isinstance(n, bool) or not isinstance(n, int) or risco not in RISCOS:
        return None
    if not isinstance(resumo, str) or not isinstance(acao, str):
        return None
    resumo, acao = _sem_valores_em_reais(resumo), _sem_valores_em_reais(acao)
    if not resumo or not acao:
        return None
    bps: int | None = None
    if pct is not None:
        if isinstance(pct, bool) or not isinstance(pct, int | float) or not -30 <= pct <= 30:
            return None
        bps = round(pct * 100)
    return InsightBruto(n, risco, limpar_controle(resumo)[:280], limpar_controle(acao)[:120], bps)


def validar_resposta(resposta: dict[str, Any], tamanho_lote: int) -> list[InsightBruto]:
    """Item inválido é descartado; o lote só falha se nada aproveitável sobrar."""
    bruto = resposta.get("insights")
    if not isinstance(bruto, list):
        raise ErroIA("resposta do modelo sem a lista 'insights'")
    validos: dict[int, InsightBruto] = {}
    for entrada in bruto:
        ins = _insight_ou_none(entrada)
        if ins is not None and 1 <= ins.n <= tamanho_lote and ins.n not in validos:
            validos[ins.n] = ins
    if bruto and not validos:
        raise ErroIA("nenhum insight da resposta passou na validação")
    return list(validos.values())
