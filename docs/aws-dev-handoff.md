# Shared AWS dev environment

## Target and responsibility

Hikaru supplied and designated account `553455762180` on 14 October 2026 for the shared FlatSplit dev deployment. Region: `ap-southeast-1`. Stack: `FlatSplit-dev`. Shyam coordinates subsequent infrastructure changes; WK reviews them. Use one shared deployment for demo URLs and eventual group data, while contributors continue local development independently.

Credentials are temporary NUS SSO credentials stored only in the ignored root `.env`. They expire and need local replacement when AWS reports an expired session. Never commit them or put them in frontend variables. Follow the root README's credential loading and account identity checks for future operations.

## Current implementation versus deployment — 20 October 2026

`main` at `760dd1f` includes group persistence/APIs, filtering/ranking, search submission/status and the SQS producer/queue definitions. These changes merged after the deployment recorded below. No later deployment is recorded here; do not infer that the shared environment runs current main.

Read-only HTTP checks on 20 October returned 200 for the shared frontend and `/api/health`, with health body `{"status":"ok","service":"flatsplit-api"}`. This verifies availability only. It does not establish the deployed revision, live OneMap credentials, shared-device persistence, an operating worker or real recommendations. The browser and deployment evidence below remains dated 14 October and was not repeated by this HTTP check.

