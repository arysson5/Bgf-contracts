"""Verificações de runtime no Windows (VC++ e dependências problemáticas)."""

from __future__ import annotations

import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform.startswith("win")


def check_vcredist_dlls() -> tuple[bool, str]:
    """
    Verifica DLLs do Visual C++ Redistributable (x64) usadas por PyTorch e outras libs nativas.
    Retorna (ok, mensagem).
    """
    if not is_windows():
        return True, "Não-Windows: verificação de VC++ ignorada."

    system32 = Path(os_environ_systemroot()) / "System32"
    required = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"]
    missing = [name for name in required if not (system32 / name).exists()]

    if missing:
        return False, (
            "Visual C++ Redistributable (x64) incompleto. DLLs ausentes: "
            + ", ".join(missing)
            + ". Instale: https://aka.ms/vcredist (x64)."
        )
    return True, "Visual C++ Redistributable (x64): DLLs principais encontradas."


def os_environ_systemroot() -> str:
    import os

    return os.environ.get("SystemRoot", r"C:\Windows")


def torch_import_probe() -> tuple[bool, str]:
    """
    Tenta importar torch. O app não precisa de torch; falha aqui indica venv poluído.
    Retorna (ok, mensagem). ok=True se torch não está instalado ou importa sem erro.
    """
    import importlib.util

    if importlib.util.find_spec("torch") is None:
        return True, "PyTorch não instalado (esperado para este projeto)."

    try:
        import torch  # noqa: F401

        logger_msg = (
            "PyTorch instalado no .venv (não é necessário). "
            "Recomendado: pip uninstall -y torch torchvision transformers unstructured"
        )
        return True, logger_msg
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1114 or "c10.dll" in str(exc).lower():
            vc_ok, vc_msg = check_vcredist_dlls()
            if vc_ok:
                return False, (
                    "PyTorch instalado no ambiente falha ao carregar DLL (WinError 1114), "
                    "mesmo com VC++ presente. O projeto não usa PyTorch — desinstale-o do .venv. "
                    f"Detalhe: {exc}"
                )
            return False, f"{vc_msg} Erro ao carregar torch: {exc}"
        return False, f"Erro ao importar torch: {exc}"
    except Exception as exc:
        return False, f"Erro ao importar torch: {exc}"


def ensure_runtime_ok() -> None:
    """
    Valida ambiente antes de chamadas à IA. Levanta ValueError com mensagem clara se inválido.
    """
    if not is_windows():
        return

    vc_ok, vc_msg = check_vcredist_dlls()
    torch_ok, torch_msg = torch_import_probe()

    if not vc_ok:
        raise ValueError(vc_msg)
    if not torch_ok:
        raise ValueError(torch_msg)
