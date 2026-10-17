"""The jobs behind ``scripts/kite.py``, ``scripts/dhan.py`` and ``scripts/indmoney.py``.

Each module does one job and exposes ``run(args) -> int`` (0 ok, 1 failed, 2 partly done).
The broker scripts own the command line, the logging set-up and the order the jobs run in.
"""
