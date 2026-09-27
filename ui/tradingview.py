"""HTML for TradingView widgets, ready for ``st.iframe``.

The app itself makes no market-data calls: each builder returns markup that
loads TradingView's own script in the viewer's browser, and the widget
fetches its data from TradingView directly.

Two widget generations are used, and they are embedded differently:

* **Web components** (Ticker Tag, Mini Chart): one ES module script per
  widget type plus a custom element whose attributes are the settings.
* **Legacy iframe widget** (Top Stories): a container div plus a classic
  script whose *body* is the JSON config.

**Theme is decided in the browser, not in Python.** ``st.context.theme`` is
documented to be wrong on a session's first load (streamlit#11920), so every
page carries a small bootstrap that reads the Streamlit app's background from
the parent document (``st.iframe`` HTML is same-origin) and sets
``color-scheme``. Web components with no ``theme`` attribute follow
``color-scheme``; Top Stories is given its ``colorTheme`` when its script is
created at runtime. The Python-side theme is only the fallback.

Every option used here is documented in docs/TRADINGVIEW_WIDGETS.md. Pure
functions - no Streamlit import - so they are unit tested directly.
"""

import html
import json
from string import Template
from typing import Iterable, Optional, Sequence

from market.tradingview_symbols import Category, Instrument, effective_time_frame, symbol_page_url

WIDGET_HOST = "https://widgets.tradingview-widget.com"
LOCALE = "en"
TOP_STORIES_SCRIPT = "https://s3.tradingview.com/external-embedding/embed-widget-timeline.js"

TICKER_TAG_SIZES = ("small", "medium", "large")
CHART_TYPES = ("Area", "Line", "Baseline")
THEMES = ("light", "dark")
# Top Stories feeds offered in the UI, keyed by the ``market`` value TradingView
# expects. "futures" is deliberately absent: checked 2026-09-26 it served only
# 2023 stories, as did per-symbol feeds (months old). See the doc's Top Stories
# section before adding it back.
NEWS_MARKETS = {
    "all_symbols": "All markets",
    "forex": "Currencies",
    "index": "Indices",
    "stock": "Stocks",
}

# Measured in Chrome (2026-09-26): the hover pop-up a ticker tag opens is
# ~215px tall and drops below the tag. An iframe clips anything outside its
# box, so the tag page reserves this much room under its last row.
TAG_POPUP_ROOM = 230
_TAG_ROW_HEIGHT = {"small": 28, "medium": 34, "large": 44}
CHART_GAP = 12


def module_script(tag: str) -> str:
    """The one script that defines a web-component widget (``tv-mini-chart`` etc)."""
    return f'<script type="module" src="{WIDGET_HOST}/w/{LOCALE}/{tag}.js"></script>'


def _theme(theme: Optional[str]) -> str:
    return theme if theme in THEMES else "light"


def _attrs(pairs) -> str:
    """Render attributes; ``True`` means a bare boolean attribute, ``None``/``False`` omits it."""
    out = []
    for name, value in pairs:
        if value is None or value is False:
            continue
        if value is True:
            out.append(name)
        else:
            out.append(f'{name}="{html.escape(str(value), quote=True)}"')
    return " ".join(out)


# -- single widgets ------------------------------------------------------------


def ticker_tag(
    instrument: Instrument,
    *,
    size: str = "medium",
    theme: Optional[str] = None,
    show_label: bool = True,
) -> str:
    """A ``<tv-ticker-tag>`` pill. With ``show_label`` the pill shows our label, not the ticker.

    ``preserve-text`` makes the widget keep the element's inner text as its
    display name - that is how a proxy such as ``BSE:NIFTYBEES`` reads as
    "Nifty 50 (NIFTYBEES)". ``theme=None`` follows the page's colour scheme.
    """
    attrs = _attrs(
        [
            ("symbol", instrument.symbol),
            ("size", size if size in TICKER_TAG_SIZES else "medium"),
            ("theme", theme if theme in THEMES else None),
            ("preserve-text", show_label),
        ]
    )
    text = html.escape(instrument.label) if show_label else ""
    return f"<tv-ticker-tag {attrs}>{text}</tv-ticker-tag>"


