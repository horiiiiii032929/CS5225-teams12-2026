import { ArrowRight, RefreshCw, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import type { GroupView } from '@flatsplit/contracts/api';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import {
  errorMessage,
  groupKey,
  searchKey,
  searchOptions,
  startSearch,
} from './api';
import type { Membership } from './membership';
import { RankedResults } from './RankedResults';
import { TownMapResults } from './TownMapResults';

export function SearchProgress({
  group,
  membership,
  groupUpdatedAt,
}: {
  group: GroupView;
  membership: Membership;
  groupUpdatedAt: number;
}) {
  const queryClient = useQueryClient();
  const [submittedSearch, setSubmittedSearch] = useState<{
    searchId: string;
    groupRevision: number;
    groupUpdatedAt: number;
  }>();
  // A successful POST is newer evidence than the group snapshot used to submit
  // it. Give its ID priority only until the next successful group refresh.
  const awaitingGroupRefresh =
    submittedSearch &&
    submittedSearch.groupRevision === group.revision &&
    groupUpdatedAt <= submittedSearch.groupUpdatedAt;
  const searchId =
    (awaitingGroupRefresh
      ? submittedSearch.searchId
      : group.latestSearch?.searchId) ??
    submittedSearch?.searchId ??
    '';
  const status = useQuery({
    ...searchOptions(membership, searchId),
    enabled: !!searchId,
  });
  const submission = useMutation({
    mutationFn: () => startSearch(membership),
    retry: false,
    onSuccess: (search) => {
      queryClient.setQueryData(searchKey(membership, search.searchId), search);
      setSubmittedSearch({
        searchId: search.searchId,
        groupRevision: search.groupRevision,
        groupUpdatedAt,
      });
      void queryClient.invalidateQueries({ queryKey: groupKey(membership) });
    },
  });
  const search = status.data;
  const stale =
    (!awaitingGroupRefresh && group.latestSearch?.status === 'stale') ||
    (search &&
      (search.status === 'stale' || search.groupRevision !== group.revision));
  const pending = !stale && search?.status === 'pending';
  const complete = !stale && search?.status === 'complete' && !status.isError;
  const routesFailed =
    complete &&
    search.progress.total > 0 &&
    search.progress.unavailable === search.progress.total;
  const ownMember = group.members.find(
    (member) => member.memberId === membership.memberId,
  );
  const placesToJoin = group.size - group.members.length;
  const preferencesToSubmit = group.members.length - group.readyCount;
  const canSearch = group.allReady && ownMember?.ready;
  return (
    <section className="surface live-search" aria-labelledby="search-heading">
      <div className="section-heading">
        <div>
          <h2 id="search-heading" tabIndex={-1}>
            Find your middle ground
          </h2>
          <p className="live-caption">
            One shortlist. Everyone’s limits respected.
          </p>
        </div>
        <Badge variant="outline">
          {status.isError || submission.isError
            ? 'Needs attention'
            : stale
              ? 'Needs a new search'
              : routesFailed
                ? 'Routes unavailable'
                : complete
                  ? 'Ready'
                  : pending
                    ? search.progress.resolved > search.progress.unavailable
                      ? 'Checking routes'
                      : 'Queued'
                    : group.allReady
                      ? 'Ready to search'
                      : 'Waiting for group'}
        </Badge>
      </div>
      <p className="live-search-principle">
        <ShieldCheck size={16} aria-hidden="true" />
        Every flatmate’s budget and commute limit is a hard requirement.
      </p>
      {!group.allReady && (
        <p role="status" className="live-waiting">
          {placesToJoin > 0
            ? `Waiting for ${placesToJoin} ${placesToJoin === 1 ? 'flatmate' : 'flatmates'} to join${preferencesToSubmit > 0 ? ` and ${preferencesToSubmit} to submit preferences` : ''}.`
            : `Waiting for ${preferencesToSubmit} ${preferencesToSubmit === 1 ? 'flatmate' : 'flatmates'} to submit preferences.`}
        </p>
      )}
      {submission.isError && (
        <Alert role="alert" variant="destructive">
          <AlertTitle>Could not start the search</AlertTitle>
          <AlertDescription>{errorMessage(submission.error)}</AlertDescription>
        </Alert>
      )}
      {searchId && status.isPending && (
        <p role="status">Loading your latest search…</p>
      )}
      {status.isError && (
        <Alert role="alert" variant="destructive">
          <AlertTitle>Could not check search progress</AlertTitle>
          <AlertDescription className="live-recovery">
            <span>{errorMessage(status.error)}</span>
            <Button
              variant="outline"
              disabled={status.isFetching}
              onClick={() => {
                void status.refetch();
              }}
            >
              Check progress again
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {stale && (
        <Alert role="status">
          <AlertTitle>Your group has changed</AlertTitle>
          <AlertDescription>
            The previous comparison is out of date. Once everyone is ready,
            start a new search using the latest preferences.
          </AlertDescription>
        </Alert>
      )}
      {pending && !status.isError && (
        <div className="live-progress-state" role="status" aria-live="polite">
          <h3>
            {search.progress.resolved === search.progress.unavailable
              ? 'Your route checks are queued.'
              : 'Checking your group’s commutes.'}
          </h3>
          <Progress
            value={
              search.progress.total
                ? (search.progress.resolved / search.progress.total) * 100
                : 0
            }
            aria-label="Commute routes checked"
          />
          <p className="live-progress-count">
            {search.progress.resolved} of {search.progress.total} routes checked
            {search.progress.unavailable
              ? ` · ${search.progress.unavailable} unavailable`
              : ''}
            .
          </p>
          <p className="live-caption">
            New routes can take a while. You can reopen this group later; your
            inputs and search are saved. Results appear when all checks finish.
          </p>
        </div>
      )}
      {complete && (
        <div className="live-complete-state">
          <h3 role="status">
            {routesFailed
              ? 'We couldn’t calculate your group’s routes.'
              : search.ranked.length
                ? `${search.ranked.length} neighbourhoods meet everyone’s limits.`
                : 'No neighbourhood meets all your current limits.'}
          </h3>
          {routesFailed && (
            <p className="live-caption">
              Your group inputs are saved. You can retry without re-entering
              anyone’s preferences.
            </p>
          )}
          <RankedResults
            key={`${search.searchId}:${search.groupRevision}`}
            search={search}
            group={group}
            checkedAt={status.dataUpdatedAt}
          />
          {search.ranked.length > 0 && (
            <TownMapResults search={search} group={group} />
          )}
          {search.progress.unavailable > 0 && (
            <Alert>
              <AlertTitle>
                {routesFailed
                  ? 'All routes were unavailable'
                  : 'Some routes were unavailable'}
              </AlertTitle>
              <AlertDescription>
                {search.progress.unavailable}{' '}
                {search.progress.unavailable === 1
                  ? 'route could'
                  : 'routes could'}{' '}
                not be calculated. Affected towns are excluded. Search again to
                retry when the service allows; unknown times are never treated
                as zero.
              </AlertDescription>
            </Alert>
          )}
          {!search.ranked.length && !routesFailed && (
            <p>
              Review the group’s budgets and commute limits together before
              changing any preference. Missing or low-confidence rent and
              unavailable routes also exclude towns.
            </p>
          )}
        </div>
      )}
      <div className="live-search-actions">
        {!status.isError && (
          <Button
            disabled={!canSearch || submission.isPending || !!pending}
            onClick={() => submission.mutate()}
          >
            {submission.isPending
              ? 'Submitting search…'
              : pending
                ? 'Search in progress'
                : stale
                  ? 'Search latest preferences'
                  : routesFailed
                    ? 'Retry route calculations'
                    : search
                      ? 'Search again'
                      : 'Find our neighbourhoods'}
            {!pending && <ArrowRight data-icon="inline-end" />}
          </Button>
        )}
        {pending && !status.isError && (
          <Button
            variant="outline"
            disabled={status.isFetching}
            onClick={() => {
              void status.refetch();
            }}
          >
            <RefreshCw size={14} aria-hidden="true" />
            {status.isFetching ? 'Checking…' : 'Check progress now'}
          </Button>
        )}
      </div>
    </section>
  );
}
