"""Exportação do documento comentado — download, Salvar como (Windows) e caminho manual."""

from __future__ import annotations

import shutil
from pathlib import Path

import streamlit as st

from app.utils.comments_ui import get_comments_bundle
from app.utils.settings import get_settings


def _mime_for(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in (".docx", ".doc"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"


def _suggest_export_name(work_path: str, version) -> str:
    stem = Path(work_path).stem
    label = getattr(version, "label", None) or ""
    if label and label not in stem:
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in label).strip()
        if safe:
            return f"{stem}_{safe}{Path(work_path).suffix}"
    return Path(work_path).name


def get_annotated_work_path(version) -> str | None:
    bundle = get_comments_bundle(version.id, version.contract_id)
    work = bundle.annotated_file_path
    if work and Path(work).exists():
        return work
    return None


def pick_save_as_path(
    *,
    initial_name: str,
    initial_dir: Path | str | None = None,
) -> Path | None:
    """Abre diálogo nativo Salvar como (Windows/macOS/Linux com Tk)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    ext = Path(initial_name).suffix.lower()
    if ext == ".pdf":
        filetypes = [("PDF", "*.pdf"), ("Todos os arquivos", "*.*")]
        defaultext = ".pdf"
    elif ext in (".docx", ".doc"):
        filetypes = [("Word", "*.docx"), ("Todos os arquivos", "*.*")]
        defaultext = ".docx"
    else:
        filetypes = [("Todos os arquivos", "*.*")]
        defaultext = ext or ".pdf"

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    try:
        selected = filedialog.asksaveasfilename(
            title="Salvar documento com comentários",
            initialfile=initial_name,
            initialdir=str(initial_dir) if initial_dir else None,
            defaultextension=defaultext,
            filetypes=filetypes,
        )
    finally:
        root.destroy()

    return Path(selected) if selected else None


def export_file_to_path(source: str | Path, dest: str | Path) -> Path:
    """Copia o arquivo comentado para o caminho escolhido pelo usuário."""
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Arquivo de origem não encontrado: {src}")

    target = Path(dest)
    if target.is_dir():
        target = target / src.name

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target.resolve()


def _default_export_dir() -> Path:
    settings = get_settings()
    if settings.export_path:
        return settings.export_path
    return Path.home() / "Documents"


def render_annotated_export_panel(
    version,
    *,
    key_prefix: str = "exp",
    compact: bool = False,
    title: str = "Exportar documento comentado",
) -> bool:
    """
    Oferece Salvar como: download do navegador, diálogo nativo ou caminho digitado.
    Retorna True se há arquivo comentado disponível para exportar.
    """
    work = get_annotated_work_path(version)
    if not work:
        if not compact:
            st.caption("Grave comentários no PDF antes de exportar.")
        return False

    suggested = _suggest_export_name(work, version)
    fname_key = f"{key_prefix}_export_fname"
    if fname_key not in st.session_state:
        st.session_state[fname_key] = suggested

    if not compact:
        st.markdown(f"**{title}**")
        st.caption(
            "Escolha onde salvar o PDF/DOCX com os comentários gravados. "
            "No app local (Windows), use **Escolher pasta** para abrir a janela **Salvar como**."
        )

    file_name = st.text_input(
        "Nome do arquivo",
        key=fname_key,
        help="Nome sugerido ao salvar. Você pode alterar antes de exportar.",
        label_visibility="visible",
    )

    data = Path(work).read_bytes()
    mime = _mime_for(work)

    btn_dl, btn_native = st.columns(2)
    with btn_dl:
        st.download_button(
            "💾 Salvar como… (download)",
            data,
            file_name=file_name or suggested,
            mime=mime,
            key=f"{key_prefix}_dl_saveas",
            type="primary",
            use_container_width=True,
            help="Abre a janela Salvar como do navegador para escolher a pasta.",
        )
    with btn_native:
        if st.button(
            "📂 Escolher pasta no computador…",
            key=f"{key_prefix}_native_saveas",
            use_container_width=True,
            help="Diálogo Salvar como do Windows (app rodando localmente).",
        ):
            dest = pick_save_as_path(
                initial_name=file_name or suggested,
                initial_dir=_default_export_dir(),
            )
            if dest:
                try:
                    saved = export_file_to_path(work, dest)
                    st.session_state[f"{key_prefix}_last_export"] = str(saved)
                    st.success(f"Salvo em: `{saved}`")
                except OSError as exc:
                    st.error(f"Não foi possível salvar: {exc}")

    last = st.session_state.get(f"{key_prefix}_last_export")
    if last and Path(last).exists():
        st.caption(f"Último export: `{last}`")

    if not compact:
        with st.expander("Informar caminho completo no computador", expanded=False):
            path_key = f"{key_prefix}_export_path"
            path_val = st.text_input(
                "Caminho completo (arquivo ou pasta)",
                key=path_key,
                placeholder=r"C:\Users\...\Downloads\contrato_revisado.pdf",
            )
            if st.button("Exportar para este caminho", key=f"{key_prefix}_path_export"):
                if not path_val.strip():
                    st.warning("Informe o caminho completo.")
                else:
                    try:
                        saved = export_file_to_path(work, path_val.strip())
                        st.session_state[f"{key_prefix}_last_export"] = str(saved)
                        st.success(f"Salvo em: `{saved}`")
                    except OSError as exc:
                        st.error(f"Não foi possível salvar: {exc}")

    return True
