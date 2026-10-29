// @vitest-environment jsdom
import type { ReactNode } from 'react';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { client } from '@/api/generated/client.gen';
import { MemberPreferencesForm } from './MemberPreferencesForm';
import { LiveGroupPage } from './LiveGroupPage';
import { groupKey } from './api';
import { createdFixture, groupFixture, membership } from './test-fixtures';
import { saveMembership } from './membership';

vi.mock('@tanstack/react-router', async (original) => ({
  ...(await original<typeof import('@tanstack/react-router')>()),
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));
const transport = vi.fn<typeof fetch>();
let cache: QueryClient;
const saved = vi.fn();
const cancelled = vi.fn();
const placeFixture = {
  placeId: 'pl_kent_ridge',
  label: 'Kent Ridge',
  address: 'Kent Ridge, Singapore',
  station: {
    stationKey: 'KENT_RIDGE',
    name: 'Kent Ridge',
    codes: ['CC24'],
    lat: 1.29,
    lng: 103.78,
    snapMetres: 0,
    snapWarning: false,
  },
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
function readyGroup() {
  const group = groupFixture();
  group.members.forEach((member) => {
    member.destination = placeFixture;
  });
  return group;
}
beforeEach(() => {
  transport.mockReset();
  saved.mockReset();
  cancelled.mockReset();
  localStorage.clear();
  cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setConfig({ baseUrl: 'https://flatsplit.test/api', fetch: transport });
});
afterEach(() => {
  cleanup();
  cache.clear();
  vi.useRealTimers();
});
function mount(member = readyGroup().members[0]!) {
  return render(
    <QueryClientProvider client={cache}>
      <MemberPreferencesForm
        member={member}
        membership={membership}
        onSaved={saved}
        onCancel={cancelled}
      />
    </QueryClientProvider>,
  );
}
const field = (name: string, value: string) =>
  fireEvent.change(screen.getByLabelText(name), { target: { value } });
const submit = () =>
  fireEvent.submit(
    screen
      .getByRole('button', { name: 'Save my preferences' })
      .closest('form')!,
  );
it('prefills saved fields and cancels without sending any request', () => {
  mount();
  expect(
    (
      screen.getByLabelText(
        'Your monthly rent budget (SGD)',
      ) as HTMLInputElement
    ).value,
  ).toBe('1600');
  expect(
    (
      screen.getByLabelText(
        'Where do you travel to most days?',
      ) as HTMLInputElement
    ).value,
  ).toBe('Kent Ridge');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(cancelled).toHaveBeenCalledOnce();
  expect(transport).not.toHaveBeenCalled();
});
it.each([
  ['Your monthly rent budget (SGD)', '299'],
  ['Your monthly rent budget (SGD)', '5001'],
  ['Longest comfortable commute (minutes)', '9'],
  ['Longest comfortable commute (minutes)', '121'],
  ['Longest comfortable commute (minutes)', '30.5'],
  ['First name', '   '],
])('rejects invalid %s = %s without a PUT', (label, value) => {
  mount();
  field(label, value);
  submit();
  expect(transport).not.toHaveBeenCalled();
});
it('requires explicit destination selection and debounces searches, hiding obsolete results immediately', async () => {
  transport.mockResolvedValue(
    json({ places: [placeFixture], unsupported: [], ambiguous: false }),
  );
  mount({ ...readyGroup().members[0]!, destination: null });
  field('Where do you travel to most days?', 'Ke');
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 350));
  });
  expect(transport).not.toHaveBeenCalled();
  field('Where do you travel to most days?', 'Kent');
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
  expect(transport).not.toHaveBeenCalled();
  await screen.findByRole('button', { name: /Kent Ridge · Kent Ridge/ });
  submit();
  expect(saved).not.toHaveBeenCalled();
  field('Where do you travel to most days?', 'Bishan');
  expect(
    screen.queryByRole('button', { name: /Kent Ridge · Kent Ridge/ }),
  ).toBeNull();
});
it('shows unsupported reasons and requires a supported selection', async () => {
  transport.mockResolvedValue(
    json({
      places: [],
      unsupported: [
        {
          label: 'Island',
          address: 'Island',
          code: 'NO_STATION',
          snapMetres: null,
          message: 'No nearby station',
        },
      ],
      ambiguous: false,
    }),
  );
  mount({ ...readyGroup().members[0]!, destination: null });
  field('Where do you travel to most days?', 'Island');
  await screen.findByText('Island: No nearby station');
  submit();
  expect(saved).not.toHaveBeenCalled();
  expect(screen.getByRole('alert').textContent).toContain(
    'Choose a destination',
  );
});
it('updates the cached group from the PUT before closing even when later reads are unavailable', async () => {
  const updated = readyGroup();
  updated.revision++;
  updated.members[0]!.budget = 1800;
  transport.mockResolvedValue(json({ group: updated }));
  mount();
  field('Your monthly rent budget (SGD)', '1800');
  submit();
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(cache.getQueryData(groupKey(membership))).toEqual(updated);
  const request = transport.mock.calls[0]![0] as Request;
  expect(request.headers.get('authorization')).toBe(
    `Bearer ${membership.memberToken}`,
  );
  expect(request.url).toContain(`/members/${membership.memberId}`);
  expect(await request.json()).toMatchObject({
    placeId: placeFixture.placeId,
    budget: 1800,
  });
});
it('retains edits on expired-place errors and explains how to select a fresh destination', async () => {
  transport.mockResolvedValue(json({ error: { code: 'NOT_FOUND' } }, 404));
  mount();
  field('Your monthly rent budget (SGD)', '1900');
  submit();
  await screen.findByText(/Search for the destination again/);
  expect(
    (
      screen.getByLabelText(
        'Your monthly rent budget (SGD)',
      ) as HTMLInputElement
    ).value,
  ).toBe('1900');
  expect(saved).not.toHaveBeenCalled();
});
it('keeps a pending save single-flight and prevents cancelling while it is in flight', async () => {
  let finish!: (response: Response) => void;
  transport.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  mount();
  submit();
  await screen.findByRole('button', { name: 'Saving…' });
  fireEvent.submit(
    screen.getByRole('button', { name: 'Saving…' }).closest('form')!,
  );
  expect(
    (
      screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement
    ).closest('fieldset')!.disabled,
  ).toBe(true);
  expect(transport).toHaveBeenCalledOnce();
  await act(async () => finish(json({ group: readyGroup() })));
});
it('reopens saved edits for the editor and a second member with separate fresh query caches', async () => {
  let group = readyGroup();
  transport.mockImplementation(async (input) => {
    const request = input as Request;
    if (request.method === 'PUT') {
      const body = await request.json();
      group = {
        ...group,
        revision: group.revision + 1,
        members: group.members.map((member) =>
          member.memberId === membership.memberId
            ? { ...member, budget: body.budget }
            : member,
        ),
      };
    }
    return json({ group });
  });
  saveMembership({
    ...createdFixture(),
    group: { ...group, inviteToken: membership.inviteToken! },
  });
  const mountLobby = () =>
    render(
      <QueryClientProvider client={cache}>
        <LiveGroupPage groupId={membership.groupId} />
      </QueryClientProvider>,
    );
  let ui = mountLobby();
  fireEvent.click(
    await screen.findByRole('button', { name: 'Edit your preferences' }),
  );
  expect(
    screen.getAllByRole('button', { name: 'Save my preferences' }),
  ).toHaveLength(1);
  field('Your monthly rent budget (SGD)', '1800');
  submit();
  await screen.findByText(/S\$1,800\/month/);
  ui.unmount();
  cache.clear();
  cache = new QueryClient();
  ui = mountLobby();
  fireEvent.click(
    await screen.findByRole('button', { name: 'Edit your preferences' }),
  );
  expect(
    (
      screen.getByLabelText(
        'Your monthly rent budget (SGD)',
      ) as HTMLInputElement
    ).value,
  ).toBe('1800');
  ui.unmount();
  cache.clear();
  cache = new QueryClient();
  saveMembership({
    group,
    memberId: group.members[1]!.memberId,
    memberToken: 'N'.repeat(43),
  });
  mountLobby();
  await screen.findByText(/S\$1,800\/month/);
  fireEvent.click(
    screen.getByRole('button', { name: 'Edit your preferences' }),
  );
  expect(
    (
      screen.getByLabelText(
        'Your monthly rent budget (SGD)',
      ) as HTMLInputElement
    ).value,
  ).toBe('1500');
  const last = transport.mock.calls.at(-1)![0] as Request;
  expect(last.headers.get('authorization')).toBe(`Bearer ${'N'.repeat(43)}`);
});

it.each([500, 502, 503, 504])(
  'does not promise unchanged preferences after a committed PUT returns %s',
  async (status) => {
    const serverGroup = readyGroup();
    transport.mockImplementation(async (input) => {
      const body = await (input as Request).json();
      serverGroup.members[0]!.budget = body.budget;
      return json({ error: { code: 'SERVICE_UNAVAILABLE' } }, status);
    });
    mount();
    field('Your monthly rent budget (SGD)', '1850');
    submit();
    await screen.findByText(/Could not save your preferences/);
    expect(serverGroup.members[0]!.budget).toBe(1850);
    expect(screen.queryByText(/saved group inputs are unchanged/)).toBeNull();
    expect(screen.getByText(/Refresh your group to confirm/)).toBeTruthy();
    expect(saved).not.toHaveBeenCalled();
    expect(
      (
        screen.getByLabelText(
          'Your monthly rent budget (SGD)',
        ) as HTMLInputElement
      ).value,
    ).toBe('1850');
  },
);
