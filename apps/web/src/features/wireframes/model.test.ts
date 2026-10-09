import { describe, expect, it } from 'vitest';
import {
  areas,
  evaluateAreas,
  groupReady,
  money,
  sampleGroup,
  validMember,
  type Priority,
} from './model';

describe('group readiness', () => {
  it('requires every invited member to submit', () => {
    const group = sampleGroup();
    expect(groupReady(group)).toBe(true);
    group.members[2]!.ready = false;
    expect(groupReady(group)).toBe(false);
    expect(evaluateAreas(group, 'balanced')).toEqual([]);
  });
  it.each([1, 6, 2.5])('rejects unsupported group size %s', (size) => {
    expect(groupReady({ ...sampleGroup(), size })).toBe(false);
  });
  it('rejects a missing or duplicated member', () => {
    const group = sampleGroup();
    group.members.pop();
    expect(groupReady(group)).toBe(false);
    group.members.push(group.members[0]!);
    expect(groupReady(group)).toBe(false);
  });
  it.each([NaN, Infinity, 0, 299, 5001])(
    'rejects invalid budget %s',
    (budget) => {
      expect(validMember({ ...sampleGroup().members[0]!, budget })).toBe(false);
    },
  );
  it.each([NaN, Infinity, 0, 9, 120.5, 121])(
    'rejects invalid commute %s',
    (maxCommute) => {
      expect(validMember({ ...sampleGroup().members[0]!, maxCommute })).toBe(
        false,
      );
    },
  );
  it('rejects blank and overlong names', () => {
    expect(validMember({ ...sampleGroup().members[0]!, name: '  ' })).toBe(
      false,
    );
    expect(
      validMember({ ...sampleGroup().members[0]!, name: 'a'.repeat(31) }),
    ).toBe(false);
  });
});

describe('explainable recommendations', () => {
  it('computes a transparent equal split and per-member fairness comparison', () => {
    const queenstown = evaluateAreas(sampleGroup(), 'balanced').find(
      (a) => a.id === 'queenstown',
    )!;
    expect(queenstown.perPerson).toBe(1200);
    expect(queenstown.times).toEqual([22, 18, 27]);
    expect(queenstown.average).toBeCloseTo(22.3333);
    expect(queenstown.longest).toBe(27);
    expect(queenstown.gap).toBe(9);
  });
  it('checks individual budgets, not only the group total', () => {
    const group = sampleGroup();
    group.members[0]!.budget = 900;
    group.members[1]!.budget = 3000;
    expect(evaluateAreas(group, 'balanced').every((a) => !a.feasible)).toBe(
      true,
    );
  });
  it('never hides one person exceeding their commute limit in the average', () => {
    const area = evaluateAreas(sampleGroup(), 'balanced').find(
      (a) => a.id === 'jurong-east',
    )!;
    expect(area.average).toBeLessThan(45);
    expect(area.feasible).toBe(false);
    expect(area.reasons).toContain(
      'Sam’s commute exceeds their limit by 10 min',
    );
  });
  it('accepts a budget or commute exactly on the limit', () => {
    const group = sampleGroup();
    group.members.forEach((m) => {
      m.budget = 1200;
    });
    group.members[2]!.maxCommute = 27;
    expect(
      evaluateAreas(group, 'balanced').find((a) => a.id === 'queenstown')!
        .feasible,
    ).toBe(true);
  });
  it('changes the first recommendation when the group prioritises rent', () => {
    expect(evaluateAreas(sampleGroup(), 'balanced')[0]!.id).toBe('queenstown');
    expect(evaluateAreas(sampleGroup(), 'fairness')[0]!.id).toBe('queenstown');
    expect(evaluateAreas(sampleGroup(), 'budget')[0]!.id).toBe('clementi');
  });
  it('never relaxes hard constraints when priorities change', () => {
    const sets = (['balanced', 'fairness', 'budget'] as Priority[]).map((p) =>
      evaluateAreas(sampleGroup(), p)
        .filter((a) => a.feasible)
        .map((a) => a.id)
        .sort(),
    );
    expect(sets[0]).toEqual(sets[1]);
    expect(sets[1]).toEqual(sets[2]);
  });
  it('excludes missing estimates and restores them on a successful retry', () => {
    expect(
      evaluateAreas(sampleGroup(), 'balanced', 'partial').find(
        (a) => a.id === 'queenstown',
      )!.feasible,
    ).toBe(false);
    expect(
      evaluateAreas(sampleGroup(), 'balanced', 'normal').find(
        (a) => a.id === 'queenstown',
      )!.feasible,
    ).toBe(true);
  });
  it('returns honest exclusions when nobody has a match', () => {
    const group = sampleGroup();
    group.members.forEach((m) => {
      m.maxCommute = 10;
    });
    const result = evaluateAreas(group, 'balanced');
    expect(result).toHaveLength(areas.length);
    expect(result.every((a) => !a.feasible && a.reasons.length > 0)).toBe(true);
  });
  it.each([2, 5])('uses the actual group size %s in the rent split', (size) => {
    const group = sampleGroup();
    group.size = size;
    group.members = Array.from({ length: size }, (_, i) => ({
      ...group.members[i % 3]!,
      id: String(i),
      budget: 5000,
      maxCommute: 120,
    }));
    expect(groupReady(group)).toBe(true);
    expect(
      evaluateAreas(group, 'balanced').find((a) => a.id === 'queenstown')!
        .perPerson,
    ).toBe(3600 / size);
  });
  it('does not mutate member preferences while ranking', () => {
    const group = sampleGroup();
    const before = structuredClone(group);
    evaluateAreas(group, 'budget');
    expect(group).toEqual(before);
  });
  it('rounds displayed estimates up to avoid understating rent', () => {
    expect(money(1000.1)).toBe('S$1,001');
  });
});
