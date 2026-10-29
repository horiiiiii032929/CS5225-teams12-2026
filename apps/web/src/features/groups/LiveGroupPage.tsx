import { useState } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Check, Link2, RefreshCw, UserRoundPlus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Field, FieldLabel, FieldDescription } from '@/components/ui/field';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { GroupShell } from './GroupShell';
import { MemberPreferencesForm } from './MemberPreferencesForm';
import { SearchProgress } from './SearchProgress';
import { errorMessage, groupOptions } from './api';
import {
  inviteLink,
  membershipIsPersisted,
  readMembership,
  validId,
  type Membership,
} from './membership';

export function LiveGroupPage({ groupId }: { groupId: string }) {
  const membership = readMembership(groupId);
  if (!membership)
    return (
      <GroupShell>
        <section className="surface live-join">
          <h1>
            {validId(groupId)
              ? 'Reopen your shared group.'
              : 'This group link is invalid.'}
          </h1>
          <p>
            You need the membership saved in the browser where you created or
            joined this group. Otherwise, ask the organiser for the original
            invite link to join if there is space.
          </p>
          <Link to="/" search={{}} className="underline">
            Return home
          </Link>
        </section>
      </GroupShell>
    );
  return <MemberGroup membership={membership} />;
}
function MemberGroup({ membership }: { membership: Membership }) {
  const group = useQuery(groupOptions(membership));
  const [copyStatus, setCopyStatus] = useState('');
  const [editingPreferences, setEditingPreferences] = useState(false);
  const link = inviteLink(membership);
  const data = group.data;
  const ownMember = data?.members.find(
    (member) => member.memberId === membership.memberId,
  );
  // Auth/expiry errors must not continue to show previously cached member data.
  const blocked =
    group.isError &&
    (!data ||
      ('status' in group.error &&
        [401, 403, 404].includes(Number(group.error.status))));
  return (
    <GroupShell>
      {!membershipIsPersisted(membership) && (
        <Alert role="alert">
          <AlertTitle>Keep this tab open</AlertTitle>
          <AlertDescription>
            This browser could not save your membership. Refreshing or closing
            the tab may lose your access. Allow browser storage before creating
            or joining another group.
          </AlertDescription>
        </Alert>
      )}
      {group.isPending && (
        <section className="surface live-opening" role="status">
          <h1>Opening your group…</h1>
          <p>Bringing your flatmates and saved preferences together.</p>
          <div className="live-loading-line" aria-hidden="true" />
        </section>
      )}
      {group.isError && (
        <section className={blocked ? 'surface live-join' : 'live-group-error'}>
          {blocked && <h1>We couldn’t open your group.</h1>}
          <Alert role="alert" variant="destructive">
            <AlertTitle>Could not refresh your group</AlertTitle>
            <AlertDescription className="live-recovery">
              <span>{errorMessage(group.error)}</span>
              <Button
                variant="outline"
                disabled={group.isFetching}
                onClick={() => {
                  void group.refetch();
                }}
              >
                Try opening again
              </Button>
            </AlertDescription>
          </Alert>
          {blocked && (
            <Link to="/" search={{}} className="text-link live-return-link">
              Return home
            </Link>
          )}
        </section>
      )}
      {data && !blocked && (
        <>
          <div className="page-heading live-group-heading">
            <div>
              <h1>{data.groupName}</h1>
              <p className="lead">
                {data.allReady
                  ? 'Everyone’s ready. Find a neighbourhood that works for you all.'
                  : 'Bring everyone’s budget and commute into one shared search.'}
              </p>
            </div>
            <div className="live-heading-actions">
              {link && data.members.length < data.size && (
                <a href="#invite-heading" className="text-link">
                  Invite flatmates
                </a>
              )}
              <a href="#search-heading" className="text-link">
                {data.allReady ? 'Go to your search' : 'View search readiness'}
              </a>
            </div>
          </div>
          <div className="live-group-layout">
            <section
              className="surface live-members"
              aria-labelledby="flatmates-heading"
            >
              <div className="section-heading">
                <div>
                  <h2 id="flatmates-heading">Your flatmates</h2>
                  <p className="live-caption">
                    {data.members.length} joined · {data.size} places in your
                    group
                  </p>
                </div>
                <Badge variant={data.allReady ? 'secondary' : 'outline'}>
                  {data.readyCount} of {data.size} ready
                </Badge>
              </div>
              <ul className="member-list">
                {data.members.map((member, index) => (
                  <li className="member-row" key={member.memberId}>
                    <div
                      className={`person-avatar member-color-${index}`}
                      aria-hidden="true"
                    >
                      {member.name.slice(0, 1).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="live-member-name">
                        <h3>{member.name}</h3>
                        <span>
                          {member.memberId === membership.memberId ? 'You' : ''}
                          {member.isOrganiser
                            ? `${member.memberId === membership.memberId ? ' · ' : ''}Organiser`
                            : ''}
                        </span>
                      </div>
                      {member.ready && member.destination ? (
                        <div className="live-member-preferences">
                          <p>{member.destination.label}</p>
                          <p>
                            S${member.budget?.toLocaleString('en-SG')}/month{' '}
                            <span aria-hidden="true">·</span> up to{' '}
                            {member.maxCommute} min
                          </p>
                        </div>
                      ) : (
                        <p>Preferences not submitted yet</p>
                      )}
                    </div>
                    <Badge variant={member.ready ? 'secondary' : 'outline'}>
                      {member.ready && <Check size={12} aria-hidden="true" />}
                      {member.ready ? 'Ready' : 'Waiting'}
                    </Badge>
                  </li>
                ))}
                {Array.from(
                  { length: Math.max(0, data.size - data.members.length) },
                  (_, index) => (
                    <li className="live-open-place" key={`open-${index}`}>
                      <span className="live-empty-avatar">
                        <UserRoundPlus size={16} aria-hidden="true" />
                      </span>
                      <span>
                        Room for another flatmate<span>Waiting to join</span>
                      </span>
                    </li>
                  ),
                )}
              </ul>
              {ownMember && !editingPreferences && (
                <Button
                  variant="outline"
                  onClick={() => setEditingPreferences(true)}
                >
                  {ownMember.ready
                    ? 'Edit your preferences'
                    : 'Add your preferences'}
                </Button>
              )}
              {ownMember && editingPreferences && (
                <MemberPreferencesForm
                  membership={membership}
                  member={ownMember}
                  onSaved={() => setEditingPreferences(false)}
                  onCancel={() => setEditingPreferences(false)}
                />
              )}
              <div className="live-members-footer">
                <span className="live-caption">Updates automatically</span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={group.isFetching}
                  onClick={() => {
                    void group.refetch();
                  }}
                >
                  <RefreshCw size={14} aria-hidden="true" />
                  {group.isFetching ? 'Refreshing…' : 'Refresh group'}
                </Button>
              </div>
            </section>
            {!group.isError && (
              <SearchProgress
                group={data}
                membership={membership}
                groupUpdatedAt={group.dataUpdatedAt}
              />
            )}
            <aside
              className="surface live-invite"
              aria-labelledby="invite-heading"
            >
              <div>
                <Link2 size={22} className="text-primary" aria-hidden="true" />
                <h2 id="invite-heading" tabIndex={-1}>
                  A home search to share.
                </h2>
                <p className="live-caption">
                  {data.members.length < data.size
                    ? 'Bring the rest of your group along.'
                    : 'Everyone has joined your group.'}
                </p>
              </div>
              {link ? (
                <>
                  <Field>
                    <FieldLabel htmlFor="invite-link">
                      Your group’s invite link
                    </FieldLabel>
                    <Input
                      id="invite-link"
                      readOnly
                      value={link}
                      onFocus={(event) => event.currentTarget.select()}
                      aria-describedby="invite-help"
                    />
                    <FieldDescription id="invite-help">
                      Share privately. Anyone with this link can join while
                      there is space.
                    </FieldDescription>
                  </Field>
                  <div>
                    <Button
                      variant="secondary"
                      className="w-full"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(link);
                          setCopyStatus('Invite link copied.');
                        } catch {
                          setCopyStatus(
                            'Copy was unavailable. Select the invite link above and copy it manually.',
                          );
                        }
                      }}
                    >
                      {copyStatus === 'Invite link copied.' ? (
                        <Check data-icon="inline-start" />
                      ) : (
                        <Link2 data-icon="inline-start" />
                      )}
                      Copy invite link
                    </Button>
                    <p role="status" className="live-copy-status">
                      {copyStatus}
                    </p>
                  </div>
                </>
              ) : (
                <p className="live-caption">
                  The organiser keeps the original invite link. Ask them to
                  share it with anyone who still needs to join.
                </p>
              )}
              <details className="live-access-details">
                <summary>Keeping your group access</summary>
                <p>
                  Use this same browser to reopen your membership. There is no
                  account login or token recovery; if the group is full, lost
                  membership cannot be replaced.
                </p>
                <p>
                  Only your own membership can save your preferences. This group
                  expires{' '}
                  {new Date(data.expiresAt).toLocaleDateString('en-SG', {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                  })}
                  .
                </p>
              </details>
            </aside>
          </div>
        </>
      )}
    </GroupShell>
  );
}

export function GroupRoutePage() {
  const { groupId } = useParams({ from: '/groups/$groupId' });
  return <LiveGroupPage key={groupId} groupId={groupId} />;
}
