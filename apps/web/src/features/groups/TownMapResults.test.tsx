// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TownMapResults } from './TownMapResults';
import { mapMarkers } from './town-map';
import { groupFixture, rankedSearchFixture } from './test-fixtures';
import referencePoints from './town-reference-points.json';

afterEach(cleanup);
describe('ranked town map and equivalent detail selection', () => {
  it('selects the same detail from a numbered map pin and the ordinary town list', () => {
    render(
      <TownMapResults search={rankedSearchFixture()} group={groupFixture()} />,
    );
    expect(screen.getByRole('heading', { name: 'Queenstown' })).toBeTruthy();
    fireEvent.click(
      screen.getByRole('button', { name: 'Show Clementi on map, rank 2' }),
    );
    expect(screen.getByRole('heading', { name: 'Clementi' })).toBeTruthy();
    const list = screen.getByRole('list', { name: 'Recommended towns' });
    expect(
      within(list)
        .getByRole('button', { name: /Clementi/ })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    fireEvent.click(within(list).getByRole('button', { name: /Bishan/ }));
    expect(screen.getByRole('heading', { name: 'Bishan' })).toBeTruthy();
    expect(
      screen
        .getByRole('button', { name: 'Show Bishan on map, rank 3' })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    expect(within(screen.getByRole('table')).getByText('Alex')).toBeTruthy();
    expect(within(screen.getByRole('table')).getByText('Jamie')).toBeTruthy();
    expect(screen.getByText(/2025-10\/2026-09/)).toBeTruthy();
    expect(screen.getByText(/Route calculation date unavailable/)).toBeTruthy();
  });
  it('drops removed towns and uses new response data without retaining an old result snapshot', () => {
    const search = rankedSearchFixture();
    const view = render(
      <TownMapResults search={search} group={groupFixture()} />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Show Clementi on map, rank 2' }),
    );
    const next = { ...search, ranked: [search.ranked[2]!] };
    view.rerender(<TownMapResults search={next} group={groupFixture()} />);
    expect(screen.getByRole('heading', { name: 'Bishan' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Clementi' })).toBeNull();
  });
  it.each(['pending', 'stale'] as const)('withholds %s results', (status) => {
    render(
      <TownMapResults
        search={{ ...rankedSearchFixture(), status }}
        group={groupFixture()}
      />,
    );
    expect(
      screen.queryByRole('region', { name: 'Singapore town reference map' }),
    ).toBeNull();
  });
  it('withholds a completed result after a revision edit or loss of readiness', () => {
    const search = rankedSearchFixture();
    const group = groupFixture();
    const view = render(
      <TownMapResults
        search={search}
        group={{ ...group, revision: group.revision + 1 }}
      />,
    );
    expect(screen.queryByRole('heading')).toBeNull();
    view.rerender(
      <TownMapResults search={search} group={{ ...group, allReady: false }} />,
    );
    expect(screen.queryByRole('heading')).toBeNull();
  });
  it('keeps an unmapped town accessible without inventing coordinates or zero rent', () => {
    const search = rankedSearchFixture();
    search.ranked = [
      {
        ...search.ranked[0]!,
        town: 'FUTURE TOWN',
        displayName: 'Future town',
        rentPerPerson: null,
      },
    ];
    render(<TownMapResults search={search} group={groupFixture()} />);
    expect(screen.queryByRole('button', { name: /on map/ })).toBeNull();
    expect(screen.getByRole('heading', { name: 'Future town' })).toBeTruthy();
    expect(
      screen.getByText(/No verified map point for Future town/),
    ).toBeTruthy();
    expect(screen.queryByText('S$0')).toBeNull();
  });
  it('rounds displayed commutes up without modifying feasibility inputs', () => {
    const search = rankedSearchFixture();
    const before = structuredClone(search);
    render(<TownMapResults search={search} group={groupFixture()} />);
    expect(within(screen.getByRole('table')).getByText('31 min')).toBeTruthy();
    expect(search).toEqual(before);
  });
  it('separates all mapped-town touch targets while preserving the geographic anchors', () => {
    const template = rankedSearchFixture().ranked[0]!;
    const all = Object.keys(referencePoints).map((town, index) => ({
      ...template,
      town,
      rank: index + 1,
    }));
    const markers = mapMarkers(all);
    expect(markers).toHaveLength(26);
    for (let i = 0; i < markers.length; i += 1) {
      for (let j = 0; j < i; j += 1) {
        expect(
          Math.hypot(
            markers[i]!.marker.x - markers[j]!.marker.x,
            markers[i]!.marker.y - markers[j]!.marker.y,
          ),
        ).toBeGreaterThanOrEqual(48);
      }
    }
  });
});
