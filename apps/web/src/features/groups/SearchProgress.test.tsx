// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { client } from '@/api/generated/client.gen';
import { SearchProgress } from './SearchProgress';
import { searchKey } from './api';
import {
  groupFixture,
  membership,
  searchFixture,
  mapSearchFixture,
} from './test-fixtures';

const transport = vi.fn<typeof fetch>();
let cache: QueryClient;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
beforeEach(() => {
  transport.mockReset();
  client.setConfig({ baseUrl: 'https://flatsplit.test/api', fetch: transport });
  cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
});
afterEach(() => {
  cleanup();
  cache.clear();
  vi.useRealTimers();
});
function mount(group = groupFixture()) {
  return render(
    <QueryClientProvider client={cache}>
      <SearchProgress
        group={group}
        membership={membership}
        groupUpdatedAt={100}
      />
    </QueryClientProvider>,
  );
}
describe('real search lifecycle UI', () => {
  it('shows the completed map, then removes it when the group revision changes', async () => {
    const complete = mapSearchFixture();
    transport.mockImplementation(async () => json(complete));
    const group = {
      ...groupFixture(),
      latestSearch: {
        searchId: complete.searchId,
        status: 'complete' as const,
        createdAt: groupFixture().createdAt,
      },
    };
    const ui = mount(group);
    await screen.findByRole('button', {
      name: 'Show Queenstown on map, rank 1',
    });
    ui.rerender(
      <QueryClientProvider client={cache}>
        <SearchProgress
          group={{ ...group, revision: group.revision + 1 }}
          membership={membership}
          groupUpdatedAt={101}
        />
      </QueryClientProvider>,
    );
    await screen.findByText('Your group has changed');
    expect(
      screen.queryByRole('region', { name: 'Singapore town reference map' }),
    ).toBeNull();
  });
  it('withholds submission until the group is ready', () => {
    const group = { ...groupFixture(), allReady: false, readyCount: 1 };
    mount(group);
    expect(
      (
        screen.getByRole('button', {
          name: 'Find our neighbourhoods',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      screen.getByText('Waiting for 1 flatmate to submit preferences.'),
    ).toBeTruthy();
    expect(transport).not.toHaveBeenCalled();
  });
  it('submits once, displays server counts and never invents a completed result', async () => {
    transport.mockImplementation(async () => json(searchFixture()));
    mount();
    fireEvent.click(
      screen.getByRole('button', { name: 'Find our neighbourhoods' }),
    );
    await screen.findByText('Your route checks are queued.');
    expect(screen.getByText('0 of 52 routes checked.')).toBeTruthy();
    expect(screen.queryByText(/neighbourhoods meet everyone/)).toBeNull();
    expect(
      transport.mock.calls.filter(
        ([request]) => (request as Request).method === 'POST',
      ),
    ).toHaveLength(1);
    expect(
      (
        screen.getByRole('button', {
          name: 'Search in progress',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
  it('does not mistake an unavailable-only pair for worker progress', async () => {
    const pending = searchFixture();
    pending.progress = { total: 27, resolved: 1, unavailable: 1 };
    transport.mockImplementation(async () => json(pending));
    mount({
      ...groupFixture(),
      latestSearch: {
        searchId: pending.searchId,
        status: 'pending',
        createdAt: groupFixture().createdAt,
      },
    });
    await screen.findByText('Your route checks are queued.');
    expect(screen.getByText('Queued')).toBeTruthy();
    expect(
      screen.getByText('1 of 27 routes checked · 1 unavailable.'),
    ).toBeTruthy();
  });
  it('keeps inputs after a failed submission and allows an explicit retry', async () => {
    transport
      .mockResolvedValueOnce(
        json({ error: { code: 'SERVICE_UNAVAILABLE' } }, 503),
      )
      .mockImplementation(async () => json(searchFixture()));
    mount();
    fireEvent.click(
      screen.getByRole('button', { name: 'Find our neighbourhoods' }),
    );
    await screen.findByText('Could not start the search');
    expect(screen.getByText(/Refresh your group to confirm/)).toBeTruthy();
    expect(transport).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole('button', { name: 'Find our neighbourhoods' }),
    );
    await screen.findByText('Your route checks are queued.');
  });
  it('shows partial progress and unavailable counts, then ready status from the server', async () => {
    const pending = searchFixture();
    pending.progress = { total: 52, resolved: 10, unavailable: 2 };
    transport.mockImplementation(async () => json(pending));
    const group = {
      ...groupFixture(),
      latestSearch: {
        searchId: pending.searchId,
        status: 'pending' as const,
        createdAt: groupFixture().createdAt,
      },
    };
    mount(group);
    await screen.findByText('10 of 52 routes checked · 2 unavailable.');
    const complete = {
      ...pending,
      status: 'complete' as const,
      progress: { total: 52, resolved: 52, unavailable: 2 },
    };
    transport.mockImplementation(async () => json(complete));
    fireEvent.click(screen.getByRole('button', { name: 'Check progress now' }));
    await screen.findByText('No neighbourhood meets all your current limits.');
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Some routes were unavailable')).toBeTruthy();
  });
  it('distinguishes total route failure and retries the same calculation without changing group inputs', async () => {
    const failed = searchFixture('complete');
    failed.progress = { total: 52, resolved: 52, unavailable: 52 };
    const retry = searchFixture();
    transport.mockImplementation(async (request) =>
      json((request as Request).method === 'POST' ? retry : failed),
    );
    const group = {
      ...groupFixture(),
      latestSearch: {
        searchId: failed.searchId,
        status: 'complete' as const,
        createdAt: groupFixture().createdAt,
      },
    };
    const before = structuredClone(group);
    mount(group);
    await screen.findByText('We couldn’t calculate your group’s routes.');
    expect(screen.getByText('Routes unavailable')).toBeTruthy();
    expect(screen.queryByText('Ready')).toBeNull();
    expect(
      screen.queryByText('No neighbourhood meets all your current limits.'),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry route calculations' }),
    );
    await screen.findByText('Your route checks are queued.');
    const posts = transport.mock.calls
      .map(([request]) => request as Request)
      .filter((request) => request.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0]!.url).toBe(
      `https://flatsplit.test/api/groups/${membership.groupId}/searches`,
    );
    expect(await posts[0]!.text()).toBe('');
    expect(cache.getQueryData(searchKey(membership, failed.searchId))).toEqual(
      retry,
    );
    expect(group).toEqual(before);
  });
  it('shows a newly accepted search while the group still carries its previous stale summary', async () => {
    const old = {
      ...searchFixture('stale'),
      searchId: 'O'.repeat(22),
      groupRevision: 2,
    };
    const fresh = searchFixture();
    transport.mockImplementation(async (request) => {
      const input = request as Request;
      return json(
        input.method === 'POST' || input.url.endsWith(fresh.searchId)
          ? fresh
          : old,
      );
    });
    const ui = mount({
      ...groupFixture(),
      latestSearch: {
        searchId: old.searchId,
        status: 'stale',
        createdAt: groupFixture().createdAt,
      },
    });
    await screen.findByText('Your group has changed');
    fireEvent.click(
      screen.getByRole('button', { name: 'Search latest preferences' }),
    );
    await screen.findByText('Your route checks are queued.');
    expect(screen.queryByText('Your group has changed')).toBeNull();
    expect(
      transport.mock.calls.some(([request]) =>
        (request as Request).url.endsWith(fresh.searchId),
      ),
    ).toBe(true);
    // A later authoritative stale summary must still hide results (e.g. a new
    // routing profile), even when the group revision has not changed.
    ui.rerender(
      <QueryClientProvider client={cache}>
        <SearchProgress
          group={{
            ...groupFixture(),
            latestSearch: {
              searchId: fresh.searchId,
              status: 'stale',
              createdAt: groupFixture().createdAt,
            },
          }}
          membership={membership}
          groupUpdatedAt={200}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText('Your group has changed')).toBeTruthy();
    expect(screen.queryByText('Your route checks are queued.')).toBeNull();
  });
  it('hides cached completed results immediately when the group revision changes', async () => {
    const complete = searchFixture('complete');
    transport.mockImplementation(async () => json(complete));
    const group = {
      ...groupFixture(),
      latestSearch: {
        searchId: complete.searchId,
        status: 'complete' as const,
        createdAt: groupFixture().createdAt,
      },
    };
    const ui = mount(group);
    await screen.findByText('No neighbourhood meets all your current limits.');
    ui.rerender(
      <QueryClientProvider client={cache}>
        <SearchProgress
          group={{ ...group, revision: 4 }}
          groupUpdatedAt={200}
          membership={membership}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText('Your group has changed')).toBeTruthy();
    expect(
      screen.queryByText('No neighbourhood meets all your current limits.'),
    ).toBeNull();
  });
  it('recovers a status outage without issuing another POST', async () => {
    const pending = searchFixture();
    transport
      .mockResolvedValueOnce(
        json({ error: { code: 'SERVICE_UNAVAILABLE' } }, 503),
      )
      .mockImplementation(async () => json(pending));
    mount({
      ...groupFixture(),
      latestSearch: {
        searchId: pending.searchId,
        status: 'pending',
        createdAt: groupFixture().createdAt,
      },
    });
    await screen.findByText('Could not check search progress');
    fireEvent.click(
      screen.getByRole('button', { name: 'Check progress again' }),
    );
    await screen.findByText('Your route checks are queued.');
    expect(
      transport.mock.calls.every(
        ([request]) => (request as Request).method === 'GET',
      ),
    ).toBe(true);
  });
  it('offers one recovery action when a pending search status refresh fails', async () => {
    const pending = searchFixture();
    transport
      .mockResolvedValueOnce(json(pending))
      .mockResolvedValue(json({ error: { code: 'SERVICE_UNAVAILABLE' } }, 503));
    mount({
      ...groupFixture(),
      latestSearch: {
        searchId: pending.searchId,
        status: 'pending',
        createdAt: groupFixture().createdAt,
      },
    });
    await screen.findByText('Your route checks are queued.');
    fireEvent.click(screen.getByRole('button', { name: 'Check progress now' }));
    await screen.findByText('Could not check search progress');
    expect(
      screen.queryByRole('button', { name: 'Check progress now' }),
    ).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Check progress again' }),
    ).toBeTruthy();
    expect(screen.getByText('Needs attention')).toBeTruthy();
    expect(
      screen.queryByRole('button', { name: 'Search in progress' }),
    ).toBeNull();
    expect(
      transport.mock.calls.every(
        ([request]) => (request as Request).method === 'GET',
      ),
    ).toBe(true);
  });
  it('does not expose results from a malformed response', async () => {
    transport.mockResolvedValue(
      json({ status: 'complete', ranked: [{ displayName: 'Invented area' }] }),
    );
    mount({
      ...groupFixture(),
      latestSearch: {
        searchId: 'S'.repeat(22),
        status: 'complete',
        createdAt: groupFixture().createdAt,
      },
    });
    await screen.findByText('Could not check search progress');
    expect(screen.queryByText('Invented area')).toBeNull();
  });
  it('stops background status polling after completion', async () => {
    const complete = searchFixture('complete');
    transport.mockImplementation(async () => json(complete));
    mount({
      ...groupFixture(),
      latestSearch: {
        searchId: complete.searchId,
        status: 'complete',
        createdAt: groupFixture().createdAt,
      },
    });
    await screen.findByText('No neighbourhood meets all your current limits.');
    vi.useFakeTimers();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4500);
    });
    expect(transport).toHaveBeenCalledTimes(1);
    expect(
      cache.getQueryData(searchKey(membership, complete.searchId)),
    ).toBeTruthy();
    vi.useRealTimers();
  });
});
