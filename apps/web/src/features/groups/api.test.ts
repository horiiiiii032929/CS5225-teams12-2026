import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { client } from '@/api/generated/client.gen';
import {
  ApiError,
  createGroup,
  joinGroup,
  groupOptions,
  savePreferences,
  searchOptions,
  searchPlaces,
  startSearch,
  groupKey,
} from './api';
import {
  createdFixture,
  groupFixture,
  membership,
  searchFixture,
} from './test-fixtures';

const transport = vi.fn<typeof fetch>();
beforeEach(() => {
  transport.mockReset();
  client.setConfig({ baseUrl: 'https://flatsplit.test/api', fetch: transport });
});
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
describe('generated API transport and response boundaries', () => {
  it('creates without credentials and sends the contracted field names', async () => {
    transport.mockResolvedValue(json(createdFixture(), 201));
    const body = { groupName: 'Our next chapter', size: 2, name: 'Alex' };
    expect(await createGroup(body)).toEqual(createdFixture());
    const request = transport.mock.calls[0]![0] as Request;
    expect(request.url).toBe('https://flatsplit.test/api/groups');
    expect(request.headers.has('authorization')).toBe(false);
    expect(await request.json()).toEqual(body);
    expect(request.cache).toBe('no-store');
    expect(request.redirect).toBe('error');
  });
  it('uses the invite only for join and the member capability only for reads', async () => {
    const response = createdFixture();
    const group = groupFixture();
    transport
      .mockResolvedValueOnce(json({ ...response, group }, 201))
      .mockResolvedValueOnce(json({ group }));
    await joinGroup(membership.groupId, membership.inviteToken!, 'Jamie');
    const cache = new QueryClient();
    await cache.fetchQuery(groupOptions(membership));
    const [join, read] = transport.mock.calls.map(
      ([request]) => request as Request,
    );
    expect(join!.headers.get('authorization')).toBe(
      `Bearer ${membership.inviteToken}`,
    );
    expect(read!.headers.get('authorization')).toBe(
      `Bearer ${membership.memberToken}`,
    );
    expect(read!.url).not.toMatch(/#|memberToken|inviteToken/);
    expect(JSON.stringify(groupKey(membership))).not.toContain(
      membership.memberToken,
    );
    cache.clear();
  });
  it.each([
    ['GROUP_FULL', 409],
    ['NOT_FOUND', 404],
    ['RATE_LIMITED', 429],
    ['SERVICE_UNAVAILABLE', 503],
  ])('maps %s to a recoverable safe error', async (code, status) => {
    transport.mockResolvedValue(
      json(
        { error: { code, message: membership.memberToken } },
        Number(status),
      ),
    );
    try {
      await joinGroup(membership.groupId, membership.inviteToken!, 'Jamie');
      throw new Error('Expected rejection');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).code).toBe(code);
      expect((error as Error).message).not.toContain(membership.memberToken);
    }
  });
  it('rejects malformed success bodies rather than inventing a group', async () => {
    transport.mockResolvedValue(json({ group: {} }, 201));
    await expect(
      createGroup({ groupName: 'Group', size: 2, name: 'Alex' }),
    ).rejects.toThrow();
  });
  it('searches places and saves preferences with the member capability only', async () => {
    const places = {
      places: [
        {
          placeId: 'P'.repeat(10),
          label: 'Kent Ridge',
          address: 'Kent Ridge, Singapore',
          station: {
            stationKey: 'S'.repeat(10),
            name: 'Kent Ridge',
            codes: ['CC24'],
            lat: 1.29,
            lng: 103.78,
            snapMetres: 120,
            snapWarning: false,
          },
        },
      ],
      unsupported: [],
      ambiguous: false,
    };
    transport
      .mockResolvedValueOnce(json(places))
      .mockResolvedValueOnce(json({ group: groupFixture() }));
    expect(await searchPlaces('Kent Ridge')).toEqual(places);
    const body = {
      name: 'Alex',
      placeId: 'P'.repeat(10),
      budget: 1600,
      maxCommute: 45,
    };
    expect(await savePreferences(membership, body)).toEqual(groupFixture());
    const [, save] = transport.mock.calls.map(
      ([request]) => request as Request,
    );
    expect(save!.url).toBe(
      `https://flatsplit.test/api/groups/${membership.groupId}/members/${membership.memberId}`,
    );
    expect(save!.headers.get('authorization')).toBe(
      `Bearer ${membership.memberToken}`,
    );
    expect(await save!.json()).toEqual(body);
  });
  it('reads and resubmits the same server search without fabricating progress', async () => {
    transport.mockImplementation(async () => json(searchFixture('complete')));
    const cache = new QueryClient();
    const options = searchOptions(membership, 'S'.repeat(22));
    const response = await cache.fetchQuery(options);
    expect(response.status).toBe('complete');
    expect(await startSearch(membership)).toEqual(response);
    cache.clear();
  });
});

it('handles API Gateway throttles without reflecting its non-contract body', async () => {
  transport.mockResolvedValue(json({ message: 'Too Many Requests' }, 429));
  await expect(startSearch(membership)).rejects.toMatchObject({
    status: 429,
    code: 'RATE_LIMITED',
  });
});

it('serializes the place query, cancels obsolete lookups and validates response bodies', async () => {
  transport.mockResolvedValue(
    json({ places: [], unsupported: [], ambiguous: false }),
  );
  const abort = new AbortController();
  await searchPlaces('Kent Ridge & MRT', abort.signal);
  const request = transport.mock.calls[0]![0] as Request;
  expect(new URL(request.url).searchParams.get('q')).toBe('Kent Ridge & MRT');
  expect(request.headers.has('authorization')).toBe(false);
  abort.abort();
  expect(request.signal.aborted).toBe(true);
  transport.mockResolvedValue(
    json({ places: [{}], unsupported: [], ambiguous: false }),
  );
  await expect(searchPlaces('Kent')).rejects.toThrow();
});
