"""An always-expanded top navigation bar: every page one click away.

Streamlit's own top navigation either folds overflow into a "N more" menu or,
with sections, puts each section behind a click-to-open dropdown, and it has no
hover mode. Both cost a click before the click that matters. So
``pulse_dashboard.py`` hides Streamlit's bar (``st.navigation(..., position="hidden")``,
which still does the routing) and draws this one at the top of every page: one
row per section, a fixed-width section label, then a direct link per page.

The links are plain ``st.page_link`` calls. The only CSS (``COMPACT_CSS``) is
cosmetic: it trims Streamlit's large default top padding and draws a hairline
under the bar. If a Streamlit upgrade renames those selectors, the page falls back
to the default spacing; nothing breaks.
"""

from typing import List, Sequence, Tuple

import streamlit as st

#: (section label, [(page, short link label), ...]) in display order.
NavSpec = Sequence[Tuple[str, Sequence[Tuple["st.Page", str]]]]

#: Width of the section-label column, so every row's links start at the same x.
LABEL_WIDTH_PX = 80

#: Streamlit's main container starts ~6rem down; this pulls the bar up near the top.
#: Streamlit's header strip (with Deploy and the menu) is full width and would cover
#: the bar's first rows, so it is made transparent and lets clicks pass through,
#: except on its real buttons and links. The bar keeps 7rem clear on the right, so a
#: wrapped link never lands under Deploy or the menu.
COMPACT_CSS = """
<style>
[data-testid="stMainBlockContainer"] { padding-top: 1.25rem; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stHeader"], [data-testid="stHeader"] * { pointer-events: none; }
[data-testid="stHeader"] button, [data-testid="stHeader"] button *, [data-testid="stHeader"] a, [data-testid="stHeader"] a * { pointer-events: auto; }
.st-key-pulse_navbar {
  padding-right: 7rem;
  border-bottom: 1px solid rgba(128, 128, 128, 0.28);
  padding-bottom: 0.4rem;
  margin-bottom: 0.4rem;
}
</style>
"""


def pages_by_section(spec: NavSpec) -> dict:
    """The ``{section: [page, ...]}`` mapping ``st.navigation`` expects."""
    return {section: [page for page, _ in links] for section, links in spec}


def link_labels(spec: NavSpec) -> List[str]:
    """Every link label, in display order (for tests and docs)."""
    return [label for _, links in spec for _, label in links]


def render_navbar(spec: NavSpec) -> None:
    """One row per section: the label, then that section's page links."""
    st.html(COMPACT_CSS)
    with st.container(key="pulse_navbar", gap=None):
        for section, links in spec:
            with st.container(horizontal=True, vertical_alignment="top", gap="small"):
                st.markdown(f":gray[**{section}**]", width=LABEL_WIDTH_PX)
                # Links in their own wrapping row, so on a narrow window they wrap under each other,
                # not back under the section label.
                with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                    for page, label in links:
                        st.page_link(page, label=label, icon=page.icon or None)
