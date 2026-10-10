from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

from erros import ErroSeguranca
from ota_manifesto_ed25519 import chave_publica_de_base64

RAIZ = Path(__file__).resolve().parent
NOME = "App"
PREPARO = RAIZ / "build" / "preparo"
OFUSCADO = RAIZ / "build" / "ofuscado"
PYI_TRABALHO = RAIZ / "build" / "pyi"
EXCLUIR = ["tkinter", "pytest", "pip", "setuptools", "unittest", "pydoc", "test"]


def executar(cmd: list[str], cwd: Path = RAIZ) -> None:
    if subprocess.run(cmd, cwd=cwd, check=False).returncode != 0:
        sys.exit(f"falhou: {' '.join(cmd[:3])}")


def gravar_variante(alvo: Path) -> None:
    texto = alvo.read_bytes().decode("utf-8")
    if 'VARIANTE = ""' not in texto:
        sys.exit("variante.py não tem a linha esperada")
    alvo.write_bytes(texto.replace('VARIANTE = ""', 'VARIANTE = "cliente"', 1).encode("utf-8"))


def gravar_chave_publica(arquivo: Path, alvo: Path) -> None:
    bruto = arquivo.read_text(encoding="ascii").strip()
    if "PRIVATE" in bruto.upper():
        sys.exit("isso parece uma chave privada; use só o arquivo da chave pública")
    try:
        chave_publica_de_base64(bruto)
    except ErroSeguranca as e:
        sys.exit(f"chave pública inválida: {e}")
    texto = alvo.read_bytes().decode("utf-8")
    if 'CHAVE_PUBLICA_B64 = ""' not in texto:
        sys.exit("chave_publica.py não tem a linha esperada")
    alvo.write_bytes(texto.replace('CHAVE_PUBLICA_B64 = ""', f'CHAVE_PUBLICA_B64 = "{bruto}"', 1).encode("utf-8"))


def importacoes_de_terceiros(pasta: Path) -> list[str]:
    """O código ofuscado esconde os imports do PyInstaller, então eles são coletados antes, no código claro."""
    achados: set[str] = set()
    stdlib = set(sys.stdlib_module_names)
    for arquivo in pasta.rglob("*.py"):
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            nomes: list[str] = []
            if isinstance(no, ast.Import):
                nomes = [a.name for a in no.names]
            elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                nomes = [no.module]
            for nome in nomes:
                raiz = nome.split(".")[0]
                if raiz not in stdlib and raiz not in ("backend", "__future__"):
                    achados.add(nome)
    return sorted(achados)


def ofuscar() -> Path:
    if OFUSCADO.exists():
        shutil.rmtree(OFUSCADO)
    executar([sys.executable, "-m", "pyarmor.cli", "gen", "-O", str(OFUSCADO), "-r", "backend"], cwd=PREPARO)
    shutil.copy2(PREPARO / "launcher.py", OFUSCADO / "launcher.py")
    return OFUSCADO


def empacotar(origem: Path, dist_front: Path, saida: Path, ocultos: list[str], ofuscado: bool) -> Path:
    if PYI_TRABALHO.exists():
        shutil.rmtree(PYI_TRABALHO)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", NOME,
           "--distpath", str(saida), "--workpath", str(PYI_TRABALHO), "--specpath", str(PYI_TRABALHO),
           "--paths", str(origem), "--add-data", f"{dist_front}{os.pathsep}front"]
    for nome in ocultos:
        cmd += ["--hidden-import", nome]
    if ofuscado:
        cmd += ["--hidden-import", "pyarmor_runtime_000000"]
    for nome in EXCLUIR:
        cmd += ["--exclude-module", nome]
    cmd.append(str(origem / "launcher.py"))
    executar(cmd)
    exe = saida / f"{NOME}.exe"
    if not exe.is_file():
        sys.exit("o PyInstaller não gerou o executável")
    return exe
