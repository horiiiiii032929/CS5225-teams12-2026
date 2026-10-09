import { useState } from 'react';
import {
  ArrowLeftRight,
  ArrowRight,
  Check,
  ChevronDown,
  Clock3,
  Info,
  Scale,
  SlidersHorizontal,
  TrainFront,
  TriangleAlert,
  Wallet,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
  EmptyMedia,
} from '@/components/ui/empty';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { useDialogState } from '@/lib/use-dialog-state';
import {
  destinations,
  evaluateAreas,
  money,
  priorities,
  type Group,
  type Priority,
  type RankedArea,
  type Scenario,
} from './model';

function Commutes({ area, group }: { area: RankedArea; group: Group }) {
  return (
    <div className="flex flex-col gap-4">
      {group.members.map((member, index) => (
        <div className="commute-detail" key={member.id}>
          <div className="flex items-center justify-between gap-3">
            <span>
              <span className={`member-dot member-color-${index}`} />
              {member.name}{' '}
              <span className="muted">
                → {destinations.find((d) => d.id === member.destination)?.short}
              </span>
            </span>
            <strong>{area.times[index]} min</strong>
          </div>
          <div className="bar-track">
            <div
              className={`member-color-${index}`}
              style={{
                width: `${Math.min(100, (area.times[index]! / member.maxCommute) * 100)}%`,
              }}
            />
          </div>
          <p>
            Limit {member.maxCommute} min ·{' '}
            {member.maxCommute - area.times[index]!} min to spare
          </p>
        </div>
      ))}
    </div>
  );
}

