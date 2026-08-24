"""Exportação do documento comentado — download e caminho manual (sem tkinter)."""

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


def _export_title_for(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return "Salvar PDF comentado"
    if ext in (".docx", ".doc"):
        return "Salvar DOCX comentado"
    return "Exportar documento comentado"


def _suggest_export_name(work_path: str, version) -> str:
    stem = Path(work_path).stem
    suffix = Path(work_path).suffix
    label = getattr(version, "label", None) or ""
    if label and label not in stem:
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in label).strip()
        if safe:
            return f"{stem}_{safe}{suffix}"
    return Path(work_path).name


def _enforce_source_suffix(name: str, source_path: str | Path) -> str:
    """Garante que o nome de download/export mantém a extensão do arquivo de origem."""
    src_suffix = Path(source_path).suffix.lower()
    if not src_suffix:
        return name
    stem = Path(name).stem if name else Path(source_path).stem
    return f"{stem}{src_suffix}"


def get_annotated_work_path(version) -> str | None:
    bundle = get_comments_bundle(version.id, version.contract_id)
    work = bundle.annotated_file_path
    if work and Path(work).exists():
        return work
    path = getattr(version, "file_path", None)
    if path and Path(path).exists() and st.session_state.get("bgf_show_save_cta") == getattr(
        version, "id", None
    ):
        return path
    return None


def _read_save_bytes(work: str) -> bytes:
    try:
        return Path(work).read_bytes()
    except OSError as exc:
        raise FileNotFoundError(
            f"Não foi possível ler «{Path(work).name}». "
            "O arquivo pode estar aberto em outro programa."
        ) from exc


def render_browser_save_button(
    version,
    *,
    key_prefix: str = "dl",
    label: str | None = None,
) -> bool:
    """Botão Salvar como do navegador, com extensão travada no arquivo de origem."""
    work = get_annotated_work_path(version) or getattr(version, "file_path", None)
    if not work or not Path(work).exists():
        return False
    suggested = _enforce_source_suffix(_suggest_export_name(work, version), work)
    ext = Path(work).suffix.upper().lstrip(".") or "arquivo"
    try:
        data = _read_save_bytes(work)
    except FileNotFoundError as exc:
        st.error(str(exc))
        return False
    st.download_button(
        label or f"💾 Salvar {ext} no computador",
        data,
        file_name=suggested,
        mime=_mime_for(work),
        key=f"{key_prefix}_browser_save",
        type="primary",
        use_container_width=True,
        help="Abre a janela Salvar como do navegador. A extensão do arquivo é mantida.",
    )
    return True


def export_file_to_path(source: str | Path, dest: str | Path) -> Path:
    """Copia o arquivo comentado para o caminho escolhido pelo usuário."""
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Arquivo de origem não encontrado: {src}")

    target = Path(dest)
    if target.is_dir():
        target = target / src.name

    if src.suffix and target.suffix.lower() != src.suffix.lower():
        target = target.with_suffix(src.suffix)

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
    title: str | None = None,
) -> bool:
    """
    Oferece download do navegador ou caminho digitado manualmente.
    Retorna True se há arquivo comentado disponível para exportar.
    """
    work = get_annotated_work_path(version)
    if not work:
        if not compact:
            st.caption("Grave comentários no PDF antes de exportar.")
        return False

    panel_title = title or _export_title_for(work)
    suggested = _suggest_export_name(work, version)
    fname_key = f"{key_prefix}_export_fname"
    if fname_key not in st.session_state:
        st.session_state[fname_key] = suggested

    if not compact:
        st.markdown(f"**{panel_title}**")
        ext_label = Path(work).suffix.upper().lstrip(".") or "arquivo"
        st.caption(
            f"Escolha onde salvar o {ext_label} com os comentários gravados. "
            "Use **Salvar como** (download) ou informe o caminho completo abaixo."
        )

    raw_name = st.text_input(
        "Nome do arquivo",
        key=fname_key,
        help=f"A extensão {Path(work).suffix} é fixa e não pode ser alterada.",
        label_visibility="visible",
    )
    file_name = _enforce_source_suffix(raw_name or suggested, work)
    if raw_name and Path(raw_name).suffix and Path(raw_name).suffix.lower() != Path(work).suffix.lower():
        st.warning(
            f"A extensão foi corrigida para **{Path(work).suffix}** "
            "para o arquivo abrir corretamente em outro computador."
        )

    try:
        data = _read_save_bytes(work)
    except FileNotFoundError as exc:
        st.error(str(exc))
        return False
    mime = _mime_for(work)
    dl_label = "💾 Salvar PDF" if Path(work).suffix.lower() == ".pdf" else "💾 Salvar DOCX"

    st.download_button(
        f"{dl_label} (escolher pasta)",
        data,
        file_name=file_name,
        mime=mime,
        key=f"{key_prefix}_dl_saveas",
        type="primary",
        use_container_width=True,
        help="Abre a janela Salvar como do navegador. Escolha a pasta de destino.",
    )

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
                        dest = path_val.strip()
                        if not Path(dest).suffix:
                            dest = str(Path(dest) / file_name)
                        else:
                            dest = str(Path(dest).with_suffix(Path(work).suffix))
                        saved = export_file_to_path(work, dest)
                        st.session_state[f"{key_prefix}_last_export"] = str(saved)
                        st.success(f"Salvo em: `{saved}`")
                    except OSError as exc:
                        st.error(f"Não foi possível salvar: {exc}")

    return True


def render_prominent_save_cta(
    version,
    *,
    key_prefix: str = "save_cta",
    message: str | None = None,
) -> bool:
    """
    Banner destacado com botão de download após gravar comentários no arquivo.
    Retorna True se o arquivo comentado está disponível.
    """
    work = get_annotated_work_path(version)
    if not work:
        return False

    ext = Path(work).suffix.upper().lstrip(".") or "arquivo"
    suggested = _suggest_export_name(work, version)
    file_name = _enforce_source_suffix(suggested, work)
    try:
        data = _read_save_bytes(work)
    except FileNotFoundError as exc:
        st.error(str(exc))
        return False
    mime = _mime_for(work)

    st.success(
        message
        or f"Comentário gravado no {ext}. **Salve o arquivo** no seu computador com o botão abaixo."
    )
    st.download_button(
        f"💾 Salvar {ext} comentado no computador",
        data,
        file_name=file_name,
        mime=mime,
        key=f"{key_prefix}_prominent_dl",
        type="primary",
        use_container_width=True,
        help="Abre a janela «Salvar como» do navegador. A extensão original é mantida.",
    )
    st.caption(f"Arquivo: `{Path(work).name}` — escolha a pasta na janela do navegador.")
    return True
