import { useState } from 'react';
import type {
  AreaResult,
  GroupView,
  SearchView,
} from '@flatsplit/contracts/api';

const money = (value: number | null) =>
  value === null
    ? 'Unavailable'
    : `S$${value.toLocaleString('en-SG', { maximumFractionDigits: 2 })}`;
const minutes = (value: number | null) =>
  value === null ? 'Unavailable' : `${value} min`;

function MemberCommute({
  area,
  member,
}: {
  area: AreaResult;
  member: GroupView['members'][number];
}) {
  const outcome = area.members.find(
    (item) => item.memberId === member.memberId,
  );
  return (
    <>
      <strong>
        {outcome?.routeStatus === 'ok'
          ? minutes(outcome.commuteMinutes)
          : 'Route unavailable'}
      </strong>
      <p className="live-caption">
        {member.destination?.label ?? 'Destination unavailable'}
      </p>
      <p className="live-caption">
        Limit {minutes(member.maxCommute)} ·{' '}
        {outcome?.commuteHeadroom === null ||
        outcome?.commuteHeadroom === undefined
          ? 'Headroom unavailable'
          : `${outcome.commuteHeadroom} min to spare`}
      </p>
      <p className="live-caption">
        Budget {money(member.budget)} ·{' '}
        {outcome?.budgetHeadroom === null ||
        outcome?.budgetHeadroom === undefined
          ? 'Headroom unavailable'
          : `${money(outcome.budgetHeadroom)} to spare`}
      </p>
    </>
  );
}