def mini_chart(
    instrument: Instrument,
    *,
    time_frame: str = "1D",
    chart_type: str = "Area",
    theme: Optional[str] = None,
    show_time_scale: bool = False,
    transparent: bool = True,
) -> str:
    """A ``<tv-mini-chart>``; end-of-day symbols are lifted to a range they can draw."""
    attrs = _attrs(
        [
            ("symbol", instrument.symbol),
            ("time-frame", effective_time_frame(instrument, time_frame)),
            ("line-chart-type", chart_type if chart_type in CHART_TYPES else "Area"),
            ("theme", theme if theme in THEMES else None),
            ("show-time-scale", show_time_scale),
            ("transparent", transparent),
        ]
    )
    return f"<tv-mini-chart {attrs}></tv-mini-chart>"


def top_stories_config(
    *,
    market: str = "all_symbols",
    symbol: Optional[str] = None,
    theme: str = "light",
    display_mode: str = "regular",
    transparent: bool = False,
) -> dict:
    """Top Stories JSON config, filling its container (``width``/``height`` 100%).

    Feed selection follows TradingView's wizard: a ``symbol`` wins, then a
    ``market``; ``all_symbols`` sends neither key.

    ``transparent`` defaults to False: this widget renders inside its own
    iframe, and when that iframe's colour scheme differs from the page's the
    browser paints it opaque white - light text on white in dark mode.
    """
    config = {
        "displayMode": display_mode,
        "colorTheme": _theme(theme),
        "isTransparent": transparent,
        "locale": LOCALE,
        "width": "100%",
        "height": "100%",
    }
    if symbol:
        config["feedMode"] = "symbol"
        config["symbol"] = symbol
    elif market and market != "all_symbols":
        config["feedMode"] = "market"
        config["market"] = market
    else:
        config["feedMode"] = "all_symbols"
    return config


def _script_json(config: dict) -> str:
    # "</" cannot appear inside a <script> body; JSON allows escaping the slash.
    return json.dumps(config, indent=2).replace("</", "<\\/")


_TOP_STORIES_SHELL = (
    '<div class="tradingview-widget-container" style="height:100%;width:100%">'
    '<div class="tradingview-widget-container__widget" '
    'style="height:calc(100% - 32px);width:100%"></div>'
    '<div class="tradingview-widget-copyright">'
    '<a href="https://www.tradingview.com/news/top-providers/tradingview/" '
    'rel="noopener nofollow" target="_blank"><span class="blue-text">Top stories</span></a>'
    '<span class="trademark"> by TradingView</span></div>'
    "{script}</div>"
)


def top_stories(*, runtime_theme: bool = False, **config_kwargs) -> str:
    """The Top Stories widget.

    Static (default): TradingView's own embed - the config is the script body.
    ``runtime_theme=True``: the script is created by JavaScript after the page
    bootstrap has decided the theme, and ``colorTheme`` is taken from it.
    """
    config = top_stories_config(**config_kwargs)
    if not runtime_theme:
        script = f'<script type="text/javascript" src="{TOP_STORIES_SCRIPT}" async>\n{_script_json(config)}\n</script>'
        return _TOP_STORIES_SHELL.format(script=script)
    script = (
        "<script>(function () {"
        f"var cfg = {_script_json(config)};"
        "cfg.colorTheme = document.documentElement.dataset.theme || cfg.colorTheme;"
        "var s = document.createElement('script');"
        f"s.type = 'text/javascript'; s.async = true; s.src = '{TOP_STORIES_SCRIPT}';"
        "s.text = JSON.stringify(cfg);"
        "document.currentScript.parentNode.appendChild(s);"
        "})();</script>"
    )
    return _TOP_STORIES_SHELL.format(script=script)


