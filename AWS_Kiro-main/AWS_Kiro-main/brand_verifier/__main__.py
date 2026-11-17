"""Punto de entrada: python -m brand_verifier <subcomando>.

La logica del CLI (run, validate) se implementa en cli.py en tareas posteriores.
"""
import sys


def main(argv=None) -> int:
    try:
        from brand_verifier import cli  # type: ignore
    except ImportError:
        print("brand_verifier: CLI aun no implementado", file=sys.stderr)
        return 1
    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
