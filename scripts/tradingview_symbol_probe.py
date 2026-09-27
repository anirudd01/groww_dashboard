"""Check which TradingView symbols actually stream in widgets - in your own browser.

TradingView widgets only show exchanges licensed for embedding. The only
reliable test is to render the widget and look: this writes a page of Mini
Charts, one per symbol, serves it on localhost and opens it.

    python scripts/tradingview_symbol_probe.py MCX:CRUDEOIL1! TVC:USOIL BSE:SENSEX@3M
    python scripts/tradingview_symbol_probe.py --dashboard     # everything the dashboard charts

``SYMBOL@RANGE`` sets the Mini Chart time-frame (default 1D). What each
outcome means - "Permission denied", "Invalid Symbol", "Unsupported interval",
"Something went wrong" - is in docs/TRADINGVIEW_WIDGETS.md. Record new
findings there and in market/tradingview_symbols.py.

Uses only the standard library. Stop it with Ctrl+C.
"""

import argparse
import functools
import html
import http.server
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market.tradingview_symbols import CATEGORIES  # noqa: E402

SCRIPT = "https://widgets.tradingview-widget.com/w/en/tv-mini-chart.js"


def parse(arg: str):
    symbol, _, time_frame = arg.partition("@")
    return symbol.strip(), (time_frame.strip() or "1D")


def page(probes) -> str:
    cells = "\n".join(
        f'<div class="c"><b>{html.escape(s)} [{html.escape(tf)}]</b>'
        f'<tv-mini-chart symbol="{html.escape(s, quote=True)}" time-frame="{html.escape(tf, quote=True)}">'
        f"</tv-mini-chart></div>"
        for s, tf in probes
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>TradingView symbol probe</title>
<script type="module" src="{SCRIPT}"></script>
<style>body{{font:13px sans-serif;margin:12px}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}}
.c{{height:200px;border:1px solid #ccc;display:flex;flex-direction:column;padding:4px}}
tv-mini-chart{{flex:1}}</style></head><body><div class="g">{cells}</div></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("symbols", nargs="*", help="EXCHANGE:TICKER, optionally @RANGE (e.g. BSE:SENSEX@3M)")
    ap.add_argument("--dashboard", action="store_true", help="probe every symbol the dashboard uses")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    probes = [parse(s) for s in args.symbols]
    if args.dashboard:
        for c in CATEGORIES:
            probes += [(i.symbol, i.min_time_frame or "1D") for i in c.instruments]
            probes += [(u.symbol, "1D") for u in c.unavailable]
    if not probes:
        ap.error("give at least one symbol, or --dashboard")

    root = Path(tempfile.mkdtemp(prefix="tv_probe_"))
    (root / "index.html").write_text(page(probes), encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/index.html"
    print(f"Probing {len(probes)} symbol(s) at {url} - Ctrl+C to stop")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