# -- whole pages for st.iframe -------------------------------------------------

# Runs before any widget script. Picks light/dark from the Streamlit app's
# background, then keeps watching so a theme switch in Streamlit's settings
# menu carries over. Pages whose widgets cannot re-theme in place (Top
# Stories) mark <html data-reload-on-theme-change> and reload instead.
_THEME_BOOTSTRAP = Template("""<script>
(function () {
  var FALLBACK = "$fallback";
  function luminance(css) {
    var m = css && css.match(/[\\d.]+/g);
    if (!m || m.length < 3 || (m.length > 3 && Number(m[3]) === 0)) return null;
    return 0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2];
  }
  function detect() {
    try {
      var doc = window.parent.document;
      var els = [doc.querySelector('[data-testid="stApp"]'), doc.querySelector(".stApp"), doc.body];
      for (var i = 0; i < els.length; i++) {
        if (!els[i]) continue;
        var bg = getComputedStyle(els[i]).backgroundColor;
        var l = luminance(bg);
        if (l !== null) return { theme: l < 128 ? "dark" : "light", bg: bg };
      }
    } catch (e) {}
    return { theme: FALLBACK, bg: "" };
  }
  var root = document.documentElement;
  // The background is copied, not left transparent: an iframe whose
  // color-scheme differs from its parent's gets an opaque canvas that
  // would show as a slightly-off rectangle.
  function apply(d) { root.dataset.theme = d.theme; root.style.colorScheme = d.theme; root.style.background = d.bg; }
  apply(detect());
  setInterval(function () {
    var now = detect();
    if (now.theme === root.dataset.theme) return;
    if (root.hasAttribute("data-reload-on-theme-change")) location.reload();
    else apply(now);
  }, 2000);
})();
</script>""")

_PAGE_CSS = Template("""
html, body { height: 100%; margin: 0; background: transparent; }
body { font-family: "Source Sans Pro", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       color: light-dark(#31333f, #fafafa); font-size: 14px; }
a { color: light-dark(#1a5fd6, #6ea8ff); }
.muted, .trademark { color: light-dark(#6b6f76, #9ca0a8); }
.section { margin: 0 0 18px; }
.section h3 { font-size: 16px; font-weight: 600; margin: 0 0 2px; }
.section .caption { color: light-dark(#6b6f76, #9ca0a8); font-size: 13px; margin: 0 0 8px; }
.section .missing { color: light-dark(#6b6f76, #9ca0a8); font-size: 13px; margin: 8px 0 0; }
.tags { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; padding: 2px; }
.popup-room { height: ${popup_room}px; }
.charts { display: grid; grid-template-columns: repeat($columns, minmax(0, 1fr));
          grid-auto-rows: ${row}px; gap: ${gap}px; padding: 2px; }
.charts tv-mini-chart { display: block; height: 100%; }
.blue-text { color: #2962ff; }
.tradingview-widget-copyright { font-size: 12px; line-height: 32px; text-align: center; }
.tradingview-widget-copyright a { text-decoration: none; }
""")


def widget_page(
    body: str,
    *,
    fallback_theme: Optional[str] = "light",
    scripts: Iterable[str] = (),
    popup_room: int = 0,
    chart_columns: int = 3,
    chart_row_height: int = 190,
    reload_on_theme_change: bool = False,
) -> str:
    """Wrap widget markup in a complete document for ``st.iframe``.

    ``fallback_theme`` is used only if the page cannot read the app's
    background (for example when opened outside Streamlit).
    """
    fallback = _theme(fallback_theme)
    css = _PAGE_CSS.substitute(
        {
            "popup_room": max(0, int(popup_room)),
            "columns": max(1, int(chart_columns)),
            "row": int(chart_row_height),
            "gap": CHART_GAP,
        }
    )
    html_attrs = " data-reload-on-theme-change" if reload_on_theme_change else ""
    head_scripts = "\n".join(scripts)
    return (
        f"<!doctype html><html{html_attrs} style=\"color-scheme:{fallback}\"><head><meta charset='utf-8'>"
        f"<style>{css}</style>{_THEME_BOOTSTRAP.substitute(fallback=fallback)}{head_scripts}"
        f"</head><body>{body}</body></html>"
    )


