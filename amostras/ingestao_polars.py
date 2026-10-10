from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass

import polars as pl

from erros import ErroValidacao

SEPARADORES = ",;\t|"
LINHAS_PARA_PERFIL = 20_000
REGEX_NUMERO = r"^[+-]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$|^[+-]?\d+\.\d+$"


@dataclass(frozen=True)
class Limites:
    max_bytes: int = 25 * 1024 * 1024
    max_linhas: int = 200_000
    max_colunas: int = 200
    max_descompactado: int = 200 * 1024 * 1024


@dataclass(frozen=True)
class Tabela:
    df: pl.DataFrame
    linhas_com_excesso: frozenset[int]


def validar_xlsx(conteudo: bytes, limites: Limites) -> None:
    if not conteudo.startswith(b"PK\x03\x04"):
        raise ErroValidacao("o arquivo não parece um .xlsx válido")
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            infos = z.infolist()
            nomes = {i.filename for i in infos}
            if "xl/workbook.xml" not in nomes:
                raise ErroValidacao("o arquivo não parece um .xlsx válido")
            if any("vbaproject" in n.lower() for n in nomes):
                raise ErroValidacao("planilha com macro é recusada")
            if any(n.startswith(("/", "..")) or ".." in n.split("/") for n in nomes):
                raise ErroValidacao("estrutura interna do arquivo suspeita")
            if sum(i.file_size for i in infos) > limites.max_descompactado:
                raise ErroValidacao("arquivo descompactado grande demais")
    except zipfile.BadZipFile as e:
        raise ErroValidacao("o arquivo não parece um .xlsx válido") from e


def decodificar(conteudo: bytes) -> str:
    if conteudo.startswith((b"\xff\xfe", b"\xfe\xff")):
        return conteudo.decode("utf-16")
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("cp1252", errors="replace")


def detectar_separador(texto: str) -> str:
    amostra = texto[:65536]
    if "\n" in amostra:
        amostra = amostra[: amostra.rfind("\n")]
    try:
        return csv.Sniffer().sniff(amostra, delimiters=SEPARADORES).delimiter
    except csv.Error:
        primeira = amostra.split("\n", 1)[0]
        return max(SEPARADORES, key=primeira.count)


def _nomes_unicos(cabecalho: list[str]) -> list[str]:
    vistos: dict[str, int] = {}
    saida: list[str] = []
    for i, bruto in enumerate(cabecalho, start=1):
        nome = " ".join(str(bruto).split()) or f"coluna_{i}"
        n = vistos.get(nome, 0) + 1
        vistos[nome] = n
        saida.append(nome if n == 1 else f"{nome}_{n}")
    return saida


def _montar(cabecalho: list[str], linhas: list[list[str]], excesso: set[int], limites: Limites) -> Tabela:
    if not cabecalho or all(not c.strip() for c in cabecalho):
        raise ErroValidacao("arquivo sem cabeçalho")
    if len(cabecalho) > limites.max_colunas:
        raise ErroValidacao(f"colunas demais (máximo {limites.max_colunas})")
    nomes = _nomes_unicos(cabecalho)
    colunas = {nome: [(lin[i] if i < len(lin) else "") for lin in linhas] for i, nome in enumerate(nomes)}
    return Tabela(pl.DataFrame(colunas, schema=dict.fromkeys(nomes, pl.String)), frozenset(excesso))


def ler_csv(conteudo: bytes, limites: Limites) -> Tabela:
    texto = decodificar(conteudo)
    leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=detectar_separador(texto))
    try:
        cabecalho = next(leitor, [])
        linhas: list[list[str]] = []
        excesso: set[int] = set()
        for numero, linha in enumerate(leitor, start=2):
            if len(linhas) >= limites.max_linhas:
                raise ErroValidacao(f"linhas demais (máximo {limites.max_linhas})")
            if len(linha) > len(cabecalho):
                excesso.add(numero)
            linhas.append(linha)
    except csv.Error as e:
        raise ErroValidacao("CSV malformado") from e
    return _montar(cabecalho, linhas, excesso, limites)


def ler_xlsx(conteudo: bytes, limites: Limites) -> Tabela:
    validar_xlsx(conteudo, limites)
    try:
        df = pl.read_excel(io.BytesIO(conteudo), engine="calamine", infer_schema_length=0)
    except Exception as e:
        raise ErroValidacao("não foi possível ler a planilha .xlsx") from e
    if df.height > limites.max_linhas:
        raise ErroValidacao(f"linhas demais (máximo {limites.max_linhas})")
    cabecalho = [str(c) for c in df.columns]
    linhas = [["" if v is None else str(v) for v in r] for r in df.rows()]
    return _montar(cabecalho, linhas, set(), limites)


def perfilar(df: pl.DataFrame) -> list[dict[str, float | str]]:
    """Perfil por coluna só com expressões vetorizadas sobre uma amostra: nenhum laço em Python por célula."""
    amostra = df.head(LINHAS_PARA_PERFIL)
    perfis: list[dict[str, float | str]] = []
    for nome in df.columns:
        serie = amostra[nome].fill_null("").str.strip_chars()
        cheios = serie.filter(serie != "")
        total, n = len(serie), len(cheios)
        if n == 0:
            perfis.append({"nome": nome, "vazio": 1.0, "inteiro": 0.0, "numerico": 0.0, "unicidade": 0.0})
            continue
        limpo = cheios.str.replace_all(r"(?i)r\$|\s", "")
        perfis.append({
            "nome": nome,
            "vazio": round(1 - n / total, 4),
            "inteiro": round(float(limpo.str.contains(r"^[+-]?\d+$").sum()) / n, 4),
            "numerico": round(float(limpo.str.contains(REGEX_NUMERO).sum()) / n, 4),
            "unicidade": round(cheios.n_unique() / n, 4),
        })
    return perfis


def impressao_digital(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()
