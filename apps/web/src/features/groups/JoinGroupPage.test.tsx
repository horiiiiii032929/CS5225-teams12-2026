// @vitest-environment jsdom
import type { ReactNode } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { client } from '@/api/generated/client.gen';
import { JoinGroupPage } from './JoinGroupPage';
import { groupKey } from './api';
import { readMembership, saveMembership } from './membership';
import { createdFixture, groupFixture, membership } from './test-fixtures';

const navigate = vi.hoisted(() => vi.fn());
vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  useNavigate: () => navigate,
  Navigate: () => <p>Membership reopened</p>,
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));
const transport = vi.fn<typeof fetch>();
let cache: QueryClient;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  navigate.mockClear();
  transport.mockReset();
  window.history.replaceState(
    null,
    '',
    `/join/${membership.groupId}#${membership.inviteToken}`,
  );
  client.setConfig({ baseUrl: 'https://flatsplit.test/api', fetch: transport });
  cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(() => {
  cleanup();
  cache.clear();
});
function mount() {
  return render(
    <QueryClientProvider client={cache}>
      <JoinGroupPage groupId={membership.groupId} />
    </QueryClientProvider>,
  );
}
it('accepts a corrected invite pasted into the same tab and strips its fragment', async () => {
  window.history.replaceState(null, '', `/join/${membership.groupId}`);
  mount();
  expect(screen.getByText('This invite is incomplete')).toBeTruthy();

  window.location.hash = membership.inviteToken!;

  await screen.findByRole('button', { name: 'Join the group' });
  expect(window.location.hash).toBe('');
  expect(transport).not.toHaveBeenCalled();
});
it('keeps a valid invitation when the skip link moves focus to the main content', async () => {
  mount();
  expect(screen.getByRole('button', { name: 'Join the group' })).toBeTruthy();

  window.location.hash = 'main-content';
  fireEvent(window, new Event('hashchange'));

  expect(screen.getByRole('button', { name: 'Join the group' })).toBeTruthy();
  expect(window.location.hash).toBe('#main-content');

  cleanup();
  mount();
  expect(screen.getByRole('button', { name: 'Join the group' })).toBeTruthy();
  expect(window.location.hash).toBe('#main-content');
});
describe('returning invite membership checks', () => {
  it('reopens a valid saved membership without consuming another group place', async () => {
    saveMembership(createdFixture());
    transport.mockResolvedValue(json({ group: groupFixture() }));
    mount();
    await screen.findByText('Membership reopened');
    expect(screen.queryByRole('button', { name: 'Join the group' })).toBeNull();
    expect(transport).toHaveBeenCalledTimes(1);
    const request = transport.mock.calls[0]![0] as Request;
    expect(request.method).toBe('GET');
    expect(request.headers.get('Authorization')).toBe(
      `Bearer ${membership.memberToken}`,
    );
  });
  it('allows the original invitation to replace a rejected saved capability', async () => {
    saveMembership(createdFixture());
    transport
      .mockResolvedValueOnce(json({ error: { code: 'UNAUTHORIZED' } }, 401))
      .mockImplementation(async () =>
        json(
          {
            group: groupFixture(),
            memberId: 'J'.repeat(22),
            memberToken: 'N'.repeat(43),
          },
          201,
        ),
      );
    mount();
    await screen.findByRole('button', { name: 'Join the group' });
    fireEvent.change(screen.getByLabelText('Your first name'), {
      target: { value: 'Jamie' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Join the group' }));
    await vi.waitFor(() =>
      expect(navigate).toHaveBeenCalledWith(
        expect.objectContaining({ to: '/groups/$groupId' }),
      ),
    );
    expect(readMembership(membership.groupId)?.memberId).toBe('J'.repeat(22));
    const joinRequest = transport.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.method === 'POST')!;
    expect(joinRequest.headers.get('Authorization')).toBe(
      `Bearer ${membership.inviteToken}`,
    );
    expect(window.location.hash).toBe('');
  });
  it('verifies cached membership again before redirecting a returning invite', async () => {
    saveMembership(createdFixture());
    cache.setQueryData(groupKey(membership), groupFixture());
    let rejectAccess!: (value: Response) => void;
    transport.mockReturnValue(
      new Promise<Response>((resolve) => {
        rejectAccess = resolve;
      }),
    );
    mount();
    expect(screen.queryByText('Membership reopened')).toBeNull();
    rejectAccess(json({ error: { code: 'UNAUTHORIZED' } }, 401));
    await screen.findByRole('button', { name: 'Join the group' });
  });
  it('does not offer a duplicate join when saved membership verification has a service outage', async () => {
    saveMembership(createdFixture());
    transport.mockResolvedValue(
      json({ error: { code: 'SERVICE_UNAVAILABLE' } }, 503),
    );
    mount();
    await screen.findByText('Could not verify your membership');
    expect(screen.queryByRole('button', { name: 'Join the group' })).toBeNull();
    expect(
      transport.mock.calls.every(
        ([request]) => (request as Request).method === 'GET',
      ),
    ).toBe(true);
    expect(readMembership(membership.groupId)?.memberToken).toBe(
      membership.memberToken,
    );
  });
});
