import type {
  AreaResult,
  CreatedGroupResponse,
  GroupView,
  SearchView,
} from '@flatsplit/contracts/api';
import type { Membership } from './membership';

export const membership: Membership = {
  version: 1,
  groupId: 'G'.repeat(22),
  groupName: 'Our next chapter',
  memberId: 'M'.repeat(22),
  memberToken: 'T'.repeat(43),
  inviteToken: 'I'.repeat(43),
  expiresAt: '2099-01-01T00:00:00Z',
};
export function groupFixture(): GroupView {
  return {
    groupId: membership.groupId,
    groupName: membership.groupName,
    size: 2,
    revision: 3,
    members: [
      {
        memberId: membership.memberId,
        name: 'Alex',
        isOrganiser: true,
        ready: true,
        destination: null,
        budget: 1600,
        maxCommute: 45,
      },
      {
        memberId: 'J'.repeat(22),
        name: 'Jamie',
        isOrganiser: false,
        ready: true,
        destination: null,
        budget: 1500,
        maxCommute: 40,
      },
    ],
    readyCount: 2,
    allReady: true,
    latestSearch: null,
    createdAt: '2026-10-20T00:00:00Z',
    expiresAt: membership.expiresAt,
  };
}
export function createdFixture(): CreatedGroupResponse {
  return {
    group: { ...groupFixture(), inviteToken: membership.inviteToken! },
    memberId: membership.memberId,
    memberToken: membership.memberToken,
  };
}
export function searchFixture(
  status: SearchView['status'] = 'pending',
): SearchView {
  return {
    searchId: 'S'.repeat(22),
    groupRevision: 3,
    status,
    progress: { total: 52, resolved: 0, unavailable: 0 },
    priority: 'balanced',
    weights: { rent: 0.35, averageCommute: 0.35, commuteGap: 0.3 },
    data: {
      rentPeriod: '2025-10/2026-09',
      rentSource: 'HDB rental approvals (data.gov.sg)',
      flatType: '3-ROOM',
      commuteBasis:
        'Public transport, weekday 08:30 departure; station-to-station',
    },
    ranked: [],
    excluded: [],
  };
}

/** Synthetic API-ranked towns for UI tests only; not live rental evidence. */
export function rankedSearchFixture(): SearchView {
  const search = searchFixture('complete');
  search.progress = { total: 8, resolved: 8, unavailable: 0 };
  search.ranked = ['CLEMENTI', 'QUEENSTOWN', 'BUKIT MERAH', 'JURONG EAST'].map(
    (town, index) => ({
      town,
      displayName: ['Clementi', 'Queenstown', 'Bukit Merah', 'Jurong East'][
        index
      ]!,
      rank: index + 1,
      score: 85 - index,
      wholeFlatRent: 2400 + index * 100,
      rentPerPerson: 1200 + index * 50,
      rentP25: 2200,
      rentP75: 2600,
      rentMedianCi95Low: 2300,
      rentMedianCi95High: 2500,
      rentSampleSize: 200,
      rentQualityStatus: 'USABLE',
      averageCommute: 25.25 + index,
      longestCommute: 30.5 + index,
      shortestCommute: 20 + index,
      commuteGap: 10.5,
      mostBurdenedMemberId: membership.memberId,
      // Deliberately reversed: consumers must join by memberId, not position.
      members: [
        {
          memberId: 'J'.repeat(22),
          commuteMinutes: 20 + index,
          routeStatus: 'ok',
          budgetHeadroom: 300 - index * 50,
          commuteHeadroom: 20 - index,
        },
        {
          memberId: membership.memberId,
          commuteMinutes: 30.5 + index,
          routeStatus: 'ok',
          budgetHeadroom: 400 - index * 50,
          commuteHeadroom: 14.5 - index,
        },
      ],
      reasons: [],
    }),
  );
  return search;
}

export function mapSearchFixture(): ReturnType<typeof searchFixture> {
  const group = groupFixture();
  return {
    ...searchFixture('complete'),
    progress: { total: 54, resolved: 54, unavailable: 2 },
    ranked: ['QUEENSTOWN', 'CLEMENTI', 'BISHAN'].map(
      (town, index): AreaResult => ({
        town,
        displayName: town.charAt(0) + town.slice(1).toLowerCase(),
        rank: index + 1,
        score: 80 - index,
        wholeFlatRent: 2800 + index * 50,
        rentPerPerson: 1400 + index * 25,
        rentP25: 2800,
        rentP75: 3400,
        rentMedianCi95Low: 2900,
        rentMedianCi95High: 3100,
        rentSampleSize: 200,
        rentQualityStatus: 'USABLE',
        averageCommute: 28,
        longestCommute: 30.01 + index,
        shortestCommute: 25,
        commuteGap: 5.01 + index,
        mostBurdenedMemberId: group.members[0]!.memberId,
        reasons: [],
        members: group.members.map((member, memberIndex) => ({
          memberId: member.memberId,
          commuteMinutes: 30.01 + index - memberIndex,
          routeStatus: 'ok',
          budgetHeadroom: 50,
          commuteHeadroom: 5,
        })),
      }),
    ),
  };
}
