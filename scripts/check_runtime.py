"""Diagnóstico de ambiente Windows — execute: .venv\\Scripts\\python.exe scripts\\check_runtime.py"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.utils.windows_runtime import check_vcredist_dlls, ensure_runtime_ok, torch_import_probe


def main() -> None:
    vc_ok, vc_msg = check_vcredist_dlls()
    print(vc_msg, "->", "OK" if vc_ok else "FALHA")
    torch_ok, torch_msg = torch_import_probe()
    print(torch_msg, "->", "OK" if torch_ok else "FALHA")
    try:
        ensure_runtime_ok()
        print("\n[OK] Ambiente pronto para análises com OpenAI.")
    except ValueError as exc:
        print(f"\n[FALHA] {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
