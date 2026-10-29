import type { AreaResult } from '@flatsplit/contracts/api';
import referencePoints from './town-reference-points.json';

// Public projection of the versioned principal-station reference in
// services/api/src/flatsplit_api/towns.json; offline evidence tests guard drift.
export const points: Readonly<
  Record<string, { stationName: string; lat: number; lon: number }>
> = referencePoints;
export const WIDTH = 680;
export const HEIGHT = 400;
const PAD = 42;
const bounds = { west: 103.68, east: 104.01, south: 1.245, north: 1.465 };
export function position(point: { lat: number; lon: number }) {
  return {
    x:
      PAD +
      ((point.lon - bounds.west) / (bounds.east - bounds.west)) *
        (WIDTH - PAD * 2),
    y:
      PAD +
      ((bounds.north - point.lat) / (bounds.north - bounds.south)) *
        (HEIGHT - PAD * 2),
  };
}

// Separate touch targets without moving the actual reference point. Leader
// lines retain geography when nearby recommendations need their pins offset.
export function mapMarkers(areas: readonly AreaResult[]) {
  const placed: { x: number; y: number }[] = [];
  return areas.flatMap((area) => {
    const point = points[area.town];
    if (!point) return [];
    const anchor = position(point);
    const candidates = [anchor];
    for (let y = PAD; y <= HEIGHT - PAD; y += 48) {
      for (let x = PAD; x <= WIDTH - PAD; x += 48) candidates.push({ x, y });
    }
    candidates.sort(
      (a, b) =>
        Math.hypot(a.x - anchor.x, a.y - anchor.y) -
        Math.hypot(b.x - anchor.x, b.y - anchor.y),
    );
    const marker = candidates.find((candidate) =>
      placed.every(
        (other) =>
          Math.hypot(other.x - candidate.x, other.y - candidate.y) >= 48,
      ),
    );
    // At most 26 verified towns share 91 grid slots. If a future inventory
    // exhausts those slots, retain the accessible list rather than overlap pins.
    if (!marker) return [];
    placed.push(marker);
    return [{ area, point, anchor, marker }];
  });
}
