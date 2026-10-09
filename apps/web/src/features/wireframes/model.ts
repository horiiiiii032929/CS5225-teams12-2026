export const previews = [
  'create',
  'group',
  'join',
  'preferences',
  'processing',
  'results',
  'empty',
  'partial',
  'failure',
] as const;
export type Preview = (typeof previews)[number];

export const destinations = [
  {
    id: 'nus',
    label: 'National University of Singapore',
    short: 'NUS · Kent Ridge',
  },
  { id: 'one-north', label: 'one-north', short: 'one-north' },
  { id: 'raffles', label: 'Raffles Place', short: 'Raffles Place' },
  {
    id: 'ntu',
    label: 'Nanyang Technological University',
    short: 'NTU · Pioneer',
  },
  { id: 'tampines', label: 'Tampines Central', short: 'Tampines Central' },
] as const;
export type Destination = (typeof destinations)[number]['id'];
export type Member = {
  id: string;
  name: string;
  destination: Destination;
  budget: number;
  maxCommute: number;
  ready: boolean;
};
export type Group = { name: string; size: number; members: Member[] };
export type Priority = 'balanced' | 'fairness' | 'budget';
export type Stage =
  'create' | 'group' | 'preferences' | 'processing' | 'results';
export type Scenario = 'normal' | 'partial' | 'failure';
export type Area = {
  id: string;
  name: string;
  description: string;
  rent: number;
  commutes: Record<Destination, number>;
};
// Fictional teaching fixtures, not HDB rental or transport observations.
export const areas: Area[] = [
  {
    id: 'queenstown',
    name: 'Queenstown',
    description: 'A shared middle ground',
    rent: 3600,
    commutes: { nus: 22, 'one-north': 18, raffles: 27, ntu: 55, tampines: 50 },
  },
  {
    id: 'clementi',
    name: 'Clementi',
    description: 'More room in your budget',
    rent: 3300,
    commutes: { nus: 12, 'one-north': 22, raffles: 42, ntu: 40, tampines: 65 },
  },
  {
    id: 'bukit-merah',
    name: 'Bukit Merah',
    description: 'Closer to the city',
    rent: 3900,
    commutes: { nus: 33, 'one-north': 27, raffles: 17, ntu: 65, tampines: 48 },
  },
  {
    id: 'jurong-east',
    name: 'Jurong East',
    description: 'A west-side connection',
    rent: 3000,
    commutes: { nus: 30, 'one-north': 38, raffles: 55, ntu: 25, tampines: 75 },
  },
  {
    id: 'bishan',
    name: 'Bishan',
    description: 'Connected across the island',
    rent: 3750,
    commutes: { nus: 45, 'one-north': 35, raffles: 27, ntu: 70, tampines: 42 },
  },
  {
    id: 'toa-payoh',
    name: 'Toa Payoh',
    description: 'An established central base',
    rent: 3450,
    commutes: { nus: 38, 'one-north': 30, raffles: 23, ntu: 68, tampines: 43 },
  },
];
export const priorities: Record<
  Priority,
  { label: string; weights: [number, number, number]; explanation: string }
> = {
  balanced: {
    label: 'Balanced',
    weights: [0.35, 0.35, 0.3],
    explanation: '35% rent, 35% average commute, 30% commute gap.',
  },
  fairness: {
    label: 'Fairer commutes',
    weights: [0.2, 0.25, 0.55],
    explanation: '20% rent, 25% average commute, 55% commute gap.',
  },
  budget: {
    label: 'Lower rent',
    weights: [0.7, 0.2, 0.1],
    explanation: '70% rent, 20% average commute, 10% commute gap.',
  },
};
export function sampleGroup(): Group {
  return {
    name: 'Our next chapter',
    size: 3,
    members: [
      {
        id: '1',
        name: 'Alex',
        destination: 'nus',
        budget: 1400,
        maxCommute: 45,
        ready: true,
      },
      {
        id: '2',
        name: 'Jamie',
        destination: 'one-north',
        budget: 1300,
        maxCommute: 45,
        ready: true,
      },
      {
        id: '3',
        name: 'Sam',
        destination: 'raffles',
        budget: 1400,
        maxCommute: 45,
        ready: true,
      },
    ],
  };
}
export function validMember(member: Member): boolean {
  return (
    member.name.trim().length > 0 &&
    member.name.trim().length <= 30 &&
    destinations.some((d) => d.id === member.destination) &&
    Number.isFinite(member.budget) &&
    member.budget >= 300 &&
    member.budget <= 5000 &&
    Number.isFinite(member.maxCommute) &&
    Number.isInteger(member.maxCommute) &&
    member.maxCommute >= 10 &&
    member.maxCommute <= 120
  );
}
export function groupReady(group: Group): boolean {
  return (
    Number.isInteger(group.size) &&
    group.size >= 2 &&
    group.size <= 5 &&
    group.members.length === group.size &&
    new Set(group.members.map((m) => m.id)).size === group.size &&
    group.members.every((m) => m.ready && validMember(m))
  );
}
export function evaluateAreas(
  group: Group,
  priority: Priority,
  scenario: Scenario = 'normal',
) {
  if (!groupReady(group)) return [];
  const [rentWeight, timeWeight, gapWeight] = priorities[priority].weights;
  return areas
    .map((area) => {
      const perPerson = area.rent / group.size;
      const times = group.members.map((m) => area.commutes[m.destination]);
      const average = times.reduce((a, b) => a + b, 0) / times.length;
      const longest = Math.max(...times);
      const gap = longest - Math.min(...times);
      const unavailable = scenario === 'partial' && area.id === 'queenstown';
      const reasons = group.members.flatMap((member, index) => [
        ...(perPerson > member.budget
          ? [
              `Over ${member.name}’s budget by ${money(perPerson - member.budget)}/month`,
            ]
          : []),
        ...(times[index]! > member.maxCommute
          ? [
              `${member.name}’s commute exceeds their limit by ${times[index]! - member.maxCommute} min`,
            ]
          : []),
      ]);
      if (unavailable) reasons.push('A route estimate is unavailable');
      // Fixed scales make priority changes comparable. This is a proposed demo formula.
      const cost =
        rentWeight * (perPerson / 2000) +
        timeWeight * (average / 90) +
        gapWeight * (gap / 90);
      return {
        ...area,
        perPerson,
        times,
        average,
        longest,
        gap,
        reasons,
        feasible: reasons.length === 0,
        score: Math.max(0, Math.round((1 - cost) * 100)),
      };
    })
    .sort(
      (a, b) =>
        Number(b.feasible) - Number(a.feasible) ||
        b.score - a.score ||
        a.name.localeCompare(b.name),
    );
}
export type RankedArea = ReturnType<typeof evaluateAreas>[number];
export function money(value: number) {
  return `S$${Math.ceil(value).toLocaleString('en-SG')}`;
}
