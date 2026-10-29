import type {
  AreaResult,
  GroupView,
  SearchView,
} from '@flatsplit/contracts/api';

type Reason = AreaResult['reasons'][number];

const labels: Record<Reason['code'], string> = {
  OVER_BUDGET: 'Over budget',
  OVER_COMMUTE: 'Over commute limit',
  ROUTE_UNAVAILABLE: 'Route unavailable',
  RENT_UNAVAILABLE: 'Rent data missing',
  RENT_LOW_CONFIDENCE: 'Rent evidence too uncertain',
};

function reasonText(reason: Reason, group: GroupView) {
  const name = group.members.find(
    (member) => member.memberId === reason.memberId,
  )?.name;
  const person = name ?? 'A flatmate';
  const amount =
    reason.amount !== null &&
    Number.isFinite(reason.amount) &&
    reason.amount > 0
      ? Math.ceil(reason.amount).toLocaleString('en-SG')
      : null;
  switch (reason.code) {
    case 'OVER_BUDGET':
      return `${person}’s budget is exceeded${amount ? ` by S$${amount} per month` : ''}.`;
    case 'OVER_COMMUTE':
      return `${person}’s commute limit is exceeded${amount ? ` by ${amount} min` : ''}.`;
    case 'ROUTE_UNAVAILABLE':
      return `A route for ${name ?? 'a flatmate'} could not be calculated. Its duration is unknown.`;
    case 'RENT_UNAVAILABLE':
      return 'No rent data is available for your group’s flat type.';
    case 'RENT_LOW_CONFIDENCE':
      return 'The rent evidence is too uncertain to compare budgets.';
  }
}

/** Compose only with current, completed, empty results; owns no inputs or fetches. */
export function SearchExclusions({
  search,
  group,
}: {
  search: SearchView;
  group: GroupView;
}) {
  const counts = new Map<Reason['code'], number>();
  for (const town of search.excluded) {
    for (const code of new Set(town.reasons.map((reason) => reason.code))) {
      counts.set(code, (counts.get(code) ?? 0) + 1);
    }
  }
  return (
    <section className="live-exclusions" aria-labelledby="exclusions-heading">
      <h4 id="exclusions-heading">What you can do next</h4>
      <p>Your group inputs are saved. No preferences have been changed.</p>
      {counts.has('OVER_BUDGET') && (
        <p>
          Some towns exceed a flatmate’s budget. If everyone agrees, review the
          monthly budgets together before starting a new search.
        </p>
      )}
      {counts.has('OVER_COMMUTE') && (
        <p>
          Some commutes exceed a flatmate’s limit. If it works for that person,
          consider a longer commute limit, then search with the updated
          preferences.
        </p>
      )}
      {(counts.has('RENT_UNAVAILABLE') ||
        counts.has('RENT_LOW_CONFIDENCE')) && (
        <p>
          Some towns lack reliable rent evidence for your group’s flat type.
          Changing budgets will not fix missing or uncertain data. Try again
          after the rental data is refreshed.
        </p>
      )}
      {counts.has('ROUTE_UNAVAILABLE') && (
        <p>
          Some route durations are unknown. Try searching again later; retries
          may have to wait for the routing service. A higher commute limit does
          not make an unavailable route valid.
        </p>
      )}
      {counts.size > 0 ? (
        <>
          <ul>
            {Array.from(counts, ([code, count]) => (
              <li key={code}>
                {labels[code]}: {count} {count === 1 ? 'town' : 'towns'}
              </li>
            ))}
          </ul>
          <p className="live-caption">
            A town can have more than one reason for exclusion. Changing one
            limit does not guarantee a match.
          </p>
          <details>
            <summary>See why each town was excluded</summary>
            <ul className="live-excluded-towns">
              {search.excluded.map((town) => (
                <li key={town.town}>
                  <strong>{town.displayName}</strong>
                  <ul>
                    {town.reasons.length ? (
                      town.reasons.map((reason, index) => (
                        <li key={index}>{reasonText(reason, group)}</li>
                      ))
                    ) : (
                      <li>No exclusion details were provided for this town.</li>
                    )}
                  </ul>
                </li>
              ))}
            </ul>
          </details>
        </>
      ) : (
        <p>
          No exclusion details were provided. Check your group’s saved
          preferences and try searching again. We cannot tell which limit to
          change from this response.
        </p>
      )}
    </section>
  );
}