Raw ingestion (PR #64) and persistent places/station pins/query caching (PR #65) are open, unmerged work at this snapshot. Validated rent publication (#10), the commute worker/retries/DLQ handling (#15/#27), frontend integration and deployed group/search acceptance remain outstanding. See the [repository status](../README.md#repository-status--20-october-2026) and [current issue hub](https://github.com/horiiiiii032929/CS5225-teams12-2026/issues/44).

## Deployment evidence — 14 October 2026

- The supplied credentials passed STS identity verification for the designated account.
- The existing main application build and AWS workspace typecheck passed.
- CDK diff showed a new dev stack with the planned table, Lambda/HTTP API, server-side OneMap secret and private S3/CloudFront frontend.
- `CDKToolkit` bootstrap completed successfully. Bootstrap used CDK's standard execution policy, without trusting additional accounts. No personal AWS profile was modified.
- `FlatSplit-dev` deployment completed successfully from application main commit `4394195`.
- Shared frontend: <https://d2g88qlwvm8dec.cloudfront.net>.
- Shared API health: <https://d2g88qlwvm8dec.cloudfront.net/api/health> returned HTTP 200 with `{"status":"ok","service":"flatsplit-api"}`. The direct API health endpoint at <https://n1igu3dv2m.execute-api.ap-southeast-1.amazonaws.com/health> also returned that response.
- Browser checks at 1280 × 900 and 390 × 844 verified the deployed creation shell; document width matched viewport width at both sizes. The deployed `/status` route displayed “API connected.”
- HTTP checks verified frontend `/` and SPA route `/status` return 200, invalid destination query `/api/places?q=x` returns the expected 422 validation error, and `/api/not-a-route` returns the expected 404 error.

Stack outputs:

| Output              | Value                                           |
| ------------------- | ----------------------------------------------- |
| `TableName`         | `FlatSplit-dev-DataTableFDBAD0F2-14BXCFXGNJCMO` |
| `OneMapTokenSecret` | `ApiOneMapTokenF0E7B331-vldt8VEfRzrA`           |

The secret name is configuration; its value is never recorded here. CDK used the supplied same-account credentials when the SSO role could not assume the bootstrap deploy role. The deploy completed, but subsequent teammates still need their own authorised account access and valid sessions; credentials are not shared through GitHub.

## Remaining integration and billing work

The last recorded deployed frontend still uses fictional prototype data; local #7/#17 API-backed creation/join/reopen/progress has not been deployed. Group persistence/APIs are implemented on main; acceptance against real persisted destinations and the shared deployment is outstanding. Rental publication, persistent destination integration and an operating commute worker are separate remaining handoffs. Provisioning the stack or passing health checks does not complete the shared-group journey.

Secrets Manager creates a placeholder for the OneMap token. The live token and its renewal must be provided through the server-side secret; deployment does not establish live destination-lookup acceptance.

The read-only Cost Explorer `ListCostAllocationTags` request returned `AccessDeniedException`: the linked account cannot access cost allocation tags. The organisation's management/payer-account billing operator must verify the `project` tag activation and measurement window for #45. Application deployment credentials alone cannot resolve that control. No cost-tag activation, historical backfill or budget change was performed.

## Acceptance attempt — 20 October 2026, 19:30–19:35 SGT (#7/#17)

After [PR #66](https://github.com/horiiiiii032929/CS5225-teams12-2026/pull/66) merged, acceptance was checked against repository main `2f6ae012562be66077227a3e5ad49c7bf7a5ad86` and the existing shared CloudFront URL. [Main CI passed](https://github.com/horiiiiii032929/CS5225-teams12-2026/actions/runs/39414062114). Neither issue passed deployed acceptance, so both remain open. This dated attempt supplements the earlier evidence; it does not identify a new deployment revision.

Observed deployed responses:

| Request                                            | HTTP | Result                                                      |
| -------------------------------------------------- | ---- | ----------------------------------------------------------- |
| `GET /api/health`                                  | 200  | `{"status":"ok","service":"flatsplit-api"}`                 |
| `POST /api/groups` with valid creation fields      | 404  | `{"error":{"code":"NOT_FOUND","message":"Unknown route."}}` |
| `GET /api/groups/AAAAAAAAAAAAAAAAAAAAAA`           | 404  | Same `Unknown route.` envelope                              |
| `POST /api/groups/AAAAAAAAAAAAAAAAAAAAAA/searches` | 404  | Same `Unknown route.` envelope                              |

The example ID is a synthetic probe, not a stored group or credential. The creation request returned no member/invite capability. The deployed HTML referenced `index-CJLLsq1s.js` and `index-B9SdQ4c6.css`. Its exact Git revision could not be established through the public health endpoint; the availability response alone does not establish that the merged APIs are running.

Playwright against the shared deployment showed the explicit “Interactive wireframe · fictional data” banner. The creation flow produced a **preview** invite (`?review=join`), not a group capability. In an independent mobile browser, that link opened fictional sample data rather than the custom group. The processing preview explicitly identified simulated progress. These observations establish that the visible prototype cannot satisfy cross-device persistence or real queued/processing/ready/failed-calculation acceptance. Desktop/mobile screenshots and raw HTTP captures were kept outside the repository; no live credentials are included in this record.

### Remaining closure gate

- **#7:** deploy the reviewed API-backed frontend and group APIs to the designated shared dev account. Verify a real creation POST and copyable capability link; open/join it in an independent browser/device, confirm the same group after reload, and exercise useful loading, invalid/full-group and transient-error recovery states. Link the deployed revision and that evidence in the issue. #7 can be verified independently of an operating commute worker.
- **#17:** provide integrated preference entry (#8/#13), persisted destinations (#14), validated rent publication (#10), and an operating commute worker/retry handoff (#15/#27), then deploy the integrated build. Observe actual queued → processing → ready progress, terminal unavailable/failed calculations, and an explicit eligible calculation retry while both members’ saved inputs remain unchanged after reload. A request-status outage retry and injected local worker results do not establish this calculation-retry gate. #14 is still in open PR #65; open PR #67 is acceptance tooling, not worker completion or deployed evidence.

The ignored root `.env` was loaded only for an STS identity check against the designated account configuration. `GetCallerIdentity` returned `InvalidClientTokenId`; account identity could not be verified. No CDK diff/deployment, bootstrap, direct table/queue mutation, token-secret operation or live OneMap lookup was attempted. Temporary credentials must be refreshed locally before any deployment can proceed; they must not be pasted into GitHub or chat.

Local supporting verification passed again: **35 frontend group/search tests**, **67 API search/queue/group-journey tests**, and the non-mutating API contract drift check. These are fixture/Moto checks and do not change the failed/blocked deployed verdict above. The full merged-build suite had already passed 330 tests, with the linked main CI passing as well.

### Local #17 acceptance follow-up

The same audit found one client-state gap: when every route was unavailable, the completed calculation was still labelled “Ready” and used the limits/no-match heading. The follow-up distinguishes that case as “Routes unavailable” and offers “Retry route calculations”; partially successful results and genuine constraint failures retain their existing behavior. Its new regression failed before the fix and passed afterwards. In the actual local resolver/Moto browser harness, injected unavailable claims with an elapsed retry window became pending under the same search ID after retry, and saved members/revision stayed identical through reload. Completion was also injected conditionally, not produced by OneMap. This supports the local retry behavior only.

Final local checks passed: format/check/test/build/synth and generated-contract drift, with 331 tests (258 API, 65 web, five CDK, three offline evidence tests). The earlier 35-test frontend rerun above predates this additional regression. The user could not refresh AWS credentials during this attempt, so the integrated deployment and issue closure checks remain deferred.

## Deployment — 21 October 2026 (main `6091db8`)

Shyam deployed `FlatSplit-dev` from repository main `6091db8` with Hikaru's agreement, using refreshed NUS SSO credentials in the ignored root `.env`. The README subshell confirmed the designated account `553455762180` before both the diff and the deploy. As on 14 October, the SSO role could not assume the bootstrap deploy role and CDK used the same-account credentials. The stack reached `UPDATE_COMPLETE` at 13:18 UTC.

The reviewed `cdk diff` beforehand was additive: the `CommuteJobs` queue and its DLQ (both denying non-TLS access), the API Lambda's new code with `TABLE_NAME` and `COMMUTE_QUEUE_URL` and a 30 s timeout, key-prefix-scoped DynamoDB permissions (`GROUP#*` read/write, `PLACE#*` read, `RENT`/`RENT#*` read, `COMMUTE#*` read/write), `SendMessage` on the jobs queue, the rebuilt web assets and a `CommuteQueueUrl` output. The table, CloudFront distribution, OneMap secret and throttling were unchanged; nothing was deleted.

Checks after the deploy, against `https://d2g88qlwvm8dec.cloudfront.net`:

- `/api/health` returns 200. `GET /api/groups/<unknown>` now returns `404 NOT_FOUND` "Group not found or expired." from storage, instead of the earlier `Unknown route`, and an empty create body returns the contract's 422 envelope. The web bundle changed to `index-D2SooS-c.js`.
- The #29 journey (`FLATSPLIT_API_URL=…/api`) passed create, invite-link restrictions, joining to capacity, `GROUP_FULL` and invalid-preference rejection for both 2- and 5-member groups, then skipped at the first real preference save because the deployed API has no persisted places (#14). It created two short-lived test groups that expire with their TTL. The 12 response-mutation cases run only against the isolated local API and were skipped by design; the 10 HTTP-client redirect tests passed.
- `GET /api/places` returns `503 UPSTREAM_UNAVAILABLE`. Lambda logs show `OneMap token warning` followed by `OneMap lookup failed`: the token value in the `OneMapTokenSecret` secret appears expired (OneMap tokens last about three days; search answers during its grace period but the follow-up call fails). No secret value was read or changed. Refreshing it is a credential operation for the token owner.

What this means for acceptance: group create/join/read on the shared deployment is now evidenced for #12 and #7, but preference saves need #14 (PR #65) and a valid OneMap token, and searches need published rent (#10) and the commute worker (#15). The frontend acceptance in #7 still needs a real cross-browser create/copy/join/reload walk-through on this build.
