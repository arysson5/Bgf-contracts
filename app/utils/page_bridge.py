"""Ponte Streamlit v2: clique direito e Shift+roda no documento da página.

O iframe `components.html` (about:srcdoc) não pode alterar a URL da app
(`allow-top-navigation` ausente). O componente v2 do Streamlit 1.60 roda no
DOM da página e devolve eventos ao Python com `setTriggerValue`.
"""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

_JS = r"""
export default function (component) {
  const { data, setTriggerValue } = component;
  const cfg = window.__bgfCfg || (window.__bgfCfg = {});
  cfg.syncEnabled = !data || data.sync_enabled !== false;
  cfg.comments = !!(data && data.comments);
  cfg.setTriggerValue = setTriggerValue;

  const css = (data && data.css) || "";
  let style = document.getElementById("bgf-page-bridge-css");
  if (!style) {
    style = document.createElement("style");
    style.id = "bgf-page-bridge-css";
    document.head.appendChild(style);
  }
  if (css) style.textContent = css;

  function emit(payload) {
    payload.ts = Date.now();
    const fn = cfg.setTriggerValue;
    if (typeof fn === "function") {
      fn("event", JSON.stringify(payload));
    }
  }

  function findPeers(el) {
    const grid = el.closest(".bgf-sbs-grid, .bgf-diff-side, .bgf-diff-wrap");
    if (grid) {
      const cols = grid.querySelectorAll(".bgf-sbs-col, .bgf-diff-col, .bgf-sync-scroll");
      if (cols.length >= 2) return cols;
    }
    const groupCls = Array.from(el.classList).find(function (c) {
      return c.indexOf("bgf-sg-") === 0;
    });
    if (groupCls) {
      const root = el.getRootNode();
      const local = root.querySelectorAll ? root.querySelectorAll("." + groupCls) : [];
      if (local.length >= 2) return local;
      const global = document.querySelectorAll("." + groupCls);
      if (global.length >= 2) return global;
    }
    const outer = el.closest(".bgf-sbs-outer");
    if (outer) {
      const cols = outer.querySelectorAll(".bgf-sbs-col");
      if (cols.length >= 2) return cols;
    }
    return [];
  }

  function onWheel(e) {
    if (!cfg.syncEnabled) return;
    if (!e.shiftKey) return;
    const t = e.target && e.target.nodeType === 3 ? e.target.parentElement : e.target;
    const el = t && t.closest
      ? t.closest(".bgf-sbs-col, .bgf-diff-col, .bgf-sync-scroll")
      : null;
    if (!el) return;
    const peers = findPeers(el);
    if (!peers || peers.length < 2) return;
    const delta = e.deltaY !== 0 ? e.deltaY : e.deltaX;
    if (!delta) return;
    e.preventDefault();
    e.stopPropagation();
    Array.from(peers).forEach(function (p) {
      p.scrollTop += delta;
    });
  }

  function pctOnImg(e, img) {
    const r = img.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    const x = ((e.clientX - r.left) / r.width) * 100;
    const y = ((e.clientY - r.top) / r.height) * 100;
    return { x: Math.max(0, Math.min(100, x)), y: Math.max(0, Math.min(100, y)) };
  }

  function clearSel(wrap) {
    if (!wrap) return;
    const old = wrap.querySelector(".bgf-sel-rect");
    if (old) old.remove();
    delete wrap.dataset.selX0;
    delete wrap.dataset.selY0;
    delete wrap.dataset.selX1;
    delete wrap.dataset.selY1;
  }

  function paraIdx(el) {
    if (!el) return "";
    const m = String(el.className || "").match(/bgf-para-idx-(\d+)/);
    if (m) return m[1];
    return el.getAttribute("data-bgf-para") || "";
  }

  function onClick(e) {
    if (!cfg.comments) return;
    const t = e.target;
    if (!t || !t.closest) return;
    const btn = t.closest(".bgf-balloon");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    emit({ type: "cmt", id: btn.getAttribute("data-cmt-id") || "" });
  }

  let drag = null;
  function onDown(e) {
    if (!cfg.comments || e.button !== 0) return;
    const t = e.target;
    if (!t || !t.closest) return;
    if (t.closest(".bgf-balloon")) return;
    const wrap = t.closest(".bgf-page-wrap.bgf-comment-target");
    if (!wrap) return;
    const img = wrap.querySelector("img");
    if (!img) return;
    const p = pctOnImg(e, img);
    if (!p) return;
    drag = { wrap: wrap, start: p };
    clearSel(wrap);
    e.preventDefault();
  }

  function onMove(e) {
    if (!drag) return;
    const img = drag.wrap.querySelector("img");
    const p = pctOnImg(e, img);
    if (!p) return;
    let box = drag.wrap.querySelector(".bgf-sel-rect");
    if (!box) {
      box = document.createElement("div");
      box.className = "bgf-sel-rect";
      drag.wrap.appendChild(box);
    }
    const x0 = Math.min(drag.start.x, p.x);
    const y0 = Math.min(drag.start.y, p.y);
    const x1 = Math.max(drag.start.x, p.x);
    const y1 = Math.max(drag.start.y, p.y);
    box.style.left = x0 + "%";
    box.style.top = y0 + "%";
    box.style.width = (x1 - x0) + "%";
    box.style.height = (y1 - y0) + "%";
  }

  function onUp(e) {
    if (!drag) return;
    const img = drag.wrap.querySelector("img");
    const p = pctOnImg(e, img) || drag.start;
    const x0 = Math.min(drag.start.x, p.x);
    const y0 = Math.min(drag.start.y, p.y);
    const x1 = Math.max(drag.start.x, p.x);
    const y1 = Math.max(drag.start.y, p.y);
    if ((x1 - x0) > 1.2 && (y1 - y0) > 1.0) {
      drag.wrap.dataset.selX0 = x0.toFixed(2);
      drag.wrap.dataset.selY0 = y0.toFixed(2);
      drag.wrap.dataset.selX1 = x1.toFixed(2);
      drag.wrap.dataset.selY1 = y1.toFixed(2);
    } else {
      clearSel(drag.wrap);
    }
    drag = null;
  }

  function onContext(e) {
    if (!cfg.comments) return;
    let t = e.target;
    if (t && t.nodeType === 3) t = t.parentElement;
    if (!t || !t.closest) return;

    const docxEl = t.closest(".bgf-docx-p, .bgf-docx-balloon-row, .bgf-docx-text");
    const pageWrap = t.closest(".bgf-page-wrap.bgf-comment-target");
    const docxCol = t.closest(".bgf-docx-col.bgf-comment-target");
    let kind = "";
    let page = "1";
    let para = "";
    let host = null;

    if (docxEl || docxCol) {
      kind = "docx";
      let anchor = docxEl
        ? (docxEl.classList.contains("bgf-docx-text")
          ? docxEl.closest(".bgf-docx-balloon-row") || docxEl
          : docxEl)
        : null;
      if (!anchor && docxCol) {
        const nodes = docxCol.querySelectorAll("[class*='bgf-para-idx-']");
        let best = null;
        let bestDist = 1e9;
        for (let i = 0; i < nodes.length; i++) {
          const rr = nodes[i].getBoundingClientRect();
          if (e.clientY >= rr.top && e.clientY <= rr.bottom) {
            best = nodes[i];
            break;
          }
          const mid = (rr.top + rr.bottom) / 2;
          const d = Math.abs(e.clientY - mid);
          if (d < bestDist) {
            bestDist = d;
            best = nodes[i];
          }
        }
        anchor = best;
      }
      if (!anchor) return;
      para = paraIdx(anchor);
      page = String((parseInt(para, 10) || 0) + 1);
    } else if (pageWrap) {
      kind = "pdf";
      host = pageWrap;
      page = pageWrap.getAttribute("data-bgf-page") || "1";
    } else {
      return;
    }

    e.preventDefault();
    e.stopPropagation();
    const selText = (window.getSelection && window.getSelection().toString() || "")
      .trim()
      .slice(0, 400);
    const payload = {
      type: "rc",
      kind: kind,
      page: page,
      para: para,
      sel: selText
    };
    if (kind === "pdf" && host) {
      const imgEl = host.querySelector("img");
      const p = imgEl ? pctOnImg(e, imgEl) : null;
      if (p) {
        payload.x = p.x.toFixed(2);
        payload.y = p.y.toFixed(2);
      }
      if (host.dataset && host.dataset.selX0) {
        payload.x0 = host.dataset.selX0;
        payload.y0 = host.dataset.selY0;
        payload.x1 = host.dataset.selX1;
        payload.y1 = host.dataset.selY1;
      }
    }
    emit(payload);
  }

  const prev = window.__bgfHandlers;
  if (prev) {
    try { document.removeEventListener("wheel", prev.onWheel, true); } catch (err) {}
    try { document.removeEventListener("click", prev.onClick, true); } catch (err) {}
    try { document.removeEventListener("mousedown", prev.onDown, true); } catch (err) {}
    try { document.removeEventListener("mousemove", prev.onMove, true); } catch (err) {}
    try { document.removeEventListener("mouseup", prev.onUp, true); } catch (err) {}
    try { document.removeEventListener("contextmenu", prev.onContext, true); } catch (err) {}
  }
  try { document.removeEventListener("wheel", document.__bgfSyncScrollHandler, true); } catch (err) {}
  try { document.removeEventListener("click", document.__bgfCmtClickHandler, true); } catch (err) {}
  try { document.removeEventListener("contextmenu", document.__bgfCmtCtxHandler, true); } catch (err) {}
  try { document.removeEventListener("mousedown", document.__bgfCmtDownHandler, true); } catch (err) {}
  try { document.removeEventListener("mousemove", document.__bgfCmtMoveHandler, true); } catch (err) {}
  try { document.removeEventListener("mouseup", document.__bgfCmtUpHandler, true); } catch (err) {}

  document.__bgfSyncScrollHandler = onWheel;
  document.__bgfCmtClickHandler = onClick;
  document.__bgfCmtDownHandler = onDown;
  document.__bgfCmtMoveHandler = onMove;
  document.__bgfCmtUpHandler = onUp;
  document.__bgfCmtCtxHandler = onContext;
  window.__bgfHandlers = {
    onWheel: onWheel,
    onClick: onClick,
    onDown: onDown,
    onMove: onMove,
    onUp: onUp,
    onContext: onContext
  };

  document.addEventListener("wheel", onWheel, { passive: false, capture: true });
  document.addEventListener("click", onClick, true);
  document.addEventListener("mousedown", onDown, true);
  document.addEventListener("mousemove", onMove, true);
  document.addEventListener("mouseup", onUp, true);
  document.addEventListener("contextmenu", onContext, true);

  return function () {
    try { document.removeEventListener("wheel", onWheel, true); } catch (err) {}
    try { document.removeEventListener("click", onClick, true); } catch (err) {}
    try { document.removeEventListener("mousedown", onDown, true); } catch (err) {}
    try { document.removeEventListener("mousemove", onMove, true); } catch (err) {}
    try { document.removeEventListener("mouseup", onUp, true); } catch (err) {}
    try { document.removeEventListener("contextmenu", onContext, true); } catch (err) {}
  };
}
"""

