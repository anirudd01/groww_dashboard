# Quick Start Guide

Get Pulse Tester running in 5 minutes.

---

## 1️⃣ Setup Environment

```bash
# Activate local virtual environment
source .venv/Scripts/activate    # Windows (Git Bash/Bash)
# or
.venv\Scripts\activate           # Windows (PowerShell)
```

**Verify venv is active:** Python path should show `.venv`
```bash
python --version
pip list | grep streamlit
```

---

## 2️⃣ Configure Credentials

```bash
# Copy template
cp .env.example .env

# Edit .env with your Groww API credentials
# Choose ONE auth method:

# Option A: TOTP (Recommended)
GROWW_AUTH_MODE=TOTP
GROWW_API_KEY=your_api_key
GROWW_TOTP_SECRET=your_secret

# Option B: API Key + Secret
GROWW_AUTH_MODE=API_KEY
GROWW_API_KEY=your_key
GROWW_API_SECRET=your_secret

# Option C: Direct Token
GROWW_AUTH_MODE=TOKEN
GROWW_ACCESS_TOKEN=your_token
```

For the **sector heatmap** the default broker is Dhan. It needs the TOTP
login details; the code makes and renews the 24-hour access token itself and
keeps it in the shared database (`data/market.db`, git-ignored):

```bash
DHAN_CLIENT_ID=your_10_digit_client_id
DHAN_PIN=your_6_digit_dhan_pin
DHAN_TOTP_SECRET=base32_secret_from_setup_totp
```

Market data needs Dhan's paid **Data API** plan, or the websocket stays refused.

INDmoney (free, the first fallback) works the same way, with its token kept
in the shared database (`data/market.db`, git-ignored):

```bash
IND_MONEY_CLIENT_ID=client_id_shown_after_totp_setup
IND_MONEY_MPIN=your_mpin
IND_MONEY_TOTP_SECRET=base32_setup_key
```

### Fill the local database (first run)

The heatmap's universes (Nifty 50, Nifty Next 50) and every broker's instrument ids are
downloaded by a script, never by the dashboard. On a fresh checkout run, once:

```bash
python scripts/kite_login.py           # Kite only: once per trading day
python scripts/dhan.py --master        # NSE's index lists, Dhan ids, MCX futures, weights, movers close
python scripts/kite.py --master        # NSE's index lists, Kite ids, then the F&O history + 1-minute bars
python scripts/indmoney.py --master    # INDmoney ids (if you use INDmoney)
```

Afterwards `python scripts/kite.py` and `python scripts/dhan.py` are the daily jobs (after 16:00 IST),
and `--master` is monthly. Details: the README's "Maintenance scripts" section.

---

## 3️⃣ Run Dashboard

```bash
# Make sure venv is activated!
streamlit run apps/fno_dashboard.py               # FnO tracker
streamlit run apps/app.py                         # Portfolio / MTF Decoupler
streamlit run pulse_dashboard.py            # Sector heatmaps, F&O, Insights and MCX futures, one top navbar

# Opens browser at: http://localhost:8501
```

To run several at once, give each its own port: `streamlit run pulse_dashboard.py --server.port 8502`.

---

## 4️⃣ Verify It Works

Check dashboard shows:
- ✅ Real-time LTP values (different from Entry Price)
- ✅ Non-zero P&L % values
- ✅ Multiple tabs (Overview, Equity FnO, Commodity FnO, etc.)

---

## 🧪 Test API Connection

```bash
# Groww connectivity (groww_api/groww_client.py)
python scripts/debug/test_api.py

# Sector heatmap pipeline + live feed
python scripts/debug/check_heatmap_universe.py --provider dhan --seconds 20
# Expected: "state=LIVE  provider=Dhan  source=websocket  priced=50/50"
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `apps/fno_dashboard.py` | FnO dashboard |
| `apps/app.py` | Portfolio / MTF Decoupler |
| `pulse_dashboard.py` | Entry point: six-page navbar: sector heatmaps, F&O movers, treemaps |
| `apps/sector_heatmap_dashboard.py` | Sector heatmap page functions |
| `apps/dhan_movers_dashboard.py` | Dhan market movers: stocks, futures build-up, options OI |
| `groww_api/groww_client.py` | Groww client for `apps/app.py` and `scripts/debug/test_api.py` |
| `groww_api/` | Refactored API (new architecture) |
| `market/providers/` | Dhan / Groww market-data providers |
| `market/index_mapping.py` | Which NSE indices the index board shows |
| the `index_weights` set in `data/market.db` | Weights for market-cap sector aggregation |
| `.env` | Your credentials |

---

## 🆘 Troubleshooting

**"ModuleNotFoundError: No module named 'streamlit'"**
- Venv not activated. Run: `source .venv/Scripts/activate`

**"auth_error" in dashboard**
- Check `.env` file has correct credentials
- Try different AUTH_MODE in .env

**"LTP showing as Entry Price"**
- Market may be closed
- Run `python scripts/debug/test_api.py` to verify the API works

**Heatmap says "LIVE (Dhan REST polling)" instead of websocket**
- Usually the Dhan token was created before the Data API plan was activated
- Regenerate the token, then re-run `scripts/debug/check_heatmap_universe.py`

---

## 📚 Next Steps

- Read **docs/SECTOR_HEATMAP.md** - The live sector heatmap, brokers and fallbacks
- Read **docs/ROADMAP.md** - What is built and what is planned next
- Read **docs/PROVIDER_GUIDE.md** - Which broker API for which job
- Check **README.md** - Full project documentation

---

**Need help?** Check `docs/PROVIDER_GUIDE.md` or `docs/ROADMAP.md`
