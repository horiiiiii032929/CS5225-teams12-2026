// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { RankedResults } from './RankedResults';
import { groupFixture, rankedSearchFixture } from './test-fixtures';

afterEach(cleanup);
const checkedAt = Date.parse('2026-10-29T02:00:00Z');
function mount(search = rankedSearchFixture()) {
  return render(
    <RankedResults
      search={search}
      group={groupFixture()}
      checkedAt={checkedAt}
    />,
  );
}
it('compares three server-ranked towns and matches fractional commutes by member ID', () => {
  mount();
  const table = screen.getByRole('table');
  expect(
    within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent),
  ).toEqual(['Your group', 'Clementi', 'Queenstown', 'Bukit Merah']);
  const alex = within(table)
    .getByRole('rowheader', { name: 'Alex’s commute' })
    .closest('tr')!;
  expect(alex.textContent).toContain('30.5 min');
  expect(alex.textContent).toContain('S$400 to spare');
  const jamie = within(table)
    .getByRole('rowheader', { name: 'Jamie’s commute' })
    .closest('tr')!;
  expect(jamie.textContent).toContain('20 min');
  expect(jamie.textContent).not.toContain('30.5 min');
  expect(
    within(table).getByRole('rowheader', { name: 'Commute gap' }).closest('tr')!
      .textContent,
  ).toContain('10.5 min');
  expect(screen.getByText(/Ranking weights/).textContent).toContain('35%');
});
it('lets users replace comparison towns without recomputing or reordering the server ranking', () => {
  mount();
  expect(
    (screen.getByLabelText('Compare Jurong East') as HTMLInputElement).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByLabelText('Compare Queenstown'));
  fireEvent.click(screen.getByLabelText('Compare Jurong East'));
  const headers = within(screen.getByRole('table'))
    .getAllByRole('columnheader')
    .map((cell) => cell.textContent);
  expect(headers).toEqual([
    'Your group',
    'Clementi',
    'Bukit Merah',
    'Jurong East',
  ]);
  expect(
    screen
      .getAllByRole('heading', { level: 4 })
      .map((heading) => heading.textContent),
  ).toEqual([
    '#1 Clementi',
    '#2 Queenstown',
    '#3 Bukit Merah',
    '#4 Jurong East',
  ]);
});
it('shows actual coverage and honest freshness limits rather than manufacturing data timestamps', () => {
  mount();
  const freshness = screen.getByRole('region', { name: 'Data freshness' });
  expect(freshness.textContent).toContain('2025-10/2026-09');
  expect(freshness.textContent).toContain('HDB rental approvals');
  expect(freshness.textContent).toContain('not the age of the underlying data');
  expect(freshness.textContent).toContain('does not supply rent publication');
});
it.each(['pending', 'stale'] as const)(
  'withholds %s payloads even if they contain ranked towns',
  (status) => {
    const search = rankedSearchFixture();
    search.status = status;
    mount(search);
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByText(/Clementi/)).toBeNull();
  },
);
it('withholds results when the group revision changes', () => {
  const search = rankedSearchFixture();
  search.groupRevision--;
  mount(search);
  expect(screen.queryByRole('table')).toBeNull();
});
it('never turns missing route or rent values into zero', () => {
  const search = rankedSearchFixture();
  search.ranked[0]!.members[1]!.routeStatus = 'unavailable';
  search.ranked[0]!.members[1]!.commuteMinutes = null;
  search.ranked[0]!.rentPerPerson = null;
  mount(search);
  const row = within(screen.getByRole('table'))
    .getByRole('rowheader', { name: 'Alex’s commute' })
    .closest('tr')!;
  expect(row.textContent).toContain('Route unavailable');
  const rent = within(screen.getByRole('table'))
    .getByRole('rowheader', { name: 'Monthly rent / person' })
    .closest('tr')!;
  expect(rent.textContent).toContain('Unavailable');
  expect(rent.textContent).not.toContain('S$0');
});
it('keeps exclusion reasons distinct from ranked recommendations', () => {
  const search = rankedSearchFixture();
  const excluded = structuredClone(search.ranked.pop()!);
  excluded.rank = null;
  excluded.score = null;
  excluded.reasons = [
    {
      code: 'OVER_COMMUTE',
      memberId: groupFixture().members[0]!.memberId,
      amount: 5,
      message: 'Commute exceeds limit by 5 min',
    },
  ];
  search.excluded.push(excluded);
  mount(search);
  expect(screen.getByText('Alex: Commute exceeds limit by 5 min')).toBeTruthy();
  expect(screen.queryByLabelText('Compare Jurong East')).toBeNull();
});
