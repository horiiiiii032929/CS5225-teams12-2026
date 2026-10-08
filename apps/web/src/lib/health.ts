import { healthResponseSchema } from '@flatsplit/contracts/health';
import { queryOptions } from '@tanstack/react-query';

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(
  /\/$/,
  '',
);

export const healthQueryOptions = queryOptions({
  queryKey: ['api', 'health'],
  queryFn: async ({ signal }) => {
    const response = await fetch(`${apiBaseUrl}/health`, { signal });
    if (!response.ok) {
      throw new Error(`Health request failed (${response.status}).`);
    }
    return healthResponseSchema.parse(await response.json());
  },
  retry: false,
});