_COMPONENT = None

_BRIDGE_CSS = """
.bgf-sbs-col, .bgf-diff-col.bgf-sync-scroll {
  overscroll-behavior: contain;
}
.bgf-docx-col.bgf-comment-target .bgf-docx-p,
.bgf-docx-col.bgf-comment-target .bgf-docx-balloon-row { cursor: context-menu; }
"""


def _get_component():
    global _COMPONENT
    if _COMPONENT is None:
        _COMPONENT = st.components.v2.component(
            "bgf_page_bridge",
            js=_JS,
            isolate_styles=False,
        )
    return _COMPONENT


def _parse_event(raw: Any) -> dict | None:
    if isinstance(raw, list):
        for item in reversed(raw):
            parsed = _parse_event(item)
            if parsed:
                return parsed
        return None
    if raw in (None, "", False):
        return None
    if isinstance(raw, dict):
        return raw if raw.get("type") else None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) and parsed.get("type") else None
    return None


def _on_event_change() -> None:
    return None


def mount_page_bridge(
    *,
    comments: bool = False,
    sync_enabled: bool = True,
    extra_css: str = "",
) -> dict | None:
    """Monta o componente v2 e devolve o evento (clique direito / balão), se houver."""
    component = _get_component()
    result = component(
        data={
            "comments": comments,
            "sync_enabled": sync_enabled,
            "css": _BRIDGE_CSS + (extra_css or ""),
        },
        key="bgf_page_bridge",
        height=1,
        width=1,
        on_event_change=_on_event_change,
    )
    return _parse_event(getattr(result, "event", None))
