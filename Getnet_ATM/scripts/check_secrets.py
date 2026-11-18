#!/usr/bin/env python3
"""Escáner de secretos para el hook de pre-commit (Req. 10.5, 10.6).

Escanea los archivos staged buscando claves, contraseñas y tokens. Ante una
coincidencia imprime solo ``ruta:línea`` (nunca el valor) y devuelve 1.

Una línea con el marcador ``nosecret`` se ignora.
"""
import re
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

IGNORE_MARKER = "nosecret"
MAX_FILE_BYTES = 1_000_000

# Valores que son referencias o marcadores de posición, no literales.
_PLACEHOLDER = re.compile(
    r"^(?:\$|<|\{|%|\*+$|x+$|\.+$|none$|null$|true$|false$|changeme$|example|your[-_]|"
    r"os\.|env|getenv|process\.|secret|config|args\.|self\.)",
    re.IGNORECASE,
)

_ASSIGN = re.compile(
    r"""(?ix)
    (?P<name>\w*(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key)\w*)   # nombre
    ["']?(?P<sep>\s*[:=]\s*)                                             # separador
    (?P<q>["']?)(?P<val>[^\s"'`,;)\]}]{6,})                              # valor literal
    """
)

# Formas que no son credenciales (falsos positivos habituales en este repo):
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")                       # "input_tokens": 121755
_UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_IDENT_NAME = re.compile(r"^(?:[A-Z][a-z0-9]*)+$|^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")  # AgentTokenSecret, COMFY_AGENT_TOKEN
_KEYWORDS = {"typeof", "await", "return", "lambda", "function"}


def _is_reference(m: "re.Match[str]", line: str) -> bool:
    """True si el valor es codigo, un nombre o un numero, no un literal secreto."""
    name, sep, quoted, val = m.group("name"), m.group("sep"), bool(m.group("q")), m.group("val")
    if _PLACEHOLDER.match(val) or _NUMBER.match(val):
        return True
    if val.startswith(("/(", "/^")):  # literal de regex: /(secret|token)/i
        return True
    # Servicio IAM o ARN: secretsmanager:GetSecretValue, arn:aws:secretsmanager:us-east-2:...
    if sep == ":" and name.islower() and name.isalpha():
        return True
    if not quoted:
        # Expresion de codigo: llamada, atributo, constante o palabra clave (token=FAKE_TOKEN, r.NextToken).
        nxt = line[m.end("val"):m.end("val") + 1]
        constant = bool(_UPPER_SNAKE.match(val)) and "_" in val  # FAKE_TOKEN, no V00000000
        if "(" in val or "." in val or "[" in val or nxt == "(" or constant or val in _KEYWORDS:
            return True
        # Prosa: "Gestor_Secretos: lectura de ..." (palabra en minusculas tras ':').
        if sep.strip() == ":" and val.isalpha() and val.islower():
            return True
    # Constante con el NOMBRE de un secreto, no su valor: SECRET_NAME = "StabilityAIApiKey".
    if quoted and _UPPER_SNAKE.match(name) and "_" in name and _IDENT_NAME.match(val):
        return True
    # Nombre de variable de entorno como valor: {"StabilityAIApiKey": "STABILITY_API_KEY"}.
    if quoted and _UPPER_SNAKE.match(val) and "_" in val:
        return True
    return False

_DIRECT_PATTERNS = (
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                 # clave AWS
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),                      # prefijo tipo sk-
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{20,}"),       # cabecera Bearer
    re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),       # clave privada
)


def _line_has_secret(line: str) -> bool:
    if IGNORE_MARKER in line:
        return False
    for pat in _DIRECT_PATTERNS:
        if pat.search(line):
            return True
    for m in _ASSIGN.finditer(line):
        if not _is_reference(m, line):
            return True
    return False


def scan_text(text: str, path: str = "<texto>") -> List[Tuple[str, int]]:
    """Devuelve [(ruta, nº de línea)] (base 1) de las líneas con posibles secretos.

    Nunca incluye el valor detectado.
    """
    return [
        (path, n)
        for n, line in enumerate(text.splitlines(), start=1)
        if _line_has_secret(line)
    ]


def scan_file(path: str) -> List[Tuple[str, int]]:
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_FILE_BYTES + 1)
    except OSError:
        return []
    if len(data) > MAX_FILE_BYTES or b"\0" in data:
        return []  # binario o demasiado grande
    return scan_text(data.decode("utf-8", errors="replace"), path)


def staged_files() -> List[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"],
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.decode("utf-8", errors="replace")
    return [p for p in out.split("\0") if p]


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        files = args or staged_files()
    except (subprocess.CalledProcessError, OSError):
        print("check_secrets: no se pudo listar los archivos staged", file=sys.stderr)
        return 2
    findings: List[Tuple[str, int]] = []
    for f in files:
        findings.extend(scan_file(f))
    if findings:
        print("Commit bloqueado, posible credencial en:", file=sys.stderr)
        for path, line in findings:
            print("  %s:%d" % (path, line), file=sys.stderr)
        print("Elimina el valor y léelo de una variable de entorno o Secrets Manager.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
