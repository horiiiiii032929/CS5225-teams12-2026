export function formatCommuteMinutes(value: number | null) {
  return value === null ? 'Unavailable' : `${Math.ceil(value)} min`;
}