export function RankedResults({
  search,
  group,
  checkedAt,
}: {
  search: SearchView;
  group: GroupView;
  checkedAt: number;
}) {
  const [selected, setSelected] = useState<string[]>(() =>
    search.ranked.slice(0, 3).map((area) => area.town),
  );
  // Callers also gate this view; keep the boundary safe when used independently.
  if (
    search.status !== 'complete' ||
    search.groupRevision !== group.revision ||
    group.latestSearch?.status === 'stale'
  )
    return null;
  const comparison = search.ranked.filter((area) =>
    selected.includes(area.town),
  );
  return (
    <div className="live-ranked-results">
      <h3>Ranked neighbourhoods</h3>
      <p>
        Server ranking: {search.priority}. Lower rent, shorter average commutes
        and a smaller commute gap are the trade-offs. Every included town must
        meet each member’s limits.
      </p>
      <p className="live-caption">
        Ranking weights: rent {search.weights.rent * 100}%, average commute{' '}
        {search.weights.averageCommute * 100}%, commute gap{' '}
        {search.weights.commuteGap * 100}%. A score is a comparison aid, not a
        probability.
      </p>
      <ol className="live-ranked-list">
        {search.ranked.map((area, index) => (
          <li key={area.town} className="result-card">
            <div className="result-body">
              <div className="result-top">
                <h4>
                  #{area.rank ?? index + 1} {area.displayName}
                </h4>
                <label className="compare-check">
                  <input
                    type="checkbox"
                    checked={selected.includes(area.town)}
                    disabled={
                      !selected.includes(area.town) && comparison.length >= 3
                    }
                    onChange={(event) =>
                      setSelected(
                        event.target.checked
                          ? [...selected, area.town]
                          : selected.filter((town) => town !== area.town),
                      )
                    }
                    aria-label={`Compare ${area.displayName}`}
                  />{' '}
                  Compare
                </label>
              </div>
              <p>
                <strong>{money(area.rentPerPerson)} per person/month</strong> ·
                Whole flat {money(area.wholeFlatRent)}
              </p>
              <p>
                Average {minutes(area.averageCommute)} · Longest{' '}
                {minutes(area.longestCommute)} · Commute gap{' '}
                {minutes(area.commuteGap)}
              </p>
              <p className="live-caption">
                Longest journey:{' '}
                {group.members.find(
                  (member) => member.memberId === area.mostBurdenedMemberId,
                )?.name ?? 'Unavailable'}
                . Score: {area.score ?? 'Unavailable'}.
              </p>
              <details>
                <summary>Every member’s commute in {area.displayName}</summary>
                <ul className="live-outcomes">
                  {group.members.map((member) => (
                    <li key={member.memberId}>
                      <h5>{member.name}</h5>
                      <MemberCommute area={area} member={member} />
                    </li>
                  ))}
                </ul>
                <p className="live-caption">
                  Whole-flat rent middle 50%: {money(area.rentP25)}–
                  {money(area.rentP75)}; median 95% confidence interval:{' '}
                  {money(area.rentMedianCi95Low)}–
                  {money(area.rentMedianCi95High)}. Samples:{' '}
                  {area.rentSampleSize ?? 'Unavailable'}; quality:{' '}
                  {area.rentQualityStatus ?? 'Unavailable'}.
                </p>
              </details>
            </div>
          </li>
        ))}
      </ol>
      {search.ranked.length > 0 && (
        <section aria-labelledby="comparison-heading">
          <h3 id="comparison-heading">
            Compare towns side by side ({comparison.length}/3)
          </h3>
          <p className="live-caption">
            Choose up to three towns above. Compare rent and each person’s
            journey before deciding together.
          </p>
          {comparison.length > 0 ? (
            <div
              className="comparison-scroll"
              role="region"
              aria-label="Ranked town comparison"
              tabIndex={0}
            >
              <table>
                <caption className="sr-only">
                  Rent, individual commutes and fairness for selected towns
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Your group</th>
                    {comparison.map((area) => (
                      <th scope="col" key={area.town}>
                        {area.displayName}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">Monthly rent / person</th>
                    {comparison.map((area) => (
                      <td key={area.town}>{money(area.rentPerPerson)}</td>
                    ))}
                  </tr>
                  {group.members.map((member) => (
                    <tr key={member.memberId}>
                      <th scope="row">{member.name}’s commute</th>
                      {comparison.map((area) => (
                        <td key={area.town}>
                          <MemberCommute area={area} member={member} />
                        </td>
                      ))}
                    </tr>
                  ))}
                  {(
                    [
                      ['Average commute', 'averageCommute'],
                      ['Longest commute', 'longestCommute'],
                      ['Commute gap', 'commuteGap'],
                    ] as const
                  ).map(([label, field]) => (
                    <tr key={field}>
                      <th scope="row">{label}</th>
                      {comparison.map((area) => (
                        <td key={area.town}>{minutes(area[field])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p role="status">Select towns to compare.</p>
          )}
          <p className="live-caption">
            Commute gap is longest minus shortest journey. A smaller gap is more
            equal travel time; a cheaper town may still leave one member with a
            longer journey.
          </p>
        </section>
      )}
      {search.excluded.length > 0 && (
        <details>
          <summary>Why {search.excluded.length} towns were excluded</summary>
          <ul>
            {search.excluded.map((area) => (
              <li key={area.town}>
                <strong>{area.displayName}</strong>
                <ul>
                  {area.reasons.map((reason, index) => (
                    <li key={index}>
                      {reason.memberId
                        ? `${group.members.find((member) => member.memberId === reason.memberId)?.name ?? 'Member'}: `
                        : ''}
                      {reason.message}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </details>
      )}
      <section
        aria-label="Data freshness"
        className="live-caption live-rent-note"
      >
        <p>
          Rent coverage: {search.data.rentPeriod}. Source:{' '}
          {search.data.rentSource ?? 'Not supplied'}. Flat type:{' '}
          {search.data.flatType}.
        </p>
        <p>{search.data.commuteBasis ?? 'Commute basis not supplied'}.</p>
        <p>
          Results last checked: {new Date(checkedAt).toLocaleString('en-SG')}.
          This is the response check time, not the age of the underlying data.
          The API does not supply rent publication or individual route update
          timestamps.
        </p>
        <p>
          Rent is an estimate split equally across the group, excluding bills;
          it is not an available listing or a guaranteed price.
        </p>
      </section>
    </div>
  );
}
