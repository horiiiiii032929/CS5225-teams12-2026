# Shared AWS dev environment

## Target and responsibility

Hikaru supplied and designated account `553455762180` on 14 October 2026 for the shared FlatSplit dev deployment. Region: `ap-southeast-1`. Stack: `FlatSplit-dev`. Shyam coordinates subsequent infrastructure changes; WK reviews them. Use one shared deployment for demo URLs and eventual group data, while contributors continue local development independently.

Credentials are temporary NUS SSO credentials stored only in the ignored root `.env`. They expire and need local replacement when AWS reports an expired session. Never commit them or put them in frontend variables. Follow the root README's credential loading and account identity checks for future operations.

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

The frontend currently uses fictional prototype data. Group persistence/APIs, rental ingestion/publication and persistent destination caching remain open implementation work. Provisioning the stack does not complete the shared-group journey.

Secrets Manager creates a placeholder for the OneMap token. The live token and its renewal must be provided through the server-side secret; deployment does not establish live destination-lookup acceptance.

The read-only Cost Explorer `ListCostAllocationTags` request returned `AccessDeniedException`: the linked account cannot access cost allocation tags. The organisation's management/payer-account billing operator must verify the `project` tag activation and measurement window for #45. Application deployment credentials alone cannot resolve that control. No cost-tag activation, historical backfill or budget change was performed.

## Acceptance run after a deployment — 20 October 2026

`tools/acceptance/acceptance.py` runs the #44 acceptance gate against a deployed API in one command and writes a JSON evidence file that records the mode and the revision under test:

```bash
python3 tools/acceptance/acceptance.py \
    --base-url https://<host>/api --mode deployed --revision "$(git rev-parse --short HEAD)"
```

It uses only the Python standard library, so it needs no repository setup on the machine that runs it, and it exits non-zero when a check fails. The live destination lookup still requires the OneMap token in the stage secret; without it `/places` returns 503 and the journey stops at stage 1. `tools/acceptance/README.md` records what each stage checks, and why an absent #15 worker is recorded as a measured gap instead of a failure.
