# FlatSplit API contract and DynamoDB access patterns

**Issue:** [#6 — Agree API contracts and DynamoDB access patterns](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/6)
**Draft:** 10 October 2026 · **Owner:** Shyam · **Reviewer:** WK · **Status:** Provisional. The rent and commute fields wait on #2 and #3 (see [Assumptions to confirm](#assumptions-to-confirm)).

This is the interface the frontend (#7, #8, #13, #17, #23), data (#10, #14, #15) and API (#11, #12, #16, #18, #21, #22) tasks build against. Architecture and cost are covered in [backend-design.md](backend-design.md).

Once #12 starts, the Pydantic models in `services/api` become the source of truth. Their generated OpenAPI produces the zod schemas in `@flatsplit/contracts`. Until then, this document is the contract. Change it by pull request so every pair sees the change.

## Conventions

- **Base path:** `/api` in the browser. CloudFront and the Vite dev proxy both route it to the API.
- **Format:** JSON with camelCase fields. Money is Singapore dollars per month as a number; durations are whole minutes; timestamps are ISO 8601 UTC strings.
- **IDs:** `groupId`, `memberId` and `searchId` are random 22-character URL-safe strings. They are not secrets.
- **Tokens:** random 43-character URL-safe strings (256 bits), sent as `Authorization: Bearer <token>`. The server stores only their SHA-256 hashes, so a lost token cannot be recovered.

| Token         | Holder                      | Allows                                                    |
| ------------- | --------------------------- | --------------------------------------------------------- |
| `memberToken` | One member's browser        | Read the group, edit that member, start and read searches |
| `inviteToken` | Anyone with the invite link | Join the group, and nothing else                          |

- **Invite link:** `https://<site>/join/<groupId>#<inviteToken>`. The token sits in the URL fragment, so browsers never send it to the server, CloudFront logs or `Referer` headers. The frontend reads it from the fragment and sends it as a bearer token.
- **Reload and device recovery:** the frontend keeps `{groupId, memberId, memberToken}` in `localStorage`. A member who loses it can rejoin through the invite link as a new member while there is still space (see open question Q3).
- **Organiser:** the member who created the group. The only extra power is reading `inviteToken` again through `GET /groups/{groupId}` to re-share it. Any ready member may start a search (D02).

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
| 422    | `VALIDATION_FAILED`    | Field rules broken; `details` lists `{field, message}` pairs         |
| 429    | `RATE_LIMITED`         | API throttling                                                       |
| 503    | `UPSTREAM_UNAVAILABLE` | OneMap search failed during `/places`; the request can be retried    |

An unknown or expired group returns 404. A token that doesn't belong to an existing group returns 401.

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
  latestSearch: SearchSummary | null;
  inviteToken?: string; // only when the caller is the organiser
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
  station: { stationId: string; name: string; walkMetres: number }; // nearest MRT, used for commutes
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

Accepts a `memberToken` for this group. Returns `200 { "group": Group }`. The frontend polls this endpoint every 5 seconds in the waiting room. A group that has expired returns 404.

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

No authentication; throttled. `q` is 3–100 characters. The server calls OneMap search (#14) and snaps each result to its nearest MRT station.

```http
GET /api/places?q=kent%20ridge
```

`200`

```json
{
  "places": [
    {
      "placeId": "pl_nus_kent_ridge",
      "label": "National University of Singapore",
      "address": "21 Lower Kent Ridge Road, Singapore 119077",
      "station": {
        "stationId": "CC24",
        "name": "Kent Ridge",
        "walkMetres": 650
      }
    }
  ]
}
```

Returns up to 5 places; an empty list means no match. The client should debounce input by 300 ms.

### `POST /groups/{groupId}/searches` — start a search

Accepts any `memberToken` for this group, with no body. Returns 409 `GROUP_NOT_READY` unless `allReady`.

The server looks up every (member station, town) commute. Pairs that are not cached are queued for the commute worker (#15). The response is `201 Created` with the same body as reading the search. When every pair was already cached, `status` is `complete` immediately.

Starting a search while an identical one (same `revision`) exists returns that search instead of creating another.

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
  wholeFlatRent: number; // median monthly rent
  rentPerPerson: number; // wholeFlatRent / size, unrounded
  rentSampleSize: number; // approvals behind the median
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
  budgetHeadroom: number; // budget - rentPerPerson; negative means over budget
  commuteHeadroom: number | null; // maxCommute - commuteMinutes
};

type Reason = {
  code:
    'OVER_BUDGET' | 'OVER_COMMUTE' | 'ROUTE_UNAVAILABLE' | 'RENT_UNAVAILABLE';
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
  "progress": { "total": 78, "resolved": 78, "unavailable": 0 },
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
      "rentSampleSize": 412,
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
      "rentSampleSize": 388,
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
- `stale`: the group's `revision` has moved past `groupRevision`. Results are withheld, and the UI asks the group to search again (D08).
- A town missing rent data for the chosen flat type is excluded with `RENT_UNAVAILABLE`.

**Feasibility and ranking** (owned by #21 and #22):

- A town is feasible when, for every member, `rentPerPerson <= budget` (unrounded) and `commuteMinutes <= maxCommute`, with both limits inclusive.
- `score = max(0, round(100 × (1 − cost)))`, where `cost = wRent × rentPerPerson/2000 + wAvg × averageCommute/90 + wGap × commuteGap/90`. The weights per priority match the wireframe.
- Order is score descending, then `displayName` ascending. Excluded towns follow the same order using the score they would have had.

### `GET /meta` — data freshness

No authentication. Returns `200 { "rentPeriod", "rentSnapshotId", "rentValidatedAt", "towns": number, "commutePairsCached": number }` for the transparency panel.

## DynamoDB design

There is one on-demand table with keys `pk` and `sk` (both strings). Items with a `ttl` attribute (epoch seconds) are deleted automatically. All group items share the group's fixed expiry of `createdAt` + 30 days.

### Items

| Item         | pk                    | sk                              | Attributes                                                                                            | Written by                                 |
| ------------ | --------------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Group        | `GROUP#<groupId>`     | `META`                          | groupName, size, revision, memberCount, organiserMemberId, inviteTokenHash, createdAt, ttl            | groups API                                 |
| Member       | `GROUP#<groupId>`     | `MEMBER#<joinedAt>#<memberId>`  | memberId, name, nameKey (lower case), tokenHash, ready, placeId, destination, budget, maxCommute, ttl | groups API                                 |
| Search       | `GROUP#<groupId>`     | `SEARCH#<createdAt>#<searchId>` | searchId, groupRevision, pairs (list of stationId × town), rentSnapshotId, ttl                        | search API                                 |
| Place        | `PLACE#<placeId>`     | `META`                          | label, address, lat, lng, station, ttl (24 hours)                                                     | places API                                 |
| Rent pointer | `RENT`                | `CURRENT`                       | snapshotId, period, validatedAt                                                                       | rent ingestion (#10)                       |
| Rent summary | `RENT#<snapshotId>`   | `TOWN#<town>#<flatType>`        | median, p25, p75, count, period, sourceMonthFrom, sourceMonthTo                                       | rent ingestion (#10)                       |
| Commute      | `COMMUTE#<stationId>` | `TOWN#<town>`                   | status (`pending`/`ok`/`unavailable`), minutes, transfers, walkMinutes, attempts, computedAt, error   | search API (pending), commute worker (#15) |

Sort keys start with timestamps so members come back in join order and the latest search is last.

### Access patterns

| #   | Pattern                                | Operation                                                                                                                                                                                                                               |
| --- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A1  | Read a group with members and searches | `Query pk = GROUP#<id>` (one request, a few KB). Token checks use the hashes in this result                                                                                                                                             |
| A2  | Create a group                         | `TransactWriteItems`: put `META` and the organiser `MEMBER`, both `attribute_not_exists(pk)`                                                                                                                                            |
| A3  | Join                                   | `TransactWriteItems`: update `META` with condition `memberCount < size`, then `memberCount += 1, revision += 1`; put the new `MEMBER`. A failed condition becomes `GROUP_FULL`, so two people taking the last place cannot both succeed |
| A4  | Save preferences                       | `TransactWriteItems`: update `MEMBER` with condition `tokenHash = :hash`; update `META` with `revision += 1`                                                                                                                            |
| A5  | Resolve a place for a preference save  | `GetItem PLACE#<placeId> / META`                                                                                                                                                                                                        |
| A6  | Rent for a search                      | `GetItem RENT / CURRENT`, then `Query pk = RENT#<snapshotId>, begins_with(sk, "TOWN#")` and filter to the chosen flat type in code (about 26 × 5 small items)                                                                           |
| A7  | Commutes for a search                  | One `Query pk = COMMUTE#<stationId>` per distinct member station: at most 5 queries of about 26 items                                                                                                                                   |
| A8  | Queue a missing pair once              | `PutItem COMMUTE#…/TOWN#…` with `status = pending` and condition `attribute_not_exists(pk)`. If it succeeds, send the SQS message; if not, another search already queued it                                                             |
| A9  | Store a commute result                 | Worker `UpdateItem` to `ok` with minutes, or to `unavailable` after the final attempt or from the DLQ handler                                                                                                                           |
| A10 | Data freshness                         | `GetItem RENT / CURRENT`                                                                                                                                                                                                                |

There are no scans and no secondary indexes. Reading search results is A1 + A6 + A7: at most 7 requests, all single-partition, which leaves room within the 500 ms target. Commute and rent items carry no TTL. Commutes are refreshed by the monthly job.

## Assumptions to confirm

| ID  | Assumption                                                                                                                          | Confirm with      |
| --- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| C1  | Rent is the trailing 12-month median whole-flat rent per town and flat type                                                         | #2 (data profile) |
| C2  | Flat type by group size: 2 → 3-ROOM, 3 → 4-ROOM, 4–5 → 5-ROOM                                                                       | #2 and team (D12) |
| C3  | Town names follow HDB's dataset spelling, upper case, and are used as keys                                                          | #2                |
| C4  | OneMap search gives coordinates for free-text Singapore places, and stations can be snapped from them                               | #3, #14           |
| C5  | Commute = OneMap public-transport route from a town's reference point to the destination station, weekday 08:30, shortest itinerary | #3, #15           |
| C6  | Station codes (for example `CC24`) are stable cache keys; interchanges use one code                                                 | #3, #14           |
| C7  | OneMap rate limits allow about 250 routing calls per minute                                                                         | #3                |

## Open questions

- **Q1** Group expiry: 30 days from creation. Is that long enough for a house hunt?
- **Q2** Should the organiser be able to remove a member (for example, a duplicate after a lost device)? Not in this version.
- **Q3** Device recovery: rejoining as a new member needs a free place. Should the organiser be able to reissue a member's link instead?
- **Q4** Should `size` be editable after creation? Not in this version; create a new group instead.
