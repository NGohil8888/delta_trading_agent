# Delta Exchange API Knowledge Base

Operational reference distilled from https://docs.delta.exchange/. This is
reference material the agent reads every turn (via the system prompt) but
never edits -- same tier as `AGENTS.md`. Update this file by hand when
Delta's API changes; the agent's file tools are scoped to `workspace/` and
cannot touch it.

## Base URLs
- Production: `https://api.india.delta.exchange`
- Testnet: `https://cdn-ind.testnet.deltaex.org`
- Same documentation covers both -- only the base URL differs. This is
  exactly why `place_order()` refuses to run unless `DELTA_BASE_URL`
  contains "testnet": a correct API call against the wrong base URL is
  still a live trade.

## Authentication
Every private-endpoint request needs three headers: `api-key`, `timestamp`,
and `signature`. The signature is an HMAC-SHA256 hash (hex-encoded) of the
API secret over the concatenation of: HTTP method + timestamp + request
path (including query string) + request body. The timestamp must be
within a small window of Delta's server clock (a few seconds) or the
request is rejected as expired -- if your system clock drifts, auth will
fail even with correct keys.

**A `User-Agent` header is required.** Requests without one can be
rejected at the CDN layer with a generic 4xx before ever reaching
signature or schema validation -- this is easy to misdiagnose as a bad key
or bad payload when it's actually just a missing header. (Fixed in
`agent/delta_client.py`.)

**API keys with Trading permission require IP whitelisting.** If orders
fail with an auth-flavored error even though the key/secret are correct,
check whether the key's allowed-IP list includes the machine actually
making the request.

## Products & Contract Types
`/v2/products` returns every tradeable instrument, with fields including
`symbol`, `id` (the integer `product_id` orders reference), `contract_type`
(`perpetual_futures`, `call_options`, `put_options`, `move_options`,
`spot`, etc.), and `contract_value` (the size of one contract in
underlying-asset units).

**`contract_value` is what makes order sizing work.** Delta's order `size`
field is an INTEGER number of contracts, not a fractional coin quantity --
sending `0.003` directly for a BTC order fails schema validation
("Expected a integer value"). The correct conversion is:

```
contracts = round(desired_underlying_quantity / contract_value)
```

e.g. if `contract_value` for BTCUSD is `0.001`, wanting 0.003 BTC of
exposure means `size=3`. (`agent/delta_client.py:_resolve_contract_size`
implements this, falling back to treating the desired quantity as already
being a contract count if `contract_value` isn't present on the product.)

The raw `/v2/products` list is dominated by dated options contracts
(`C-BTC-77000-310726`, `P-ETH-2300-310726`, etc.) -- scanning it unfiltered
surfaces options noise instead of tradeable perpetuals. Filter to
`contract_types=perpetual_futures` (available on `/v2/tickers` too) before
ranking candidates.

## Orders
`POST /v2/orders` with at minimum: `product_id` (int), `size` (int,
contracts -- see above), `side` (`buy`/`sell`), `order_type`
(`market_order` or `limit_order`; `limit_order` also needs `limit_price`).

## Errors
Delta's error responses follow `{"success": false, "error": {"code": ...,
"context": {...}}}`. Common codes worth recognizing on sight:
- `invalid_api_key` / `ip_not_whitelisted_for_api_key` -- auth/config issue, not a trading-logic issue.
- `insufficient_margin` -- position sizing exceeds available balance/leverage.
- `bad_schema` with a `param` naming a field -- a payload shape issue (this is what the integer-size bug surfaced as).

## Rate Limits
Requests are weighted per endpoint against a rolling quota (order of
10,000 request-weight per 5-minute window per API key). Scanning many
symbols or polling aggressively can burn this faster than the request
count alone suggests -- prefer the ticker/products bulk endpoints over
per-symbol loops where possible (which is what `agent/market.py` already
does).