// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import type { AreaResult } from '@flatsplit/contracts/api';
import { afterEach, describe, expect, it } from 'vitest';
import { SearchExclusions } from './SearchExclusions';
import { groupFixture, searchFixture } from './test-fixtures';

type Reason = AreaResult['reasons'][number];

afterEach(cleanup);
function town(town: string, reasons: Reason[]): AreaResult {
  return {
    town,
    displayName: town,
    rank: null,
    score: null,
    wholeFlatRent: null,
    rentPerPerson: null,
    rentP25: null,
    rentP75: null,
    rentMedianCi95Low: null,
    rentMedianCi95High: null,
    rentSampleSize: null,
    rentQualityStatus: null,
    averageCommute: null,
    longestCommute: null,
    shortestCommute: null,
    commuteGap: null,
    mostBurdenedMemberId: null,
    members: [],
    reasons,
  };
}
const reason = (
  code: Reason['code'],
  memberId: string | null = null,
  amount: number | null = null,
): Reason => ({ code, memberId, amount, message: 'Untrusted upstream copy' });

describe('empty-search recovery guidance', () => {
  it('counts towns once per reason, names affected members and rounds excess upward', () => {
    const group = groupFixture();
    const search = searchFixture('complete');
    search.excluded = [
      town('Queenstown', [
        reason('OVER_BUDGET', group.members[0]!.memberId, 0.01),
        reason('OVER_BUDGET', group.members[1]!.memberId, 150),
        reason('OVER_COMMUTE', group.members[0]!.memberId, 0.01),
      ]),
      town('Bishan', [reason('OVER_COMMUTE', group.members[1]!.memberId, 10)]),
    ];
    const before = structuredClone({ group, search });
    render(<SearchExclusions group={group} search={search} />);
    expect(screen.getByText('Over budget: 1 town')).toBeTruthy();
    expect(screen.getByText('Over commute limit: 2 towns')).toBeTruthy();
    expect(screen.getByText(/If everyone agrees/)).toBeTruthy();
    expect(
      screen.getByText('Alex’s budget is exceeded by S$1 per month.'),
    ).toBeTruthy();
    expect(
      screen.getByText('Alex’s commute limit is exceeded by 1 min.'),
    ).toBeTruthy();
    expect(
      screen.getByText('Jamie’s budget is exceeded by S$150 per month.'),
    ).toBeTruthy();
    expect(screen.queryByText('Untrusted upstream copy')).toBeNull();
    expect({ group, search }).toEqual(before);
  });
  it('does not suggest relaxing constraints when only data is missing or uncertain', () => {
    const search = searchFixture('complete');
    search.excluded = [
      town('Bishan', [reason('RENT_UNAVAILABLE'), reason('ROUTE_UNAVAILABLE')]),
      town('Clementi', [reason('RENT_LOW_CONFIDENCE')]),
    ];
    render(<SearchExclusions group={groupFixture()} search={search} />);
    expect(
      screen.getByText(/Changing budgets will not fix missing/),
    ).toBeTruthy();
    expect(
      screen.getByText(/A higher commute limit does not make/),
    ).toBeTruthy();
    expect(screen.queryByText(/consider a longer commute limit/)).toBeNull();
    expect(
      screen.queryByText(/review the monthly budgets together/),
    ).toBeNull();
    expect(screen.getByText('Rent data missing: 1 town')).toBeTruthy();
    expect(
      screen.getByText('Rent evidence too uncertain: 1 town'),
    ).toBeTruthy();
    expect(screen.getByText('Route unavailable: 1 town')).toBeTruthy();
    expect(screen.queryByText(/0 min/)).toBeNull();
  });
  it('does not invent a reason when the response supplies no exclusion evidence', () => {
    render(
      <SearchExclusions
        group={groupFixture()}
        search={searchFixture('complete')}
      />,
    );
    expect(
      screen.getByText(/We cannot tell which limit to change/),
    ).toBeTruthy();
    expect(screen.queryByText(/Over budget:/)).toBeNull();
    expect(screen.queryByText(/consider a longer/)).toBeNull();
  });
  it('handles unknown members and missing amounts without inventing a zero or a person', () => {
    const search = searchFixture('complete');
    search.excluded = [town('Bishan', [reason('OVER_COMMUTE', 'unknown')])];
    render(<SearchExclusions group={groupFixture()} search={search} />);
    expect(
      screen.getByText('A flatmate’s commute limit is exceeded.'),
    ).toBeTruthy();
    const details = screen
      .getByText('See why each town was excluded')
      .closest('details')!;
    expect(within(details).queryByText(/0 min|unknown/)).toBeNull();
  });
});
