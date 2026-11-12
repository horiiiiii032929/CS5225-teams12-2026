import type {
  CreatedGroupResponse,
  MembershipResponse,
} from '@flatsplit/contracts/api';

export interface Membership {
  version: 1;
  groupId: string;
  groupName: string;
  memberId: string;
  memberToken: string;
  inviteToken?: string;
  expiresAt: string;
}
const prefix = 'flatsplit:membership:';
const memory = new Map<string, Membership>();
const unpersisted = new Set<string>();
const invitations = new Map<string, string>();
export const validId = (value: string) => /^[A-Za-z0-9_-]{22}$/.test(value);
const validToken = (value: unknown): value is string =>
  typeof value === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value);

function parse(value: unknown): Membership | null {
  if (typeof value !== 'object' || value === null) return null;
  const item = value as Partial<Membership>;
  return item.version === 1 &&
    typeof item.groupId === 'string' &&
    validId(item.groupId) &&
    typeof item.memberId === 'string' &&
    validId(item.memberId) &&
    validToken(item.memberToken) &&
    typeof item.groupName === 'string' &&
    typeof item.expiresAt === 'string' &&
    Date.parse(item.expiresAt) > Date.now() &&
    (item.inviteToken === undefined || validToken(item.inviteToken))
    ? (item as Membership)
    : null;
}
export function readMembership(groupId: string): Membership | null {
  if (!validId(groupId)) return null;
  // A replacement capability may be newer than storage when its write failed.
  // Keep this tab on the membership it just received, including its warning.
  if (unpersisted.has(groupId)) return parse(memory.get(groupId));
  try {
    const item = parse(
      JSON.parse(localStorage.getItem(prefix + groupId) ?? 'null'),
    );
    if (item?.groupId === groupId) return item;
  } catch {
    /* Storage may be blocked; preserve access for this tab. */
  }
  return parse(memory.get(groupId));
}
export function saveMembership(
  response: CreatedGroupResponse | MembershipResponse,
): { membership: Membership; persisted: boolean } {
  const membership: Membership = {
    version: 1,
    groupId: response.group.groupId,
    groupName: response.group.groupName,
    memberId: response.memberId,
    memberToken: response.memberToken,
    expiresAt: response.group.expiresAt,
    ...('inviteToken' in response.group
      ? { inviteToken: response.group.inviteToken }
      : {}),
  };
  if (!parse(membership)) throw new Error('Invalid membership response.');
  memory.set(membership.groupId, membership);
  try {
    localStorage.setItem(
      prefix + membership.groupId,
      JSON.stringify(membership),
    );
    unpersisted.delete(membership.groupId);
    return { membership, persisted: true };
  } catch {
    unpersisted.add(membership.groupId);
    return { membership, persisted: false };
  }
}
export function savedMemberships(): Membership[] {
  const groups = new Map(memory);
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith(prefix)) {
        const membership = readMembership(key.slice(prefix.length));
        if (membership) groups.set(membership.groupId, membership);
      }
    }
  } catch {
    /* The current tab can still use memory membership. */
  }
  return [...groups.values()].filter((item) => parse(item));
}
export function membershipIsPersisted(membership: Membership) {
  try {
    return (
      localStorage.getItem(prefix + membership.groupId) ===
      JSON.stringify(membership)
    );
  } catch {
    return false;
  }
}
export function inviteLink(
  membership: Membership,
  origin = window.location.origin,
) {
  return membership.inviteToken
    ? `${origin}/join/${membership.groupId}#${membership.inviteToken}`
    : null;
}
export function captureInvite(groupId: string): string | null {
  const key = `flatsplit:invite:${groupId}`;
  const fragment = window.location.hash.slice(1);
  // The app-wide skip link uses an ordinary anchor on the join page too.
  const hasInviteFragment = fragment !== '' && fragment !== 'main-content';
  // Strip before any API request; it must never become a query parameter.
  if (hasInviteFragment)
    window.history.replaceState(
      window.history.state,
      '',
      window.location.pathname + window.location.search,
    );
  if (!validId(groupId) || (hasInviteFragment && !validToken(fragment))) {
    clearInvite(groupId);
    return null;
  }
  if (validToken(fragment)) {
    invitations.set(groupId, fragment);
    try {
      sessionStorage.setItem(key, fragment);
    } catch {
      /* memory fallback */
    }
  }
  const current = invitations.get(groupId);
  if (current) return current;
  try {
    const stored = sessionStorage.getItem(key);
    if (validToken(stored)) return stored;
  } catch {
    /* memory fallback */
  }
  return invitations.get(groupId) ?? null;
}
export function clearInvite(groupId: string) {
  invitations.delete(groupId);
  try {
    sessionStorage.removeItem(`flatsplit:invite:${groupId}`);
  } catch {
    /* best effort */
  }
}