def unavailable_links_html(category: Category) -> str:
    """'Only on tradingview.com: MCX Crude Oil ...' - links out, since no widget can show them."""
    if not category.unavailable:
        return ""
    links = " · ".join(
        f'<a href="{html.escape(symbol_page_url(u.symbol), quote=True)}" target="_blank" '
        f'rel="noopener" title="{html.escape(u.symbol)} - {html.escape(u.reason)}">'
        f"{html.escape(u.label)} ↗</a>"
        for u in category.unavailable
    )
    return f'<p class="missing">Only on tradingview.com: {links}</p>'


def ticker_sections_page(
    categories: Sequence[Category],
    *,
    fallback_theme: Optional[str] = "light",
    size: str = "large",
    popup_room: int = TAG_POPUP_ROOM,
) -> str:
    """Every category as a titled row of ticker tags, in one document.

    One iframe rather than one per category: a tag's hover pop-up can then
    overlap the rows below it instead of being clipped at its own row.
    """
    sections = []
    for c in categories:
        tags = "".join(ticker_tag(i, size=size) for i in c.instruments)
        caption = f'<p class="caption">{html.escape(c.caption)}</p>' if c.caption else ""
        sections.append(
            f'<div class="section"><h3>{html.escape(c.title)}</h3>{caption}'
            f'<div class="tags">{tags}</div>{unavailable_links_html(c)}</div>'
        )
    body = "".join(sections) + '<div class="popup-room"></div>'
    return widget_page(
        body,
        fallback_theme=fallback_theme,
        scripts=[module_script("tv-ticker-tag")],
        popup_room=popup_room,
    )


def ticker_sections_height(
    categories: Sequence[Category], *, size: str = "large", popup_room: int = TAG_POPUP_ROOM
) -> int:
    """Iframe height for ``ticker_sections_page``: title, caption, one tag row, links, spacing."""
    row = _TAG_ROW_HEIGHT.get(size, _TAG_ROW_HEIGHT["medium"])
    total = 0
    for c in categories:
        total += 22 + 18 + 8  # h3 + caption line + its margin
        total += row + 4
        total += 26 if c.unavailable else 0
        total += 18  # section margin
    return total + popup_room


def mini_charts_page(
    instruments: Sequence[Instrument],
    *,
    time_frame: str,
    chart_type: str,
    show_time_scale: bool,
    columns: int,
    row_height: int,
    fallback_theme: Optional[str] = "light",
) -> str:
    charts = "".join(
        mini_chart(i, time_frame=time_frame, chart_type=chart_type, show_time_scale=show_time_scale)
        for i in instruments
    )
    return widget_page(
        f'<div class="charts">{charts}</div>',
        fallback_theme=fallback_theme,
        scripts=[module_script("tv-mini-chart")],
        chart_columns=columns,
        chart_row_height=row_height,
    )


def chart_grid_height(count: int, *, columns: int, row_height: int, gap: int = CHART_GAP) -> int:
    """Pixel height of a chart grid holding ``count`` charts in ``columns`` columns."""
    rows = max(1, -(-count // max(1, columns)))
    return rows * row_height + (rows - 1) * gap + 6


def top_stories_page(*, market: str, fallback_theme: Optional[str] = "light") -> str:
    return widget_page(
        top_stories(market=market, theme=_theme(fallback_theme), runtime_theme=True),
        fallback_theme=fallback_theme,
        reload_on_theme_change=True,
    )
