import {
  zCreatedGroupResponse,
  zGroupResponse,
  zMembershipResponse,
  zSearchView,
  zPlacesResponse,
} from '@flatsplit/contracts/api';
import { queryOptions } from '@tanstack/react-query';
import { client } from '@/api/generated/client.gen';
import * as sdk from '@/api/generated/sdk.gen';
import type { Membership } from './membership';

client.setConfig({
  baseUrl: (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, ''),
  cache: 'no-store',
  credentials: 'omit',
  redirect: 'error',
});

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}
function unwrap<T>(result: {
  data?: T;
  error?: unknown;
  response?: Response;
}): T {
  if (result.data !== undefined) return result.data;
  const error = result.error;
  const envelope =
    typeof error === 'object' && error !== null && 'error' in error
      ? error.error
      : null;
  const responseCode =
    typeof envelope === 'object' &&
    envelope !== null &&
    'code' in envelope &&
    typeof envelope.code === 'string'
      ? envelope.code
      : undefined;
  const fallbackCodes: Record<number, string> = {
    401: 'UNAUTHORIZED',
    403: 'FORBIDDEN',
    404: 'NOT_FOUND',
    409: 'CONFLICT',
    429: 'RATE_LIMITED',
    500: 'SERVICE_UNAVAILABLE',
    502: 'SERVICE_UNAVAILABLE',
    503: 'SERVICE_UNAVAILABLE',
    504: 'SERVICE_UNAVAILABLE',
  };
  const code =
    (error instanceof Error || error instanceof DOMException) &&
    error.name === 'TimeoutError'
      ? 'REQUEST_TIMEOUT'
      : (responseCode ??
        fallbackCodes[result.response?.status ?? 0] ??
        'REQUEST_FAILED');
  // Use controlled copy; never reflect arbitrary upstream response bodies or tokens.
  const messages: Record<string, string> = {
    REQUEST_TIMEOUT:
      'The request took too long. We could not confirm the result. Refresh your group before retrying.',
    GROUP_FULL:
      'This group is full. If you joined before, reopen it in the browser you used to join.',
    GROUP_NOT_READY:
      'Everyone needs to join and submit preferences before the search can start.',
    NOT_FOUND: 'This group or search is unavailable or has expired.',
    UNAUTHORIZED:
      'This browser no longer has access. Use the original invite link to join if there is space.',
    FORBIDDEN: 'This membership cannot perform that action.',
    VALIDATION_FAILED:
      'Check your entries. Names must be unique within the group.',
    CONFLICT: 'The group changed at the same time. Refresh it and try again.',
    RATE_LIMITED: 'Too many requests. Wait a moment, then try again.',
    SERVICE_UNAVAILABLE:
      'The service or rental data is temporarily unavailable. Refresh your group to confirm its saved inputs before retrying.',
  };
  throw new ApiError(
    result.response?.status ?? 0,
    code,
    messages[code] ??
      'We could not reach the service. Check your connection and try again.',
  );
}
const auth = (membership: Membership) => ({
  Authorization: `Bearer ${membership.memberToken}`,
});

export async function searchPlaces(query: string, signal?: AbortSignal) {
  // q is read from the raw query string by the resolver and is absent from
  // OpenAPI; the client query serializer still encodes it normally.
  return zPlacesResponse.parse(
    unwrap(
      await client.get({
        url: '/places',
        query: { q: query },
        signal: signal
          ? AbortSignal.any([signal, AbortSignal.timeout(35000)])
          : AbortSignal.timeout(35000),
      }),
    ),
  );
}
export async function savePreferences(
  membership: Membership,
  body: {
    name: string;
    placeId: string;
    budget: number;
    maxCommute: number;
  },
) {
  return zGroupResponse.parse(
    unwrap(
      await sdk.savePreferences({
        path: {
          group_id: membership.groupId,
          member_id: membership.memberId,
        },
        body,
        headers: auth(membership),
        signal: AbortSignal.timeout(35000),
      }),
    ),
  ).group;
}
export async function createGroup(body: {
  groupName: string;
  name: string;
  size: number;
}) {
  return zCreatedGroupResponse.parse(
    unwrap(await sdk.createGroup({ body, signal: AbortSignal.timeout(35000) })),
  );
}
export async function joinGroup(
  groupId: string,
  inviteToken: string,
  name: string,
) {
  return zMembershipResponse.parse(
    unwrap(
      await sdk.joinGroup({
        path: { group_id: groupId },
        body: { name },
        headers: { Authorization: `Bearer ${inviteToken}` },
        signal: AbortSignal.timeout(35000),
      }),
    ),
  );
}
export async function readGroup(membership: Membership, signal: AbortSignal) {
  return zGroupResponse.parse(
    unwrap(
      await sdk.readGroup({
        path: { group_id: membership.groupId },
        headers: auth(membership),
        signal: AbortSignal.any([signal, AbortSignal.timeout(35000)]),
      }),
    ),
  ).group;
}
export const groupKey = (membership: Membership) =>
  ['group', membership.groupId, membership.memberId] as const;
export const groupOptions = (membership: Membership) =>
  queryOptions({
    queryKey: groupKey(membership),
    queryFn: ({ signal }) => readGroup(membership, signal),
    staleTime: 0,
    refetchInterval: (query) => (query.state.status === 'error' ? false : 5000),
    retry: false,
  });
export const searchKey = (membership: Membership, searchId: string) =>
  ['search', membership.groupId, membership.memberId, searchId] as const;
export const searchOptions = (membership: Membership, searchId: string) =>
  queryOptions({
    queryKey: searchKey(membership, searchId),
    queryFn: async ({ signal }) =>
      zSearchView.parse(
        unwrap(
          await sdk.readSearch({
            path: { group_id: membership.groupId, search_id: searchId },
            headers: auth(membership),
            signal: AbortSignal.any([signal, AbortSignal.timeout(35000)]),
          }),
        ),
      ),
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.status !== 'error' && query.state.data?.status === 'pending'
        ? 2000
        : false,
    retry: false,
  });
export async function startSearch(membership: Membership) {
  return zSearchView.parse(
    unwrap(
      await sdk.startSearch({
        path: { group_id: membership.groupId },
        headers: auth(membership),
        signal: AbortSignal.timeout(35000),
      }),
    ),
  );
}
export function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : 'We could not load a valid response. Check your connection and try again.';
}
