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
import { groupFixture, mapSearchFixture } from './test-fixtures';
import referencePoints from './town-reference-points.json';

afterEach(cleanup);
describe('ranked town map and town selection', () => {
  it('keeps the selected pin, town picker and details in sync', () => {
    render(
      <TownMapResults search={mapSearchFixture()} group={groupFixture()} />,
    );
    expect(screen.getByRole('heading', { name: 'Queenstown' })).toBeTruthy();
    fireEvent.click(
      screen.getByRole('button', { name: 'Show Clementi on map, rank 2' }),
    );
    expect(screen.getByRole('heading', { name: 'Clementi' })).toBeTruthy();
    const picker = screen.getByRole<HTMLSelectElement>('combobox', {
      name: 'Town on map',
    });
    expect(picker.value).toBe('CLEMENTI');
    fireEvent.change(picker, { target: { value: 'BISHAN' } });
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
  it('can plot a lower-ranked town on demand without crowding the initial map', () => {
    const search = mapSearchFixture();
    search.ranked.push({
      ...search.ranked[0]!,
      town: 'WOODLANDS',
      displayName: 'Woodlands',
      rank: 4,
    });
    render(<TownMapResults search={search} group={groupFixture()} />);
    const map = screen.getByRole('region', {
      name: 'Singapore town reference map',
    });
    expect(within(map).getAllByRole('button')).toHaveLength(3);
    const picker = screen.getByRole('combobox', { name: 'Town on map' });
    fireEvent.change(picker, { target: { value: 'WOODLANDS' } });
    expect(
      within(map)
        .getByRole('button', { name: /Show Woodlands/ })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    expect(screen.getByRole('heading', { name: 'Woodlands' })).toBeTruthy();
    fireEvent.change(picker, { target: { value: 'BISHAN' } });
    expect(within(map).getAllByRole('button')).toHaveLength(3);
  });
  it('drops removed towns and uses new response data without retaining an old result snapshot', () => {
    const search = mapSearchFixture();
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
        search={{ ...mapSearchFixture(), status }}
        group={groupFixture()}
      />,
    );
    expect(
      screen.queryByRole('region', { name: 'Singapore town reference map' }),
    ).toBeNull();
  });
  it('withholds a completed result after a revision edit or loss of readiness', () => {
    const search = mapSearchFixture();
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
    const search = mapSearchFixture();
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
    const search = mapSearchFixture();
    const before = structuredClone(search);
    render(<TownMapResults search={search} group={groupFixture()} />);
    expect(within(screen.getByRole('table')).getByText('31 min')).toBeTruthy();
    expect(search).toEqual(before);
  });
  it('separates all mapped-town touch targets while preserving the geographic anchors', () => {
    const template = mapSearchFixture().ranked[0]!;
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
        ).toBeGreaterThanOrEqual(72);
      }
    }
  });
});
