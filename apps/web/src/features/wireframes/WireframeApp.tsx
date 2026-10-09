import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleHelp,
  Copy,
  House,
  Link2,
  LoaderCircle,
  RotateCcw,
  Scale,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  X,
} from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import { Input } from '@/components/ui/input';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Progress } from '@/components/ui/progress';
import { cn } from '@/lib/utils';
import { useDialogState } from '@/lib/use-dialog-state';
import { CreateGroup, GroupLobby, MemberForm } from './GroupViews';
import { ResultsView } from './ResultsView';
import {
  previews,
  type Preview,
  groupReady,
  sampleGroup,
  type Group,
  type Scenario,
  type Stage,
} from './model';

const previewLabels: Record<Preview, string> = {
  create: 'Start the journey',
  group: 'Group · waiting',
  join: 'Invite · member joins',
  preferences: 'Member preferences',
  processing: 'Processing',
  results: 'Ranked results',
  empty: 'No matching areas',
  partial: 'Missing route data',
  failure: 'Search failed',
};
const steps = [
  { label: 'Your group', icon: Users },
  { label: 'Preferences', icon: SlidersHorizontal },
  { label: 'Find the balance', icon: Scale },
  { label: 'Your shortlist', icon: House },
];
function initial(preview: Preview): {
  group: Group;
  stage: Stage;
  scenario: Scenario;
} {
  const group = sampleGroup();
  if (preview === 'group' || preview === 'join')
    group.members[2]!.ready = false;
  if (preview === 'empty')
    group.members.forEach((m) => {
      m.maxCommute = 10;
    });
  const stage =
    preview === 'join'
      ? 'preferences'
      : preview === 'empty' || preview === 'partial'
        ? 'results'
        : preview === 'failure'
          ? 'processing'
          : preview;
  return {
    group,
    stage,
    scenario:
      preview === 'partial' || preview === 'failure' ? preview : 'normal',
  };
}
export function WireframeApp({
  initialPreview = 'create',
}: {
  initialPreview?: Preview;
}) {
  const [state, setState] = useState(() => initial(initialPreview));
  const { group, stage, scenario } = state;
  const [activeMember, setActiveMember] = useState(
    initialPreview === 'join' ? '3' : '1',
  );
  const [preview, setPreview] = useState(initialPreview);
  const [paused, setPaused] = useState(initialPreview === 'processing');
  const {
    open: invite,
    onOpenChange: setInvite,
    restoreFocus: restoreInviteFocus,
  } = useDialogState();
  const {
    open: help,
    onOpenChange: setHelp,
    restoreFocus: restoreHelpFocus,
  } = useDialogState();
  const [copyStatus, setCopyStatus] = useState('');
  const heading = useRef<HTMLDivElement>(null);
  const [hasResults, setHasResults] = useState(
    initialPreview === 'results' ||
      initialPreview === 'partial' ||
      initialPreview === 'empty',
  );
  const index =
    stage === 'create' || stage === 'group'
      ? 0
      : stage === 'preferences'
        ? 1
        : stage === 'processing'
          ? 2
          : 3;
  const link = `${window.location.origin}/?review=join`;
  const go = (next: Stage) => {
    setState((s) => ({ ...s, stage: next }));
  };
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [stage]);
  const complete = useCallback(() => {
    setHasResults(true);
    setState((s) => ({ ...s, stage: 'results' }));
  }, []);
  const runSearch = () => {
    if (!groupReady(group)) return;
    setPaused(false);
    setHasResults(false);
    setState((s) => ({ ...s, stage: 'processing', scenario: 'normal' }));
  };
  function loadPreview(value: Preview) {
    setState(initial(value));
    setPreview(value);
    setActiveMember(value === 'join' ? '3' : '1');
    setPaused(value === 'processing');
    setHasResults(['results', 'partial', 'empty'].includes(value));
  }
  return (
    <div className="wireframe-app">
      <div className="review-toolbar">
        <div className="review-label">
          <span className="review-dot" />
          <strong>Design review</strong>
          <span className="hidden sm:inline">
            Interactive wireframe · fictional data
          </span>
        </div>
        <div className="flex items-center gap-2">
          <NativeSelect
            aria-label="Preview a journey state"
            value={preview}
            onChange={(e) => loadPreview(e.target.value as Preview)}
          >
            {previews.map((p) => (
              <NativeSelectOption key={p} value={p}>
                {previewLabels[p]}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Restart journey"
            onClick={() => loadPreview('create')}
          >
            <RotateCcw />
          </Button>
        </div>
      </div>
      <header className="app-header">
        <Link to="/" search={{ review: 'create' }} className="brand">
          <span className="brand-icon">
            <House size={21} strokeWidth={2} />
          </span>
          flatsplit<span className="brand-period">.</span>
        </Link>
        <div className="header-context">
          <span>Singapore</span>
          <span className="header-divider" />
          <span>Find a fairer place.</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          aria-label="How it works"
          onClick={() => setHelp(true)}
        >
          <CircleHelp data-icon="inline-start" />
          <span className="hidden sm:inline">How it works</span>
        </Button>
      </header>
      <div className="app-frame">
        <aside className="journey-sidebar">
          <div className="sidebar-group">
            <span className="sidebar-caption">YOUR NEXT CHAPTER</span>
            <h2>{stage === 'create' ? 'A home, together.' : group.name}</h2>
            <p>
              {stage === 'create'
                ? 'A little closer to everyone.'
                : `${group.size} flatmates · Singapore`}
            </p>
          </div>
          <nav aria-label="Group journey">
            <ol>
              {steps.map((step, i) => (
                <li key={step.label}>
                  <button
                    className={cn(
                      'journey-step',
                      index === i && 'active',
                      index > i && 'complete',
                    )}
                    aria-current={index === i ? 'step' : undefined}
                    disabled={
                      stage === 'create' || i === 2 || (i === 3 && !hasResults)
                    }
                    onClick={() =>
                      go(
                        i === 0 ? 'group' : i === 1 ? 'preferences' : 'results',
                      )
                    }
                  >
                    <span className="step-icon">
                      {index > i ? (
                        <Check size={16} />
                      ) : (
                        <step.icon size={17} />
                      )}
                    </span>
                    <span>{step.label}</span>
                    <span className="step-number">0{i + 1}</span>
                  </button>
                </li>
              ))}
            </ol>
          </nav>
          <div className="sidebar-bottom">
            <Scale size={24} strokeWidth={1.4} />
            <p>
              A better move is one
              <br />
              that works for everyone.
            </p>
            <span>2–5 people. One shared decision.</span>
          </div>
        </aside>
        <main id="main-content" className="workspace">
          <div className="workspace-breadcrumb" ref={heading} tabIndex={-1}>
            <span>Your home search</span>
            <span>/</span>
            <strong>{steps[index]?.label}</strong>
            <Badge variant="outline" className="ml-auto">
              Prototype
            </Badge>
          </div>
          {stage === 'create' && (
            <CreateGroup
              onCreate={(newGroup) => {
                setState({
                  group: newGroup,
                  stage: 'preferences',
                  scenario: 'normal',
                });
                setActiveMember('1');
                setHasResults(false);
              }}
              onDemo={() => loadPreview('results')}
            />
          )}
          {stage === 'group' && (
            <GroupLobby
              group={group}
              onEdit={(id) => {
                setActiveMember(id);
                go('preferences');
              }}
              onInvite={() => {
                setCopyStatus('');
                setInvite(true);
              }}
              onSearch={runSearch}
            />
          )}
          {stage === 'preferences' && (
            <MemberForm
              key={activeMember + preview}
              member={group.members.find((m) => m.id === activeMember)!}
              onCancel={() => go('group')}
              onSave={(member) => {
                setState((s) => ({
                  ...s,
                  stage: 'group',
                  scenario: 'normal',
                  group: {
                    ...s.group,
                    members: s.group.members.map((m) =>
                      m.id === member.id ? member : m,
                    ),
                  },
                }));
                setHasResults(false);
              }}
            />
          )}
          {stage === 'processing' &&
            (scenario === 'failure' ? (
              <div className="processing-surface">
                <div className="icon-tile">
                  <X size={30} />
                </div>
                <h1>That search hit a bump.</h1>
                <p className="lead">
                  Your group’s preferences are still here. We couldn’t retrieve
                  the route estimates.
                </p>
                <Alert>
                  <AlertTitle>Search temporarily unavailable</AlertTitle>
                  <AlertDescription>
                    This is a simulated service failure. Retry the same
                    preferences, or return to your group.
                  </AlertDescription>
                </Alert>
                <div className="flex flex-wrap justify-center gap-3">
                  <Button variant="outline" onClick={() => go('group')}>
                    Back to group
                  </Button>
                  <Button onClick={runSearch}>
                    <RotateCcw data-icon="inline-start" /> Retry search
                  </Button>
                </div>
              </div>
            ) : (
              <Processing
                group={group}
                paused={paused}
                onComplete={complete}
                onCancel={() => go('group')}
              />
            ))}
          {stage === 'results' && (
            <ResultsView
              key={preview}
              group={group}
              scenario={scenario}
              onEdit={() => go('group')}
              onRetry={runSearch}
            />
          )}
          <footer className="workspace-footer">
            <span>Made for different journeys, shared.</span>
            <span>
              CS5224 · FlatSplit <span className="footer-dot">/</span>{' '}
              <Link to="/status">Service status</Link>
            </span>
          </footer>
        </main>
      </div>
      <Dialog open={invite} onOpenChange={setInvite}>
        <DialogContent onCloseAutoFocus={restoreInviteFocus}>
          <DialogHeader>
            <DialogTitle>Bring your people along.</DialogTitle>
            <DialogDescription>
              In the live service, each flatmate will use a private group link
              to add their own preferences.
            </DialogDescription>
          </DialogHeader>
          <Alert>
            <InfoIcon />
            <AlertTitle>Preview link only</AlertTitle>
            <AlertDescription>
              This opens the sample member journey. It does not share your
              current group or connect different devices.
            </AlertDescription>
          </Alert>
          <Field>
            <FieldLabel htmlFor="invite-link">Sample member preview</FieldLabel>
            <Input
              id="invite-link"
              value={link}
              readOnly
              onFocus={(e) => e.target.select()}
            />
            <FieldDescription>
              Localhost links only open on a device running this app.
            </FieldDescription>
          </Field>
          <Button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(link);
                setCopyStatus('Preview link copied.');
              } catch {
                setCopyStatus(
                  'Copy was unavailable. Select the link above and copy it manually.',
                );
              }
            }}
          >
            <Copy data-icon="inline-start" /> Copy preview link
          </Button>
          <p role="status" className="text-sm">
            {copyStatus}
          </p>
        </DialogContent>
      </Dialog>
      <Dialog open={help} onOpenChange={setHelp}>
        <DialogContent onCloseAutoFocus={restoreHelpFocus}>
          <DialogHeader>
            <DialogTitle>A home that works for all of you.</DialogTitle>
            <DialogDescription>
              Four steps to a shared shortlist.
            </DialogDescription>
          </DialogHeader>
          <ol className="help-steps">
            <li>
              <Users />
              <div>
                <h3>Gather your group</h3>
                <p>
                  Start with 2–5 flatmates. Everyone brings their own
                  priorities.
                </p>
              </div>
            </li>
            <li>
              <SlidersHorizontal />
              <div>
                <h3>Set your boundaries</h3>
                <p>
                  Add a destination, monthly rent budget, and maximum commute.
                </p>
              </div>
            </li>
            <li>
              <Scale />
              <div>
                <h3>Find the balance</h3>
                <p>
                  Only areas within everyone’s limits can make the shortlist.
                </p>
              </div>
            </li>
            <li>
              <House />
              <div>
                <h3>Choose together</h3>
                <p>
                  Compare rent and every person’s journey. Change priorities to
                  explore trade-offs.
                </p>
              </div>
            </li>
          </ol>
          <p className="fine-print">
            This browser-only prototype uses invented data and resets on
            refresh. No authentication, live sharing, real rental listings, or
            bookings.
          </p>
        </DialogContent>
      </Dialog>
    </div>
  );
}
function InfoIcon() {
  return <Link2 />;
}
function Processing({
  group,
  paused,
  onComplete,
  onCancel,
}: {
  group: Group;
  paused: boolean;
  onComplete: () => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState(paused ? 1 : 0);
  useEffect(() => {
    if (paused) return;
    const timers = [
      window.setTimeout(() => setStep(1), 1000),
      window.setTimeout(() => setStep(2), 2300),
      window.setTimeout(() => setStep(3), 3600),
      window.setTimeout(onComplete, 4700),
    ];
    return () => timers.forEach(window.clearTimeout);
  }, [paused, onComplete]);
  const labels = [
    'Check everyone’s preferences',
    'Read rental and route estimates',
    'Apply budgets and commute limits',
    'Rank the fairest trade-offs',
  ];
  return (
    <section className="processing-surface">
      <div className="processing-orbit">
        <Scale size={40} strokeWidth={1.25} />
      </div>
      <h1>Finding your middle ground.</h1>
      <p className="lead">
        Six neighbourhoods. {group.size} different journeys.
        <br />
        We’re making sure everyone is considered.
      </p>
      <div className="processing-steps">
        {labels.map((label, i) => (
          <div key={label} className={cn(i <= step && 'active')}>
            <span>
              {i < step ? (
                <Check size={17} />
              ) : i === step ? (
                <LoaderCircle className="motion-safe:animate-spin" size={17} />
              ) : (
                <span className="size-2 rounded-full bg-muted-foreground/30" />
              )}
            </span>
            <span>{label}</span>
            {i < step && <small>Complete</small>}
          </div>
        ))}
      </div>
      <Progress
        value={((step + 1) / 4) * 100}
        aria-label="Simulated search progress"
      />
      <p className="fine-print" role="status">
        {labels[step]} · Simulated progress, not a live cloud job.
      </p>
      {paused && (
        <Button onClick={onComplete}>
          Complete simulation <ArrowRight data-icon="inline-end" />
        </Button>
      )}
      <Button variant="ghost" onClick={onCancel}>
        <ArrowLeft data-icon="inline-start" /> Back to group
      </Button>
      <div className="processing-tip">
        <ShieldCheck size={20} />
        <p>We never hide a long commute behind a good average.</p>
      </div>
    </section>
  );
}
