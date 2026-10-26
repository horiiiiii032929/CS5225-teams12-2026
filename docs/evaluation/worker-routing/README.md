# Commute worker routing, verified live (#15)

Evidence that the worker's own routing client — `services/api/src/flatsplit_api/routing.py`, the code that is deployed, not a separate probe — reaches OneMap, returns the minutes the design assumes, and classifies failures the way the handler relies on. The feasibility question ("can OneMap do this at all") was answered in [feasibility/](../feasibility/) by #3; this answers "does our module do it".

**Run date:** 20 October 2026 (UTC). **Operator:** @lukerspace. **Script:** `scripts/verify_live_routing.py` v1.0.0. **Token:** user 26849, fingerprint `829a3c999601`, 70.6 h left. No token value is recorded anywhere in this tree.

> Script docstrings and the generated `note` fields are in the operator's working language (Chinese), per the feasibility archive's convention.

## Layout

| Path                                         | What it is                                                                            |
| -------------------------------------------- | ------------------------------------------------------------------------------------- |
| `scripts/verify_live_routing.py`             | Routes eight real pairs through `flatsplit_api.routing` and probes five failures      |
| `raw/2026-10-20/live_routing_*T085658Z.json` | First run — **uncached** latency, and the superseded 03:00 expectation (verdict FAIL) |
| `raw/2026-10-20/live_routing_*T085800Z.json` | Second run — the same eight pairs **cached** upstream, verdict PASS                   |

Both runs are kept. The first one is not a failure of the module: it failed its own verdict because one probe no longer reproduces #3's result (below), and it is the only uncached latency sample of the two.

## Claim → evidence

| Claim                                                                                                      | Where                                                |
| ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| The worker's module routes 8/8 of #3's sampled town → Kent Ridge pairs on a weekday 08:30 departure        | `pairs.coverage`, `pairs.rows` in either run         |
| Minutes reproduce #3's 11 October figures to within 0.3 min (table below)                                  | `pairs.rows[].minutes`                               |
| Uncached routing latency p50 **992 ms** (n=8, min 496, p95 1174, max 1454)                                 | `pairs.latencyMs` in the 085658Z run                 |
| A repeat of the same pairs is served in p50 **154 ms** (n=8, min 107, max 201) — OneMap caches it          | `pairs.latencyMs` in the 085800Z run                 |
| A routing 404 arrives as `RoutingUnroutable` / `NO_ROUTE`, never as zero minutes (D06)                     | `failureProbes.rows[0]`                              |
| A request we built wrongly arrives as `RoutingRejected` / `INVALID_ROUTE_REQUEST`, and stays terminal      | `failureProbes.rows[2..3]`                           |
| A token OneMap refuses arrives as `RoutingCredential` / `CREDENTIAL_UNAVAILABLE`, not as the pair's answer | `failureProbes.rows[4]`                              |
| OneMap's first itinerary was the shortest in 8/8 pairs, with 1–3 itineraries returned                      | `pairs.shortestWasFirst`, `pairs.rows[].itineraries` |

### Minutes against #3's baseline

Both columns request three itineraries and take the minimum, so they are the same measurement nine days apart.

| Town        | #3, 11 Oct | This run, 20 Oct | Itineraries returned |
| ----------- | ---------: | ---------------: | -------------------: |
| ANG MO KIO  |       45.1 |             45.3 |                    1 |
| TAMPINES    |       56.5 |             56.7 |                    2 |
| WOODLANDS   |       45.3 |             45.4 |                    3 |
| JURONG WEST |       26.0 |             26.2 |                    1 |
| CLEMENTI    |       14.5 |             14.6 |                    2 |
| PUNGGOL     |       47.5 |             47.7 |                    1 |
| BEDOK       |       42.8 |             42.9 |                    1 |
| YISHUN      |       57.0 |             57.1 |                    1 |

TAMPINES is the pair that made `numItineraries=3` a requirement: #3 measured 58.3 min with one itinerary and 56.5 with three. It still returns two itineraries, so one of them is still the wrong answer to cache.

## What changed upstream since #3

**#3's "03:00 has no service → HTTP 404" no longer reproduces.** On 20 October the same call returned a valid 182.6-minute overnight itinerary. The probe is therefore recorded but no longer asserted (`asExpected: null`), and "same start and end" is the only 404 source we can rely on. Consequences:

- The worker is unaffected: it always routes at the producer's 08:30 departure.
- A night-time departure can return a route three hours long. Nothing in the design treats a long route as an error, so this is a data-quality note for #19, not a failure path.

## Limitations

- Measured from outside Singapore, like #3. Latency includes that distance.
- Two runs an hour apart on one day: enough to show the module works and that upstream caches repeats, not enough for a latency distribution. E4's drain measurement (#27) is where the rate and queue behaviour get measured.
- The 429 path is not probed here. Provoking it means deliberately exceeding OneMap's published limit, which #3 already measured once (concurrency-driven, 2/30 rejections at concurrency 30) and which the worker bounds by holding concurrency at three.