export function ResultsView({
  group,
  scenario,
  onEdit,
  onRetry,
}: {
  group: Group;
  scenario: Scenario;
  onEdit: () => void;
  onRetry: () => void;
}) {
  const [priority, setPriority] = useState<Priority>('balanced');
  const [selected, setSelected] = useState<string[]>([]);
  const {
    open: compare,
    onOpenChange: setCompare,
    restoreFocus: restoreCompareFocus,
  } = useDialogState();
  const {
    open: method,
    onOpenChange: setMethod,
    restoreFocus: restoreMethodFocus,
  } = useDialogState();
  const [expanded, setExpanded] = useState<string | null>('queenstown');
  const ranked = evaluateAreas(group, priority, scenario);
  const feasible = ranked.filter((a) => a.feasible);
  const excluded = ranked.filter((a) => !a.feasible);
  const first = feasible[0];
  const comparison = ranked.filter(
    (a) => a.feasible && selected.includes(a.id),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Find your common ground.</h1>
          <p className="lead">
            Different routines. A shortlist that brings you together.
          </p>
        </div>
        <Button variant="outline" onClick={onEdit}>
          <SlidersHorizontal data-icon="inline-start" /> Edit preferences
        </Button>
      </div>
      {scenario === 'partial' && (
        <Alert className="mb-6">
          <TriangleAlert />
          <AlertTitle>One area needs another look</AlertTitle>
          <AlertDescription>
            <p>
              Queenstown has a missing route estimate and is excluded. The other
              areas have complete sample estimates.
            </p>
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry missing route
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <div className="results-layout">
        <div className="min-w-0">
          <div className="ranking-toolbar">
            <div>
              <h2>
                Your shortlist{' '}
                <span className="muted">/ {feasible.length} areas</span>
              </h2>
              <p>All included areas meet every flatmate’s limits.</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={comparison.length < 2}
              onClick={() => setCompare(true)}
            >
              <ArrowLeftRight data-icon="inline-start" /> Compare (
              {comparison.length}/3)
            </Button>
          </div>
          <div className="priority-row">
            <span>Prioritise</span>
            <ToggleGroup
              type="single"
              value={priority}
              onValueChange={(v) => {
                if (v) setPriority(v as Priority);
              }}
              variant="outline"
              aria-label="Ranking priority"
            >
              {(
                Object.entries(priorities) as [
                  Priority,
                  (typeof priorities)[Priority],
                ][]
              ).map(([id, p]) => (
                <ToggleGroupItem key={id} value={id}>
                  {p.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <p className="ranking-caption" aria-live="polite">
            {priorities[priority].explanation}{' '}
            <button className="text-link" onClick={() => setMethod(true)}>
              How ranking works <Info size={13} />
            </button>
          </p>
          {!first && (
            <Empty className="surface my-5">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <SlidersHorizontal />
                </EmptyMedia>
                <EmptyTitle>No area meets everyone’s limits yet.</EmptyTitle>
                <EmptyDescription>
                  We haven’t quietly stretched anyone’s budget or commute.
                  Review the reasons below, then decide together what can
                  change.
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button onClick={onEdit}>
                  Review our preferences <ArrowRight data-icon="inline-end" />
                </Button>
              </EmptyContent>
            </Empty>
          )}
          <div className="ranked-list">
            {feasible.map((area, index) => (
              <article
                className={cn(
                  'result-card',
                  index === 0 && 'result-card-featured',
                )}
                key={area.id}
              >
                {index === 0 && (
                  <div className="recommendation-label">
                    <Scale size={15} />
                    <span>Best fit for your group</span>
                    <span>{priorities[priority].label}</span>
                  </div>
                )}
                <div className="result-body">
                  <div className="result-top">
                    <span className="rank-number">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <div className="flex-1">
                      <h3>{area.name}</h3>
                      <p className="muted">{area.description}</p>
                    </div>
                    <label className="compare-check">
                      <input
                        type="checkbox"
                        checked={selected.includes(area.id)}
                        disabled={
                          !selected.includes(area.id) && selected.length >= 3
                        }
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, area.id]
                              : selected.filter((id) => id !== area.id),
                          )
                        }
                        aria-label={`Compare ${area.name}`}
                      />
                      <span>Compare</span>
                    </label>
                  </div>
                  <div className="area-metrics">
                    <div>
                      <span>
                        <Wallet size={14} /> Rent / person
                      </span>
                      <strong>
                        {money(area.perPerson)}
                        <small> / mo</small>
                      </strong>
                    </div>
                    <div>
                      <span>
                        <TrainFront size={14} /> Avg. commute
                      </span>
                      <strong>
                        {Math.round(area.average)}
                        <small> min</small>
                      </strong>
                    </div>
                    <div>
                      <span>
                        <Scale size={14} /> Commute gap
                      </span>
                      <strong>
                        {area.gap}
                        <small> min</small>
                      </strong>
                    </div>
                  </div>
                  <div className="result-footer">
                    <span>
                      <Check size={15} /> Within all {group.size} members’
                      limits
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-expanded={expanded === area.id}
                      aria-controls={`commutes-${area.id}`}
                      onClick={() =>
                        setExpanded(expanded === area.id ? null : area.id)
                      }
                    >
                      Everyone’s commute{' '}
                      <ChevronDown
                        data-icon="inline-end"
                        className={cn(expanded === area.id && 'rotate-180')}
                      />
                    </Button>
                  </div>
                  {expanded === area.id && (
                    <div
                      id={`commutes-${area.id}`}
                      className="commute-expanded"
                    >
                      <Commutes area={area} group={group} />
                      <div className="explanation-note">
                        <Info size={16} />
                        <p>
                          The longest journey is{' '}
                          <strong>{area.longest} minutes</strong>. The gap
                          between the shortest and longest is{' '}
                          <strong>{area.gap} minutes</strong>.{' '}
                          {money(area.rent)} whole-flat rent is split equally
                          across {group.size} people.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
          {excluded.length > 0 && (
            <details className="excluded-areas" open={!first}>
              <summary>
                {excluded.length}{' '}
                {excluded.length === 1 ? 'area does' : 'areas do'} not meet all
                requirements <ChevronDown size={16} />
              </summary>
              <div className="flex flex-col gap-5 pt-5">
                {excluded.map((area) => (
                  <div key={area.id}>
                    <h3>{area.name}</h3>
                    <ul>
                      {area.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </details>
          )}
          <p className="fine-print mt-5">
            Fictional estimates for design review. Town-level suggestions, not
            available properties.
          </p>
        </div>
        <aside className="results-aside">
          <section className="group-summary">
            <div className="section-heading">
              <h2>Your people</h2>
              <UsersStack count={group.size} />
            </div>
            {group.members.map((member, i) => (
              <div className="summary-member" key={member.id}>
                <span className={`person-avatar member-color-${i}`}>
                  {member.name.slice(0, 1)}
                </span>
                <div>
                  <strong>{member.name}</strong>
                  <p>
                    {
                      destinations.find((d) => d.id === member.destination)
                        ?.short
                    }
                  </p>
                  <span>
                    {money(member.budget)}/mo · ≤ {member.maxCommute} min
                  </span>
                </div>
              </div>
            ))}
            <Separator />
            <div className="summary-bottom">
              <span>Shared rent ceiling</span>
              <strong>
                {money(
                  Math.min(...group.members.map((m) => m.budget)) * group.size,
                )}
                <small> / mo</small>
              </strong>
              <p>Based on the lowest individual budget and an equal split.</p>
            </div>
          </section>
          {first && (
            <section className="fairness-note">
              <div className="flex items-center gap-2">
                <Scale size={20} />
                <h2>Fair looks good on you.</h2>
              </div>
              <p>
                In {first.name}, nobody travels more than{' '}
                <strong>{first.gap} minutes longer</strong> than another
                flatmate.
              </p>
              <div className="fairness-number">
                {first.longest}
                <span>
                  min
                  <br />
                  longest commute
                </span>
              </div>
              <p className="text-sm">
                A short average is only part of the story.
              </p>
            </section>
          )}
          <section className="data-note">
            <Clock3 size={17} />
            <div>
              <h3>Know what’s behind the numbers</h3>
              <p>
                All rents and routes here are invented fixtures. The live
                service will show rental periods, sample sizes, and route
                freshness.
              </p>
              <button
                className="text-link mt-3"
                onClick={() => setMethod(true)}
              >
                Read the assumptions <ArrowRight size={14} />
              </button>
            </div>
          </section>
        </aside>
      </div>
      <Dialog open={compare} onOpenChange={setCompare}>
        <DialogContent
          className="sm:max-w-3xl"
          onCloseAutoFocus={restoreCompareFocus}
        >
          <DialogHeader>
            <DialogTitle>See the trade-offs side by side.</DialogTitle>
            <DialogDescription>
              Equal rent split. One-way public transport. Fictional estimates.
            </DialogDescription>
          </DialogHeader>
          <div
            className="comparison-scroll"
            tabIndex={0}
            role="region"
            aria-label="Area comparison"
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">Your priorities</th>
                  {comparison.map((a) => (
                    <th scope="col" key={a.id}>
                      {a.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Rent / person / month</th>
                  {comparison.map((a) => (
                    <td key={a.id}>{money(a.perPerson)}</td>
                  ))}
                </tr>
                {group.members.map((m, i) => (
                  <tr key={m.id}>
                    <th scope="row">{m.name}’s commute</th>
                    {comparison.map((a) => (
                      <td key={a.id}>{a.times[i]} min</td>
                    ))}
                  </tr>
                ))}
                <tr>
                  <th scope="row">Longest commute</th>
                  {comparison.map((a) => (
                    <td key={a.id}>{a.longest} min</td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">Commute gap</th>
                  {comparison.map((a) => (
                    <td key={a.id}>{a.gap} min</td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="muted text-sm">
            Lower rent can mean a less equal commute. Decide which trade-off
            works for your group.
          </p>
        </DialogContent>
      </Dialog>
      <Dialog open={method} onOpenChange={setMethod}>
        <DialogContent onCloseAutoFocus={restoreMethodFocus}>
          <DialogHeader>
            <DialogTitle>Clear rules. No hidden compromises.</DialogTitle>
            <DialogDescription>
              This is a proposed ranking model for team review.
            </DialogDescription>
          </DialogHeader>
          <div className="method-copy">
            <h3>1. Respect everyone’s limits</h3>
            <p>
              Divide whole-flat rent equally, then check each person’s budget
              and commute limit. Exclude an area if any limit fails or a route
              is missing.
            </p>
            <h3>2. Compare three things</h3>
            <p>
              Lower rent, shorter average commute, and a smaller gap between the
              shortest and longest commutes. {priorities[priority].explanation}
            </p>
            <h3>3. Make the trade-off visible</h3>
            <p>
              We show each person’s journey and the longest journey. Commute gap
              is one view of fairness; equal travel time isn’t everyone’s
              definition of fair.
            </p>
            <Separator />
            <p className="text-sm">
              Demo score = 100 × [1 − (rent weight × rent/person ÷ 2000 +
              commute weight × average minutes ÷ 90 + gap weight × gap minutes ÷
              90)]. Scores are floored at zero; higher ranks first. Weights and
              scales need team validation. This is not a probability or a
              measured satisfaction score.
            </p>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
function UsersStack({ count }: { count: number }) {
  return (
    <div className="flex" aria-label={`${count} flatmates`}>
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className={`stack-dot member-color-${i}`} />
      ))}
    </div>
  );
}
