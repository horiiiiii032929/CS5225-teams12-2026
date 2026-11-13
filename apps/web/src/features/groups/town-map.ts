import type { AreaResult } from '@flatsplit/contracts/api';
import referencePoints from './town-reference-points.json';

// Public projection of the versioned principal-station reference in
// services/api/src/flatsplit_api/towns.json; offline evidence tests guard drift.
export const points: Readonly<
  Record<string, { stationName: string; lat: number; lon: number }>
> = referencePoints;
export const WIDTH = 680;
export const HEIGHT = 425;
const PAD = 42;
const PIN_SPACING = 72;
// The bundled coastline and rail paths use this same projection.
const bounds = { west: 103.6, east: 104.04, south: 1.215, north: 1.49 };
export function position(point: { lat: number; lon: number }) {
  return {
    x: ((point.lon - bounds.west) / (bounds.east - bounds.west)) * WIDTH,
    y: ((bounds.north - point.lat) / (bounds.north - bounds.south)) * HEIGHT,
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
    for (let y = PAD; y <= HEIGHT - PAD; y += PIN_SPACING) {
      for (let x = PAD; x <= WIDTH - PAD; x += PIN_SPACING)
        candidates.push({ x, y });
    }
    candidates.sort(
      (a, b) =>
        Math.hypot(a.x - anchor.x, a.y - anchor.y) -
        Math.hypot(b.x - anchor.x, b.y - anchor.y),
    );
    const marker = candidates.find((candidate) =>
      placed.every(
        (other) =>
          Math.hypot(other.x - candidate.x, other.y - candidate.y) >=
          PIN_SPACING,
      ),
    );
    // A town without a marker remains available in the selector.
    if (!marker) return [];
    placed.push(marker);
    return [{ area, point, anchor, marker }];
  });
}
