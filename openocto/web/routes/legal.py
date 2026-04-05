"""Legal routes — license, terms of service, brand guidelines."""

from __future__ import annotations

import html as html_mod
import re
from pathlib import Path

import aiohttp_jinja2
from aiohttp import web

from openocto import __version__


def _md_to_html(text: str) -> str:
    """Minimal Markdown → HTML converter (no external deps).

    Handles: headings, bold, links, unordered/ordered lists,
    horizontal rules, simple tables, paragraphs.
    """
    lines = text.split("\n")
    out: list[str] = []
    list_tag: str | None = None  # "ul" or "ol"
    in_table = False

    def _close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def _close_table():
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    for line in lines:
        stripped = line.strip()

        # Blank line — close open blocks
        if not stripped:
            _close_list()
            _close_table()
            out.append("")
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$|^\*{3,}$", stripped):
            _close_list()
            _close_table()
            out.append("<hr>")
            continue

        # Table separator row (|---|---|) — skip
        if re.match(r"^\|[-\s|:]+\|$", stripped):
            continue

        # Table row
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                _close_list()
                out.append('<table role="grid"><thead><tr>')
                for cell in cells:
                    content = _md_inline(html_mod.escape(cell))
                    out.append(f"  <th>{content}</th>")
                out.append("</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>")
                for cell in cells:
                    content = _md_inline(html_mod.escape(cell))
                    out.append(f"  <td>{content}</td>")
                out.append("</tr>")
            continue

        _close_table()

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            _close_list()
            level = len(m.group(1))
            content = _md_inline(html_mod.escape(m.group(2)))
            out.append(f"<h{level}>{content}</h{level}>")
            continue

        # Unordered list items (- item)
        if stripped.startswith("- "):
            if list_tag != "ul":
                _close_list()
                out.append("<ul>")
                list_tag = "ul"
            content = _md_inline(html_mod.escape(stripped[2:]))
            out.append(f"  <li>{content}</li>")
            continue

        # Ordered list items (1. item)
        m_ol = re.match(r"^\d+\.\s+(.*)", stripped)
        if m_ol:
            if list_tag != "ol":
                _close_list()
                out.append("<ol>")
                list_tag = "ol"
            content = _md_inline(html_mod.escape(m_ol.group(1)))
            out.append(f"  <li>{content}</li>")
            continue

        # Regular paragraph
        _close_list()
        content = _md_inline(html_mod.escape(stripped))
        out.append(f"<p>{content}</p>")

    _close_list()
    _close_table()

    return "\n".join(out)


def _md_inline(text: str) -> str:
    """Convert inline markdown: **bold**, [link](url)."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Links — unescape &amp; inside href since we pre-escaped
    def _link_repl(m: re.Match) -> str:
        label = m.group(1)
        href = m.group(2).replace("&amp;", "&")
        return f'<a href="{href}">{label}</a>'

    text = re.sub(r"\[(.+?)\]\((.+?)\)", _link_repl, text)
    return text

routes = web.RouteTableDef()

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # openocto/ repo root


@routes.get("/legal/license")
@aiohttp_jinja2.template("legal_license.html")
async def license_page(request: web.Request) -> dict:
    license_path = _PROJECT_ROOT / "LICENSE.md"
    license_html = ""
    if license_path.exists():
        license_html = _md_to_html(license_path.read_text(encoding="utf-8"))
    return {
        "page": "legal",
        "version": __version__,
        "license_html": license_html,
    }


@routes.get("/legal/terms")
@aiohttp_jinja2.template("legal_terms.html")
async def terms_page(request: web.Request) -> dict:
    terms_path = _PROJECT_ROOT / "TERMS.md"
    terms_html = ""
    if terms_path.exists():
        terms_html = _md_to_html(terms_path.read_text(encoding="utf-8"))
    return {
        "page": "legal",
        "version": __version__,
        "terms_html": terms_html,
    }


@routes.get("/legal/brand")
@aiohttp_jinja2.template("legal_brand.html")
async def brand_page(request: web.Request) -> dict:
    return {
        "page": "legal",
        "version": __version__,
    }


@routes.get("/api/legal/terms-accepted")
async def check_terms(request: web.Request) -> web.Response:
    """Check if terms have been accepted (via cookie)."""
    accepted = request.cookies.get("openocto_terms_accepted", "")
    return web.json_response({"accepted": accepted == "1"})


@routes.post("/api/legal/accept-terms")
async def accept_terms(request: web.Request) -> web.Response:
    """Mark terms as accepted (set cookie)."""
    resp = web.json_response({"accepted": True})
    resp.set_cookie(
        "openocto_terms_accepted", "1",
        max_age=365 * 24 * 3600,  # 1 year
        httponly=True,
        samesite="Lax",
    )
    return resp
