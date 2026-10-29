# FlatSplit API contract and DynamoDB access patterns

**Issue:** [#6 — Agree API contracts and DynamoDB access patterns](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/6)
**Updated:** 20 October 2026 (status reconciliation; original PM baseline: 14 October) · **Owner:** Shyam · **Reviewer:** WK · **Status:** Implementation baseline. Incorporates the reviewed rental profile (#52), OneMap evidence (#51), and WK/Ming's contract corrections. Product defaults below are PM implementation decisions under Hikaru's request to clear blockers; they do not claim six-person approval or deployed acceptance.

**Rent evidence:** Ming approved PR #52. See the [source-backed aggregation notes](hdb-rental-data-profile.md) and [sample rows](data/hdb-rental-sample-2026-09.csv).

This is the interface the frontend (#7, #8, #13, #17, #23), data (#10, #14, #15) and API (#11, #12, #16, #18, #21, #22) tasks build against. Architecture and cost are covered in [backend-design.md](backend-design.md).

The Pydantic models and handlers in `services/api` now implement the group/search HTTP shapes and produce OpenAPI for the implemented routes. This document records the shared interface, data policy and worker handoff, including planned endpoints. Keep it aligned with runtime models through reviewed PRs. `pnpm generate:api` now exports the resolver OpenAPI to `packages/contracts/openapi.json`, then generates public Zod schemas/types in `@flatsplit/contracts/api` and the web SDK using the pinned Hey API generator. The contracts package contains schemas/types only; HTTP runtime stays in `apps/web`. `pnpm generate:api:check` detects drift in CI without editing repository artifacts. Regenerate after model/route changes instead of hand-editing the snapshot, schemas or SDK. The existing hand-authored health schema remains compatible.

**Implementation status — 25 October:** main `0446272` implements health, destination lookup, group APIs, search submission/status, filtering, ranking and raw HDB snapshot ingestion (#9). Main's destination lookup does not persist selectable places; preference-save tests seed those records. PR #65 adds persistence, immutable station pins and lookup caching but remains unmerged. Issue #10 now publishes validated trailing-12-month rent summaries into the `RENT` partitions locally; deployment and live scheduled execution remain outstanding. The actual commute worker (#15/#27), `/meta` and deployed integrated acceptance also remain outstanding. Search tests use seeded rent/place records and injected worker completions. These tests do not establish live AWS execution or deployed recommendations.

**Frontend follow-up (#7/#17):** the working implementation uses `/` for real creation, `/join/<groupId>#<inviteToken>` for join and `/groups/<groupId>` for saved membership/readiness/search progress. It polls group state every five seconds and pending search state every two seconds, passes fetch cancellation signals, refuses redirects for capability-bearing requests and keeps member tokens out of URLs/query keys. Join consumes/removes the fragment before API use, retaining it in session storage until success. A fresh fragment takes precedence over an older scratch token even if storage writes fail. Returning invite links verify saved member capabilities before redirecting; only confirmed 401/403 failures permit a replacement join, while transient errors preserve membership. A successful search POST is displayed immediately ahead of its older group snapshot until the next successful group refresh; later stale summaries still withhold results. Browser-storage failure has an explicit warning and a current-tab memory fallback. Live preference forms and editing (#8/#13) now save the current member’s inputs and refresh group state; #23 consumes the ranked response for per-member and three-town comparisons. Local browser QA uses the HTTP resolver with Moto and synthetic records/injected route completions; real producer/deployed acceptance and #24 map integration remain separate. The results UI shows rentPeriod and response-check time separately; SearchView currently provides no rent publication or per-route update timestamps.

## Conventions

- **Base path:** `/api` in the browser. CloudFront and the Vite dev proxy both route it to the API.
- **Format:** JSON with camelCase fields. Money is Singapore dollars per month as a number; commute durations are numeric minutes (fractional values retained for constraint comparisons); timestamps are ISO 8601 UTC strings.
- **IDs:** `groupId`, `memberId` and `searchId` are random 22-character URL-safe strings. They are not secrets.
- **Tokens:** random 43-character URL-safe strings (256 bits), sent as `Authorization: Bearer <token>`. The server stores only their SHA-256 hashes, so a lost token cannot be recovered.

| Token         | Holder                      | Allows                                                    |
| ------------- | --------------------------- | --------------------------------------------------------- |
| `memberToken` | One member's browser        | Read the group, edit that member, start and read searches |
| `inviteToken` | Anyone with the invite link | Join the group, and nothing else                          |

- **Invite link:** `https://<site>/join/<groupId>#<inviteToken>`. The token sits in the URL fragment, so browsers never send it to the server, CloudFront logs or `Referer` headers. The frontend reads it from the fragment and sends it as a bearer token.
- **Reload and device recovery:** the frontend keeps `{groupId, memberId, memberToken}` in `localStorage`, plus the `inviteToken` in the organiser’s browser. A member who loses it can rejoin through the invite link as a new member while there is still space (see the device-recovery policy below).
- **Organiser:** the member who created the group. Creation returns the invite token once; the organiser’s browser retains it to re-share the link. `GET /groups/{groupId}` cannot return it because the server stores only its hash. Losing that browser copy means the original invite link must be recovered from another recipient; server-side token recovery or rotation is outside this version. Any ready member may start a search (D02).

### Errors

Every error uses the same body:

```json
{
  "error": {
    "code": "GROUP_FULL",
    "message": "This group already has 3 of 3 members."
  }
}
```

| Status | `code`                 | When                                                                 |
| ------ | ---------------------- | -------------------------------------------------------------------- |
| 400    | `BAD_REQUEST`          | Malformed JSON or unknown query value                                |
| 401    | `UNAUTHORIZED`         | Missing token, or a token that does not match this group             |
| 403    | `FORBIDDEN`            | Valid token without permission (for example, editing another member) |
| 404    | `NOT_FOUND`            | Unknown or expired group, member, place or search                    |
| 409    | `GROUP_FULL`           | Joining a group that already has `size` members                      |
| 409    | `GROUP_NOT_READY`      | Starting a search before every member is ready                       |
| 409    | `CONFLICT`             | A concurrent change to the same group won; reload and retry          |
| 422    | `VALIDATION_FAILED`    | Field rules broken; `details` lists `{field, message}` pairs         |
| 429    | `RATE_LIMITED`         | API throttling                                                       |
| 503    | `UPSTREAM_UNAVAILABLE` | OneMap search failed during `/places`; the request can be retried    |
| 503    | `SERVICE_UNAVAILABLE`  | Storage is busy or not configured; the request can be retried        |

An unknown or expired group returns 404. A token that doesn't belong to an existing group returns 401.

Every group response carries `Cache-Control: no-store`, because create and join responses contain credentials.

### Validation

These rules come from `apps/web/src/features/wireframes/model.ts`. The server enforces them; the client repeats them for fast feedback.

| Field           | Rule                                                                 |
| --------------- | -------------------------------------------------------------------- |
| `groupName`     | 1–40 characters after trimming                                       |
| `size`          | Integer 2–5; fixed at creation                                       |
| `name` (member) | 1–30 characters after trimming; unique within a group, ignoring case |
| `budget`        | Number from 300 to 5,000 (S$ per person per month)                   |
| `maxCommute`    | Integer from 10 to 120 minutes                                       |
| `placeId`       | Returned by `/places` within the last 24 hours                       |

## Shared shapes

```ts
type Group = {
  groupId: string;
  groupName: string;
  size: number; // declared members, 2–5
  revision: number; // +1 on every join or preference save; stale-result guard
  members: Member[]; // in join order
  readyCount: number;
  allReady: boolean; // members.length === size && every member ready
  latestSearch: SearchSummary | null; // latest persisted search, or null before submission
  inviteToken?: string; // only in POST /groups; omitted from every later response
  createdAt: string;
  expiresAt: string; // createdAt + 30 days
};

type Member = {
  memberId: string;
  name: string;
  isOrganiser: boolean;
  ready: boolean; // true once valid preferences are saved
  destination: Destination | null;
  budget: number | null;
  maxCommute: number | null;
};

type Destination = {
  placeId: string;
  label: string; // e.g. "National University of Singapore"
  address: string;
  station: {
    stationKey: string; // application-owned canonical physical-station name
    codes: string[]; // upstream line-code aliases; never cache identities
    name: string;
    lat: number; // pinned canonical routing coordinate
    lng: number;
    snapMetres: number; // straight-line place-to-station distance, not a walking route
    snapWarning: boolean; // true above 800 m; selection requires explicit confirmation
  };
};

type SearchSummary = {
  searchId: string;
  status: 'pending' | 'complete' | 'stale';
  createdAt: string;
};
```

Every member sees the other members' names, destinations, budgets and commute limits. The preference form says so before submission (D04).

## Endpoints

### `GET /health`

Returns `200 {"status": "ok", "service": "flatsplit-api"}`. No authentication.

### `POST /groups` — create a group

No authentication. The creator becomes the organiser and saves their own preferences next, with the update call.

```http
POST /api/groups
{ "groupName": "Our next chapter", "size": 3, "name": "Alex" }
```

`201 Created`

```json
{
  "group": {
    "groupId": "V1StGXR8_Z5jdHi6B-myT2",
    "groupName": "Our next chapter",
    "size": 3,
    "revision": 1,
    "members": [
      {
        "memberId": "m_Alex000000000000000a",
        "name": "Alex",
        "isOrganiser": true,
        "ready": false,
        "destination": null,
        "budget": null,
        "maxCommute": null
      }
    ],
    "readyCount": 0,
    "allReady": false,
    "latestSearch": null,
    "inviteToken": "inv_k7G2wq9XvT1pLzR4sN8bYc3mHf6dJa0eUu5iOo2rWlQ",
    "createdAt": "2026-10-10T08:00:00Z",
    "expiresAt": "2026-11-09T08:00:00Z"
  },
  "memberId": "m_Alex000000000000000a",
  "memberToken": "mem_Q2wE4rT6yU8iO0pA1sD3fG5hJ7kL9zX2cV4bN6mQw8E"
}
```

The prefixes (`m_`, `inv_`, `mem_`) are illustrative and only make the examples easy to read.

### `GET /groups/{groupId}` — read a group (and reload)

Accepts a `memberToken` for this group. Returns `200 { "group": Group }` without `inviteToken`, including for the organiser. The frontend polls this endpoint every 5 seconds in the waiting room. A group that has expired returns 404.

### `POST /groups/{groupId}/members` — join

Accepts the `inviteToken`.

```http
POST /api/groups/V1StGXR8_Z5jdHi6B-myT2/members
Authorization: Bearer inv_k7G2wq9XvT1pLzR4sN8bYc3mHf6dJa0eUu5iOo2rWlQ
{ "name": "Jamie" }
```

`201 Created` → `{ "group": Group, "memberId": "...", "memberToken": "..." }`. `inviteToken` is omitted because Jamie is not the organiser. Returns 409 `GROUP_FULL` when all places are taken, and 422 when the name is already used.

### `PUT /groups/{groupId}/members/{memberId}` — save preferences

Accepts that member's own `memberToken`; any other member's token gets 403. The whole preference set is sent each time.

```http
PUT /api/groups/V1StGXR8_Z5jdHi6B-myT2/members/m_Alex000000000000000a
Authorization: Bearer mem_Q2wE4rT6yU8iO0pA1sD3fG5hJ7kL9zX2cV4bN6mQw8E
{ "name": "Alex", "placeId": "pl_nus_kent_ridge", "budget": 1400, "maxCommute": 45 }
```

`200` → `{ "group": Group }` with this member `ready: true` and `revision` increased. Saving after a search marks that search `stale` (D08). The group must search again before it sees results.

### `GET /places?q=<text>` — destination search

No authentication; throttled. `q` is 3–100 characters after trimming/collapsing whitespace. Reject control characters. The server calls OneMap search (#14), returns up to five distinct Singapore address/coordinate candidates, and resolves each candidate's nearest physical MRT station. It never saves the first search hit automatically: the user selects the intended label/address. The caller must disambiguate different addresses even when the query resembles a unique campus or landmark.

A selected station must be at most **1,000 m** from the place coordinates, measured as straight-line distance. A result beyond that bound is not a valid `placeId`; return it in `unsupported` with `STATION_TOO_FAR` and an instruction to choose an explicit nearby station or more precise address. Above 800 m and within the bound, require a visible distance/approximation confirmation. This conservative prototype bound is a PM default, not a measured guarantee of commute accuracy. NUS/NTU/SUSS examples in the evidence can exceed it; do not silently accept a distant station or relabel a selected station as the campus.

`places` contains only selectable candidates; `unsupported` contains `{label, address, code, message, snapMetres}` with `code` equal to `STATION_TOO_FAR` or `NO_STATION`. `ambiguous` is true when distinct selectable address candidates require user choice. No upstream result returns `{places: [], unsupported: [], ambiguous: false}`; an upstream/authentication failure is 503 rather than an empty success. Query/lookup cache entries expire after 24 hours. A valid preference save copies its destination and canonical station into the member so an already-saved preference is not lost when lookup cache TTL passes.

Canonicalise physical names using the [station normaliser](evaluation/feasibility/onemap/stations.py): strip line-code parentheses, the `MRT STATION` suffix and exit labels; uppercase and join alphanumeric words with `_`. Thus all Dhoby Ghaut line entries become `DHOBY_GHAUT`. Split `EW24 / NS1` into aliases `EW24` and `NS1`. Routes for a key use one pinned coordinate in a `STATION#<stationKey>/META` record, not whichever interchange exit happened to be nearest to a particular address. #14 obtains an exact canonical-name match, creates that station record conditionally, and reuses the winning record for every saved destination; aliases can be merged without changing its coordinate. Changing the coordinate requires an explicit cache refresh before serving results for that key.

An uncached candidate lookup uses search plus nearest-station calls; multi-candidate responses may require one nearest-station call per candidate and an exact-name search for a station record not yet pinned. Count all actual upstream calls, including retries, in E3/E4; do not assume every request costs exactly two. Debounce on the client and cache repeated queries/candidates.

```http
GET /api/places?q=kent%20ridge
```

`200`

```json
{
  "places": [
    {
      "placeId": "pl_nus_kent_ridge",
      "label": "Kent Ridge MRT Station",
      "address": "Kent Ridge MRT Station, Singapore",
      "station": {
        "stationKey": "KENT_RIDGE",
        "codes": ["CC24"],
        "name": "Kent Ridge",
        "lat": 1.29330347372,
        "lng": 103.784516185,
        "snapMetres": 0,
        "snapWarning": false
      }
    }
  ],
  "unsupported": [],
  "ambiguous": false
}
```

Return up to five selectable places. The client debounces by 300 ms, displays all returned choices and any unsupported reason, and requires selection before saving.

### `POST /groups/{groupId}/searches` — start a search

Accepts any `memberToken` for this group, with no body. Returns 409 `GROUP_NOT_READY` unless `allReady`.

The server looks up every (member station, town) commute. Pairs that are not cached are queued for the commute worker (#15). The response is `201 Created` with the same body as reading the search. When every pair was already cached, `status` is `complete` immediately.

Starting a search while an identical one (same `revision`) exists returns that search instead of creating another. An explicit repeat also retries unavailable pairs after their retry delay and reclaims expired pending leases; cached `ok` pairs are retained. The response keeps the same `searchId` and reports the refreshed progress.

### `GET /groups/{groupId}/searches/{searchId}?priority=balanced` — read status and results

Accepts any `memberToken` for this group. `priority` is `balanced` (the default), `fairness` or `budget`. Changing it re-ranks the same data without starting a new search, so the priority switch costs one cheap request.

```ts
type Search = {
  searchId: string;
  groupRevision: number; // the revision the search was started at
  status: 'pending' | 'complete' | 'stale';
  progress: { total: number; resolved: number; unavailable: number }; // commute pairs
  priority: 'balanced' | 'fairness' | 'budget';
  weights: { rent: number; averageCommute: number; commuteGap: number };
  data: {
    rentPeriod: string; // e.g. "2025-10/2026-09"
    rentSource: string;
    flatType: string; // chosen from group size (D12)
    commuteBasis: string; // e.g. "Public transport, weekday 08:30 departure"
  };
  ranked: AreaResult[]; // feasible towns, best first; empty while pending
  excluded: AreaResult[]; // infeasible towns with reasons
};

type AreaResult = {
  town: string; // HDB town name, e.g. "QUEENSTOWN"
  displayName: string; // "Queenstown"
  rank: number | null; // 1-based; null when excluded
  score: number | null; // 0–100 demonstration index (D07); null when excluded
  wholeFlatRent: number | null; // stored median; null only when no summary exists
  rentPerPerson: number | null; // wholeFlatRent / size, unrounded; display-only when low-confidence
  rentP25: number | null; // null only when no summary exists
  rentP75: number | null; // null only when no summary exists
  rentMedianCi95Low: number | null; // null only when no summary exists
  rentMedianCi95High: number | null; // null only when no summary exists
  rentSampleSize: number | null; // source-row count; null only when no summary exists
  rentQualityStatus: 'USABLE' | 'LOW_CONFIDENCE' | null; // null when no summary exists
  averageCommute: number | null;
  longestCommute: number | null;
  shortestCommute: number | null;
  commuteGap: number | null; // longest - shortest
  mostBurdenedMemberId: string | null; // longest commute; ties go to the earliest joiner
  members: MemberOutcome[];
  reasons: Reason[]; // empty when feasible
};

type MemberOutcome = {
  memberId: string;
  commuteMinutes: number | null; // null when the route is pending or unavailable
  routeStatus: 'ok' | 'pending' | 'unavailable';
  budgetHeadroom: number | null; // null without usable rent; otherwise budget - rentPerPerson
  commuteHeadroom: number | null; // maxCommute - commuteMinutes
};

type Reason = {
  code:
    | 'OVER_BUDGET'
    | 'OVER_COMMUTE'
    | 'ROUTE_UNAVAILABLE'
    | 'RENT_UNAVAILABLE'
    | 'RENT_LOW_CONFIDENCE';
  memberId: string | null;
  amount: number | null; // S$ over budget or minutes over the limit
  message: string; // ready to display, e.g. "Sam's commute exceeds their limit by 10 min"
};
```

Example: the wireframe's sample group with fictional rents and routes. Alex goes to NUS (S$1,400, 45 min), Jamie to one-north (S$1,300, 45 min) and Sam to Raffles Place (S$1,400, 45 min). With `priority=balanced`:

```json
{
  "searchId": "s_8fK2nQ0wLx4pR7tY1zVb3c",
  "groupRevision": 4,
  "status": "complete",
  "progress": { "total": 81, "resolved": 81, "unavailable": 0 },
  "priority": "balanced",
  "weights": { "rent": 0.35, "averageCommute": 0.35, "commuteGap": 0.3 },
  "data": {
    "rentPeriod": "2025-10/2026-09",
    "rentSource": "HDB Renting Out of Flats (data.gov.sg)",
    "flatType": "4-ROOM",
    "commuteBasis": "Public transport, weekday 08:30 departure"
  },
  "ranked": [
    {
      "town": "QUEENSTOWN",
      "displayName": "Queenstown",
      "rank": 1,
      "score": 67,
      "wholeFlatRent": 3600,
      "rentPerPerson": 1200,
      "rentP25": 3400,
      "rentP75": 3900,
      "rentMedianCi95Low": 3500,
      "rentMedianCi95High": 3700,
      "rentSampleSize": 412,
      "rentQualityStatus": "USABLE",
      "averageCommute": 22.33,
      "longestCommute": 27,
      "shortestCommute": 18,
      "commuteGap": 9,
      "mostBurdenedMemberId": "m_Sam0000000000000000c",
      "members": [
        {
          "memberId": "m_Alex000000000000000a",
          "commuteMinutes": 22,
          "routeStatus": "ok",
          "budgetHeadroom": 200,
          "commuteHeadroom": 23
        },
        {
          "memberId": "m_Jamie00000000000000b",
          "commuteMinutes": 18,
          "routeStatus": "ok",
          "budgetHeadroom": 100,
          "commuteHeadroom": 27
        },
        {
          "memberId": "m_Sam0000000000000000c",
          "commuteMinutes": 27,
          "routeStatus": "ok",
          "budgetHeadroom": 200,
          "commuteHeadroom": 18
        }
      ],
      "reasons": []
    }
  ],
  "excluded": [
    {
      "town": "JURONG EAST",
      "displayName": "Jurong East",
      "rank": null,
      "score": null,
      "wholeFlatRent": 3000,
      "rentPerPerson": 1000,
      "rentP25": 2800,
      "rentP75": 3300,
      "rentMedianCi95Low": 2900,
      "rentMedianCi95High": 3100,
      "rentSampleSize": 388,
      "rentQualityStatus": "USABLE",
      "averageCommute": 41,
      "longestCommute": 55,
      "shortestCommute": 30,
      "commuteGap": 25,
      "mostBurdenedMemberId": "m_Sam0000000000000000c",
      "members": [
        {
          "memberId": "m_Alex000000000000000a",
          "commuteMinutes": 30,
          "routeStatus": "ok",
          "budgetHeadroom": 400,
          "commuteHeadroom": 15
        },
        {
          "memberId": "m_Jamie00000000000000b",
          "commuteMinutes": 38,
          "routeStatus": "ok",
          "budgetHeadroom": 300,
          "commuteHeadroom": 7
        },
        {
          "memberId": "m_Sam0000000000000000c",
          "commuteMinutes": 55,
          "routeStatus": "ok",
          "budgetHeadroom": 400,
          "commuteHeadroom": -10
        }
      ],
      "reasons": [
        {
          "code": "OVER_COMMUTE",
          "memberId": "m_Sam0000000000000000c",
          "amount": 10,
          "message": "Sam's commute exceeds their limit by 10 min"
        }
      ]
    }
  ]
}
```

The example shows one entry per list. With the wireframe data, the full balanced order is Queenstown 67, Toa Payoh 63, Bukit Merah 62, Clementi 61, Bishan 58. With `priority=budget`, Clementi (53) moves ahead of Queenstown (52). Rent sample sizes are invented for the example.

**Status rules**

- `pending`: at least one needed commute pair is still queued. `ranked` and `excluded` are empty, and the frontend polls every 2 seconds using `progress`.
- `complete`: every pair is `ok` or `unavailable`. A town with an unavailable route for any member is excluded with `ROUTE_UNAVAILABLE` (D06). Unknown never counts as zero minutes.
- `stale`: the group's `revision` has moved past `groupRevision`, or the stored monthly routing profile is no longer current. Results are withheld, and the UI asks the group to search again (D08).
- A town missing rent data for the chosen flat type is excluded with `RENT_UNAVAILABLE`.
- A town whose stored rent summary has `qualityStatus = LOW_CONFIDENCE` is excluded with `RENT_LOW_CONFIDENCE`. The response still exposes its median, per-person estimate, P25, P75, 95% median interval, sample size, and quality status. Every member's `budgetHeadroom` is null, and the observed rent does not enter feasibility or ranking.

**Feasibility and ranking** (owned by #21 and #22):

- A town is feasible only when `rentQualityStatus = USABLE` and, for every member, `rentPerPerson <= budget` (unrounded) and `commuteMinutes <= maxCommute`, with both limits inclusive.
- `score = max(0, round(100 × (1 − cost)))`, where `cost = wRent × rentPerPerson/2000 + wAvg × averageCommute/90 + wGap × commuteGap/90`. The weights per priority match the wireframe.
- Implementation (`services/api/src/flatsplit_api/ranking.py`): rounding is half-up, matching JavaScript's `Math.round` in the wireframe, not Python's round-half-to-even. The arithmetic follows the wireframe's order, and parity tests pin the wireframe's scores for all three priorities.
- Weights: `balanced` 0.35 / 0.35 / 0.30, `fairness` 0.20 / 0.25 / 0.55, `budget` 0.70 / 0.20 / 0.10 (rent / average commute / commute gap).
- Display rounding: `averageCommute` to 2 decimals; `OVER_BUDGET` amounts round up to whole dollars (S$0.01 over shows as S$1); `rentPerPerson` and `budgetHeadroom` stay unrounded. `mostBurdenedMemberId` and commute statistics are null unless every member has a route.
- The engine runs only on complete searches: a pending or missing commute pair raises an error, so the search API must report `pending` instead.
- Order is score descending, then `displayName` ascending. Excluded towns with complete, usable inputs follow the same order using a hypothetical internal score; the response still exposes `score: null` for exclusions. Missing, low-confidence, or unavailable rent/route inputs give a null score; these towns follow scored exclusions in `displayName` order. A missing rent summary has null rent fields. A low-confidence summary retains its observed distribution and sample evidence, but has null budget-headroom fields and never contributes a fabricated or weak score.

### `GET /meta` — data freshness

No authentication. Returns `200 { "rentPeriod", "rentSnapshotId", "rentValidatedAt", "towns": number, "commutePairsCached": number }` for the transparency panel.

## DynamoDB design

There is one on-demand table with keys `pk` and `sk` (both strings). Items with a `ttl` attribute (epoch seconds) are deleted automatically. All group items share the group's fixed expiry of `createdAt` + 30 days.

### Items

| Item                 | pk                     | sk                              | Attributes                                                                                                                                                                                                                                                                           | Written by                                 |
| -------------------- | ---------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| Group                | `GROUP#<groupId>`      | `META`                          | groupName, size, revision, memberCount, organiserMemberId, inviteTokenHash, createdAt, ttl                                                                                                                                                                                           | groups API                                 |
| Member               | `GROUP#<groupId>`      | `MEMBER#<joinedAt>#<memberId>`  | memberId, name, nameKey (lower case), tokenHash, ready, placeId, destination, budget, maxCommute, ttl                                                                                                                                                                                | groups API                                 |
| Search               | `GROUP#<groupId>`      | `SEARCH#<createdAt>#<searchId>` | searchId, groupRevision, pairs (distinct stationKey × town), pinned stations, rentSnapshotId, rentPeriod, flatType, routingProfileVersion, createdAt, ttl                                                                                                                            | search API                                 |
| Revision reservation | `GROUP#<groupId>`      | `SEARCH_REV#<revision>`         | searchId, searchKey, ttl; conditional creation converges simultaneous starts for one revision                                                                                                                                                                                        | search API                                 |
| Search ID lookup     | `GROUP#<groupId>`      | `SEARCH_ID#<searchId>`          | searchKey, ttl; resolves a public ID without scanning history                                                                                                                                                                                                                        | search API                                 |
| Place                | `PLACE#<placeId>`      | `META`                          | label, address, lat, lng, station, ttl (24 hours)                                                                                                                                                                                                                                    | places API                                 |
| Station              | `STATION#<stationKey>` | `META`                          | stationKey, name, codes (upstream line-code aliases), codesRevision (optimistic lock for the alias list only), lat, lng, pinnedAt; **no ttl** — the pinned routing coordinate outlives the lookup cache that created it                                                              | places API                                 |
| Query cache          | `PLACELOOKUP#<query>`  | `META`                          | query, placeIds, unsupported, refreshedAt, ttl (24 hours); the key is the trimmed, whitespace-collapsed, case-folded query, since the upstream search ignores case                                                                                                                   | places API                                 |
| Rent pointer         | `RENT`                 | `CURRENT`                       | schemaVersion, snapshotId, period, sourceMonthTo, rawRetrievedAt, validatedAt                                                                                                                                                                                                        | rent ingestion (#10)                       |
| Rent summary         | `RENT#<snapshotId>`    | `TOWN#<town>#<flatType>`        | schemaVersion, sourceDatasetId, sourceUpdatedAt, sourceMonthFrom, sourceMonthTo, period, town, flatType, currency, unit, statistic, median, p25, p75, count, blockCount, bootstrapMethod, bootstrapReplicates, medianCi95Low, medianCi95High, medianCi95RelativeWidth, qualityStatus | rent ingestion (#10)                       |
| Commute              | `COMMUTE#<stationKey>` | `TOWN#<town>`                   | status (`pending`/`ok`/`unavailable`), minutes, transfers, walkMinutes, attempts, computedAt, error                                                                                                                                                                                  | search API (pending), commute worker (#15) |

The place record is a 24-hour cache of one resolved place; the query cache maps a query to the response it produced, so a repeated query needs no upstream call, and a hit is only served while every place record it names is still present and unexpired. Neither cache slides its expiry. The station record is the pinned physical-station identity: it is created conditionally, is never rewritten by a lookup, and carries no ttl, so a saved destination keeps one routing coordinate after both caches expire.

Sort keys start with timestamps so members come back in join order and the latest search is last. Group reads and writes check `META.ttl` against the current time; DynamoDB TTL deletion is asynchronous and must not be relied on for access expiry. Name uniqueness uses a `NAME#<nameKey>` reservation item in the group partition (memberId and ttl), created in the same transaction as a join and replaced transactionally on a rename.

### Access patterns

| #   | Pattern                                | Operation                                                                                                                                                                                                                                                                                                                                                                                              |
| --- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A1  | Read a group with members and searches | `Query pk = GROUP#<id>`; paginate if `LastEvaluatedKey` is present. Token checks use the hashes in this result                                                                                                                                                                                                                                                                                         |
| A2  | Create a group                         | `TransactWriteItems`: put `META`, the organiser `MEMBER` and its `NAME#<nameKey>` reservation, all `attribute_not_exists(pk)`                                                                                                                                                                                                                                                                          |
| A3  | Join                                   | `TransactWriteItems`: update `META` with condition `memberCount < size AND ttl > now AND inviteTokenHash = :hash`, then `memberCount += 1, revision += 1`; put the new `MEMBER` and its `NAME#<nameKey>` reservation with `attribute_not_exists(pk)`. A capacity condition failure becomes `GROUP_FULL`; a name reservation conflict becomes 422. Two people taking the last place cannot both succeed |
| A4  | Save preferences                       | `TransactWriteItems`: update `MEMBER` with condition `tokenHash = :hash`; update `META` with `revision += 1` and condition `ttl > now`; a rename also conditions on the previous `nameKey`, reserves the new name and releases the old reservation in this transaction                                                                                                                                 |
| A5  | Resolve a place for a preference save  | `GetItem PLACE#<placeId> / META`                                                                                                                                                                                                                                                                                                                                                                       |
| A6  | Rent for a search                      | `GetItem RENT / CURRENT`, then `Query pk = RENT#<snapshotId>, begins_with(sk, "TOWN#")` and filter to the chosen flat type in code (up to 27 towns × 6 flat types = 162 small items; the profiled trailing window produces 129 non-empty items)                                                                                                                                                        |
| A7  | Commutes for a search                  | One `Query pk = COMMUTE#<stationKey>` per distinct member station: at most 5 queries of about 27 items; the source-controlled town set may change                                                                                                                                                                                                                                                      |
| A8  | Queue a missing pair once              | `PutItem COMMUTE#…/TOWN#…` with `status = pending`, a new `jobId` and bounded `leaseExpiresAt`; claim only an absent item, expired pending lease or retry-eligible unavailable item. The claimant sends SQS; other requests leave an active lease alone                                                                                                                                                |
| A9  | Store a commute result                 | Worker `UpdateItem` to `ok` with minutes, or to `unavailable` with `retryAfter` after the final attempt/DLQ; condition on matching `jobId` and `status = pending`; an old attempt cannot overwrite a newer claim or completed result                                                                                                                                                                   |
| A10 | Data freshness                         | `GetItem RENT / CURRENT`                                                                                                                                                                                                                                                                                                                                                                               |

There are no scans and no secondary indexes. The #16 implementation adds point reads for search-ID/revision reservations and consistent group-metadata checks before and after result construction; the original 7/8-request sketch is **not** its implemented request count. A complete status read with five distinct stations and single-page partitions uses 11 DynamoDB requests: one group query, two search lookups, two metadata checks, five commute queries and one pinned rent query. Pending reads omit the rent query. Cold submissions additionally read the rent pointer, transact the search plus two reservations, claim up to 135 pairs and send up to 130 jobs (five TENGAH pairs resolve locally); do not confuse those writes/sends with the read budget. Long group histories, rent/cache pagination, retries and lease recovery add requests. #30 must measure actual cold/warm latency and cost; the 500 ms target is not verified locally. Commute and rent items carry no TTL. Commutes are refreshed by profile-aware claims; monthly batch refresh remains external work. Place/station lookups are separate from this budget; search uses station coordinates copied into the member/search snapshot.

### Routing baseline

Use the [27-town principal-station reference table](evaluation/feasibility/data/towns.json) with HDB spelling. `CENTRAL` is the rental key; archived `CENTRAL AREA` observations map to it for interpretation. `TENGAH` is retained with its documented non-routable reference; unavailable routes and weak/missing rents exclude it honestly, rather than removing it from the source inventory.

Route from the pinned town point to the pinned destination station at weekday 08:30 Singapore time. Choose the next weekday in Singapore at refresh and record `routingDate`, `routingTime`, `routingProfileVersion` and source timestamp with the cached result. Request `numItineraries=3` and take the minimum returned duration (one upstream request, not three). A monthly refresh or changed routing profile invalidates prior results before reuse; an older `jobId`/profile must not overwrite a newer refresh. Do not mix routing profiles in one search.

Commute is **station-to-station**, not door-to-door; display that label and the snap distance alongside the original selected address. No invented walking time is added. #19/#20 quantify the approximation. A 404/no-itinerary result is `unavailable`, never zero, including TENGAH or a same-point upstream failure.

Start with at most three in-flight worker routing requests, shared-budget headroom for user lookups and a conservative 250-call/min client guard below the published 300/min quota. This guard is a configured budget, not an experimentally established safe throughput. Short-window measurements indicate concurrency sensitivity and do not prove sustained/hourly/daily capacity. On 429/5xx/transport failures, bounded backoff and at most three attempts precede DLQ handling. Parse HTML as well as JSON and define backoff when `Retry-After` is absent. 400/403/404 are not retried; 401/expired-token signals invoke the credential-refresh path and operational alert rather than repeating the same credential. Check the three-day token's remaining validity before a fill. A 200 search response with a token warning still requires that alert.

## Evidence and implementation decisions

| ID  | Baseline                                                                                                                  | Evidence or decision                                                                                           |
| --- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| C1  | Trailing-12-month R-7 quantiles and block-bootstrap quality gate; weak summaries remain visible but cannot affect ranking | Mani's profile and Ming's approved #52 review                                                                  |
| C2  | Equal whole-flat benchmark split; 2 members → 3-ROOM, 3 → 4-ROOM, 4–5 → 5-ROOM                                            | PM prototype default adopted 14 October; this is not a legal occupancy rule or a source-proven unit definition |
| C3  | Exact HDB town spelling, including `CENTRAL` and `TENGAH`; 27-town source inventory                                       | #52; station table reconciled to those keys                                                                    |
| C4  | User-selected Singapore place candidates can be geocoded and station-snapped subject to the bound above                   | #3/#51; results do not establish the user's intended address                                                   |
| C5  | Pinned principal-station town point → pinned destination station; weekday 08:30; minimum of three returned itineraries    | #51 and WK's 14 October review; station approximation declared                                                 |
| C6  | Physical-station `stationKey` is the cache identity; line codes are aliases                                               | #3 refutes the old code-based identity; WK and Ming requested this correction                                  |
| C7  | Published quota 300/min; configured client guard 250/min and initial worker concurrency three, all actual calls counted   | #51 documents short-window/concurrency findings and limitations; throughput still requires E4                  |

### Group defaults that unblock #11/#12

- Group size is fixed at creation, 2–5; names are unique after trimmed Unicode-normalised case folding. Conditional transactions enforce capacity, name reservation, token permission and logical expiry. API/tests must include the race for the last place and stale revision behavior.
- Expiry is 30 days from creation. Check it on every request and in mutations; DynamoDB TTL deletion is asynchronous. No sliding expiry.
- Any ready member can start a search once the whole group is ready. Members see the declared shared fields after the privacy notice.
- No member removal, token recovery/reissue, group resizing or accounts in this prototype. Lost-device recovery requires the original invite and a free slot; a full group needs a new group. Explain this limitation instead of adding permissions silently.
- The equal rent split and flat-type mapping above are implementation defaults. The source metadata's blank rent unit and approximation limitations remain visible in the profile/report. Ranking retains the wireframe weights and scales. Merged #22 implementation includes parity tests for all three priorities; this establishes fixture parity, while integrated/deployed acceptance and empirical fairness/usability validation remain outstanding.

These decisions close the document/design handoff only. Runtime endpoints, deployment, recovery and user evaluation must satisfy their own issues. Human pair feedback can revise the baseline through a reviewed PR; no missing approval is fabricated.

### Commute enqueue recovery

DynamoDB and SQS do not share a transaction. If sending fails, release the pending claim only when its `jobId` still matches. A crash between claim and send is recovered when a subsequent search/status request reclaims the expired lease and resends the job. Choose the lease duration to cover the expected queue/worker time in #15, and record `jobId`, `leaseExpiresAt` and `retryAfter` on commute items. Queue delivery and worker retries are idempotent: duplicate jobs for the same claim may be acknowledged, but an older claim cannot publish over a newer one. No pair may remain pending indefinitely solely because its enqueue failed.

#### #16 producer and #15 worker handoff

- `SearchStore` implements submission/status; `SearchDataReader` pins `RENT/CURRENT` at creation and queries that snapshot thereafter. `CommuteJobs` claims each distinct destination-station × packaged town pair. Members sharing a station share its commute jobs, while ranking still evaluates every member's own limits.
- SQS payload version 1 contains `schemaVersion`, `jobId`, `stationKey`, `town`, `origin: {lat, lng}`, `destination: {lat, lng}`, `routingProfileVersion`, `routingDate`, `routingTime` and `leaseExpiresAt`. It contains no group/member IDs, bearer tokens, names, budgets, addresses or raw place queries. `origin` comes from the reviewed town-point projection packaged with the API; `destination` is the saved pinned station.
- Default pending lease: **900 seconds**. Profiles are `pt-v1:YYYY-MM` in Singapore time; routing is the next weekday at `08:30:00`. Cache items record the profile/date/time, job identity and attempts. A newer profile cannot be replaced by an older claimant. TENGAH's non-routable reference resolves directly to `unavailable`, with `NON_ROUTABLE_TOWN`, not a queue job or zero-minute route.
- The #15 worker must update only an item whose `jobId` matches **and** whose status is still `pending`; retain its routing metadata. Write `ok` with fractional `minutes`, or `unavailable` with an epoch-second `retryAfter` after terminal failure. Duplicate/late deliveries must not overwrite a newer claim or completed result. DLQ consumption/final-failure recording and routing/provider policy remain #15/#27 work.
- `GET` may reclaim an absent/expired pending lease, but does not retry resolved `unavailable` pairs. Explicit repeat `POST` retries only those whose delay has elapsed; it retains the same search ID and rent snapshot. A profile from an earlier month is stale on read; repeating the search advances its profile, retains the ID/rent pin and refreshes older cache entries. Stale responses withhold results and report zero resolved/unavailable progress because prior-profile routes are not reused.
- CDK exposes `Api.commuteJobsQueue` and `CommuteQueueUrl`. The encrypted/TLS-only source queue has 180-second visibility, four-day retention and a three-receive redrive policy to a 14-day DLQ. #15 must attach its consumer to this queue, choose a worker timeout compatible with that visibility, and validate/tune the 900-second claim lease under the actual backlog. No consumer or deployed queue is claimed by local synthesis.
- Runtime configuration is `TABLE_NAME` and `COMMUTE_QUEUE_URL`; `DYNAMODB_ENDPOINT_URL` and `SQS_ENDPOINT_URL` support local compatible services. Missing queue configuration returns 503 when enqueue is needed; a complete warm cache does not require an SQS call. No default worker output or fabricated rent/commute fallback exists.
