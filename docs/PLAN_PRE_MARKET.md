# Plan: show the pre-open price from 09:08, never yesterday's prices as if they were today's

Status: planned 2026-11-10, not built. Build only after the 09:00-09:15 capture (step 1) has shown
what the brokers actually send.

## The goal

On a trading day, someone opening the heatmap at 09:08 should see the pre-open price (NSE's
call auction, 09:00-09:08) against yesterday's close. They should not see yesterday's last price
dressed up as today's. From 09:15 the board works as it does now.

MCX is separate: it opens at 09:00 with no auction, and the MCX page is not part of this plan.

## What the code does today (read 2026-11-10, not tested live before 09:15)

- `market/market_hours.py`: 09:00-09:15 is `PRE-MARKET`. The board shows `CLOSED` for that window,
  because `is_market_open()` is false then.
- Previous close (`LiveMarketDataService._previous_close_source`): in pre-market and in session it
  is the broker's OHLC `close`; outside those hours it comes from daily candles. It is refreshed
  at most every 15 minutes (`previous_close_refresh_seconds`), so a feed that started the evening
  before may keep its old previous close until about 09:15.
- Prices are not dated. `_apply_prices` stamps each one with the time *we received* it, not the
  time it traded. Before the auction prints, the websocket and REST simply return yesterday's
  last price, and nothing on the board can tell the two apart.
- REST polling stays every 3 s through pre-market (kept that way on 2026-11-10 on purpose).
- The market-status check (`market/exchange_status.py`) does not ask about NSE before 09:16, so it
  plays no part here.

## Open questions only a live morning can answer

1. Between 09:00 and 09:08, what do Dhan and Groww return for LTP: yesterday's last price, or
   nothing?
2. At 09:08, does the pre-open equilibrium price show up as the LTP, over REST and over the
   websocket, for both brokers? With what `last_trade_time`?
3. Between 09:00 and 09:15, is the OHLC `close` still yesterday's close, or has it been repointed?
4. Does the Nifty index get a pre-open value, or only the stocks?

## Steps

1. **Capture (read-only, one trading morning).** A script in `scripts/debug/` polls every 30 s
   from 08:58 to 09:17, for about 10 liquid stocks and the Nifty index. Each pass records Dhan's
   REST quote (`last_price`, `ohlc.close`, `last_trade_time`), Groww's quote (`last_price`,
   `ohlc.close`, `last_trade_time`) and the websocket ticks. The results go into the
   `provider_compare.db` the comparison scripts already use. Run it on the laptop; the morning
   cron does not need it.
2. **Decide from the data**, and write the findings into `docs/PROVIDER_COMPARISON_LOG.md`.
3. **Date every price.** Carry the broker's trade time with each price: Dhan's ticker packet and
   quote both have it, and Groww's quote has it as epoch seconds. Before 09:15, show a price only
   if it traded today; otherwise the tile reads "no pre-open price yet".
4. **Refresh the previous close at 09:00 sharp**, not "within 15 minutes": a new day's first
   pre-market pass refetches it once.
5. **A `PRE-OPEN` board state** in the status banner, so 09:00-09:15 reads neither `CLOSED` nor
   `LIVE`.
6. **Tests** for each rule, then a second live morning to check it end to end.

## Out of scope

- The MCX page.
- Kite.
- Changing the 09:16 NSE market-status rule.
