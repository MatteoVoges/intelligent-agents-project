"""Branding and colour theme. Presentation only — nothing here affects behaviour."""

from __future__ import annotations

from nicegui import ui

APP_NAME = "Francois"
TAGLINE = "A local assistant, served at home."

ACCENT = "#7C5CFF"  # vivid violet — the single accent, used sparingly
ACCENT_SOFT = "#A594FF"
BG = "#0C0C11"  # page
SURFACE = "#15151E"  # header, drawer, composer, cards
SURFACE_2 = "#1E1E2B"  # raised: user bubbles, hover
BORDER = "#282836"
TEXT = "#F3F3F7"
MUTED = "#8C8C9E"

_CSS = f"""
:root {{
  --fr-accent: {ACCENT};
  --fr-bg: {BG};
  --fr-surface: {SURFACE};
  --fr-surface-2: {SURFACE_2};
  --fr-border: {BORDER};
  --fr-text: {TEXT};
  --fr-muted: {MUTED};
}}
body {{ color: var(--fr-text); }}
.fr-surface {{ background: var(--fr-surface); }}
.fr-raised {{ background: var(--fr-surface-2); }}
.fr-border {{ border-color: var(--fr-border) !important; }}
.fr-muted {{ color: var(--fr-muted); }}
.fr-accent {{ color: var(--fr-accent); }}
.fr-hover:hover {{ background: var(--fr-surface-2); }}
.fr-active {{ background: var(--fr-surface-2); box-shadow: inset 2px 0 0 0 var(--fr-accent); }}

/* Drawer children live in Quasar's .q-drawer__content, not on the drawer element itself —
   the full-height column that pins the footer buttons has to be declared there. */
.fr-sidebar .q-drawer__content {{
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}}

/* the composer wraps the input *and* the model picker, so it owns the focus ring */
.fr-composer {{
  background: var(--fr-surface);
  border: 1px solid var(--fr-border);
  transition: border-color .15s ease;
}}
.fr-composer:focus-within {{ border-color: var(--fr-accent); }}

::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{ background: var(--fr-surface-2); border-radius: 6px; }}
::-webkit-scrollbar-thumb:hover {{ background: #2E2E40; }}
::-webkit-scrollbar-track {{ background: transparent; }}
"""


def apply() -> None:
    """Dark page, white text, one vibrant accent. Call once per page."""
    ui.dark_mode().enable()
    ui.colors(primary=ACCENT, secondary=ACCENT_SOFT, accent=ACCENT, dark=SURFACE, dark_page=BG)
    ui.add_css(_CSS)
