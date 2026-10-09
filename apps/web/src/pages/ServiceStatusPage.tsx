import { Link } from '@tanstack/react-router';
import { Button } from '@/components/ui/button';
import { useQuery } from '@tanstack/react-query';
import { healthQueryOptions } from '../lib/health';

export function ServiceStatusPage() {
  const health = useQuery(healthQueryOptions);

  return (
    <main id="main-content" className="status-shell surface">
      <Link to="/" search={{ review: 'create' }}>
        ← Back to FlatSplit
      </Link>
      <p className="eyebrow">Scaffold verification</p>
      <h1>Service status</h1>
      <div aria-live="polite" role="status">
        {health.isPending && <p>Connecting to the Python API…</p>}
        {health.isError && (
          <p>
            The API is unavailable. Start it with <code>pnpm dev:api</code>,
            then refresh.
          </p>
        )}
        {health.isSuccess && (
          <p>
            <strong>API connected.</strong> {health.data.service} returned{' '}
            <code>{health.data.status}</code>.
          </p>
        )}
      </div>
      <Button
        type="button"
        disabled={health.isFetching}
        onClick={() => void health.refetch()}
      >
        {health.isFetching ? 'Checking…' : 'Refresh status'}
      </Button>
    </main>
  );
}
