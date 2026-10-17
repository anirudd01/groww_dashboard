here are the api and key level glossary , what those keys mean and what should be they used for
hint : ignoring FnO altogether for now as its out of the scope

get_available_margin_details() -

- collateral_available - available margin balance that can be still used for buying intraday or MTF stocks
- clear_cash - available cash in wallat for buying (anything and everything)
- equity_margin_details.mis_balance_available - total balance cash from wallat + margin given by groww , which can be used for MTF or intraday, but not delivery/CNC

get_holdings_for_user() - returns all stocks meaning holdings + positions in list -

- if "pledge_quantity":0 , its safe to assume the stock is not pledged, as may be its not a delivery or cnc holdings, it is a MTF or intraday position,
- for "trading_symbol":"EICHERMOT" , the quantity and "pledge_quantity":108 is same, so it is fully bought via cash and not margin, so its safe to say the total amount invested for this stock is user's own money.
- T1 quantity represents the number of shares you recently bought that have not yet settled and fully credited to your Demat account
- for "trading_symbol":"ATHERENERG" , the "t1_quantity":3000 and "quantity":3000 , so this basically means all stocks belong to same category either MTF, or intraday or delivery holdings
- in such case pledge quantity usually will be 0 which means we cant figure out if its delivery holdings or not

- get_positions_for_user() - always use this api for MTF or intraday , it returns a list with all the positions,
- "segment":"CASH" does not mean it was bought with own money, it just means equity and not commodity
- "product":"MTF" - this is what matters, this basically says this position is a MTF purchase with margin money
