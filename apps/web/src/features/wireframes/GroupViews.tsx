import { useState } from 'react';
import {
  ArrowRight,
  Check,
  Clock3,
  Link2,
  MapPin,
  Plus,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldError,
} from '@/components/ui/field';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Progress } from '@/components/ui/progress';
import {
  destinations,
  groupReady,
  money,
  validMember,
  type Destination,
  type Group,
  type Member,
} from './model';

export function CreateGroup({
  onCreate,
  onDemo,
}: {
  onCreate: (group: Group) => void;
  onDemo: () => void;
}) {
  const [size, setSize] = useState('3');
  const [error, setError] = useState('');
  return (
    <div className="create-layout">
      <section>
        <h1>
          Different destinations.
          <br />
          <span className="text-primary">One place to call home.</span>
        </h1>
        <p className="lead">
          Find a Singapore neighbourhood that works for every flatmate’s budget.
          And every flatmate’s morning.
        </p>
        <form
          className="setup-form"
          onSubmit={(event) => {
            event.preventDefault();
            const values = new FormData(event.currentTarget);
            const name = String(values.get('group')).trim();
            const creator = String(values.get('name')).trim();
            if (!name || !creator) {
              setError('Add a group name and your name to continue.');
              return;
            }
            onCreate({
              name,
              size: Number(size),
              members: Array.from({ length: Number(size) }, (_, i) => ({
                id: String(i + 1),
                name: i === 0 ? creator : '',
                destination: 'nus',
                budget: 1400,
                maxCommute: 45,
                ready: false,
              })),
            });
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="group-name">
                Give your group a name
              </FieldLabel>
              <Input
                id="group-name"
                name="group"
                placeholder="e.g. Our next chapter"
                maxLength={50}
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="creator-name">Your first name</FieldLabel>
              <Input
                id="creator-name"
                name="name"
                placeholder="What should your flatmates call you?"
                maxLength={30}
                autoComplete="given-name"
                required
              />
            </Field>
            <Field>
              <FieldLabel id="group-size-label">
                How many flatmates, including you?
              </FieldLabel>
              <ToggleGroup
                type="single"
                value={size}
                onValueChange={(value) => {
                  if (value) setSize(value);
                }}
                aria-labelledby="group-size-label"
                variant="outline"
                className="w-full"
              >
                {[2, 3, 4, 5].map((n) => (
                  <ToggleGroupItem key={n} value={String(n)} className="flex-1">
                    {n} people
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </Field>
            {error && <FieldError role="alert">{error}</FieldError>}
            <Button size="lg" type="submit" className="w-full">
              Create your group <ArrowRight data-icon="inline-end" />
            </Button>
          </FieldGroup>
        </form>
        <p className="fine-print">
          <ShieldCheck size={15} /> No account needed. Use sample information in
          this prototype.
        </p>
        <Button variant="link" onClick={onDemo}>
          Just exploring? Open the sample shortlist{' '}
          <ArrowRight data-icon="inline-end" />
        </Button>
      </section>
      <aside className="intro-panel">
        <div className="intro-symbol">
          <Users size={34} strokeWidth={1.4} />
        </div>
        <h2>
          A good move.
          <br />
          For the whole group.
        </h2>
        <p>
          The best location is more than the cheapest one. See the trade-offs
          before you choose.
        </p>
        <div className="example-commutes">
          <div className="flex items-center justify-between">
            <strong>Everyone’s journey matters</strong>
            <Badge variant="outline">Example</Badge>
          </div>
          {[
            { name: 'Alex', time: 22 },
            { name: 'Jamie', time: 18 },
            { name: 'Sam', time: 27 },
          ].map((m, i) => (
            <div key={m.name} className="commute-line">
              <span>{m.name}</span>
              <div className="bar-track">
                <div
                  className={`member-color-${i}`}
                  style={{ width: `${(m.time / 45) * 100}%` }}
                />
              </div>
              <strong>{m.time} min</strong>
            </div>
          ))}
        </div>
        <div className="intro-note">
          <ShieldCheck size={22} />
          <span>
            <strong>No one gets left with the long ride.</strong>
            <br />
            Compare the longest commute, not just the average.
          </span>
        </div>
      </aside>
    </div>
  );
}

export function GroupLobby({
  group,
  onEdit,
  onInvite,
  onSearch,
}: {
  group: Group;
  onEdit: (id: string) => void;
  onInvite: () => void;
  onSearch: () => void;
}) {
  const ready = group.members.filter((m) => m.ready).length;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>A place starts with people.</h1>
          <p className="lead">
            Bring everyone’s needs to the table. Your shortlist starts here.
          </p>
        </div>
        <Button variant="outline" onClick={onInvite}>
          <Link2 data-icon="inline-start" /> Invite flatmates
        </Button>
      </div>
      <div className="content-columns">
        <section className="surface">
          <div className="section-heading">
            <h2>Your flatmates</h2>
            <Badge variant="secondary">
              {ready} of {group.size} ready
            </Badge>
          </div>
          <div className="member-list">
            {group.members.map((m, i) => (
              <div className="member-row" key={m.id}>
                <div className={`person-avatar member-color-${i}`}>
                  {m.name ? (
                    m.name.slice(0, 1).toUpperCase()
                  ) : (
                    <Plus size={18} />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <h3>
                    {m.name || `Flatmate ${i + 1}`}{' '}
                    {i === 0 && <span className="muted">· organiser</span>}
                  </h3>
                  <p>
                    {m.ready
                      ? `${destinations.find((d) => d.id === m.destination)?.short} · ${money(m.budget)}/mo · up to ${m.maxCommute} min`
                      : 'Preferences not submitted yet'}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onEdit(m.id)}
                >
                  {m.ready ? 'Edit' : 'Add preferences'}
                  <ArrowRight data-icon="inline-end" />
                </Button>
              </div>
            ))}
          </div>
          <p className="fine-print">
            Demo: you can act as each flatmate. Live member permissions will be
            added with the group API.
          </p>
        </section>
        <aside className="surface flex flex-col gap-5">
          <div className="icon-tile">
            <Users size={23} />
          </div>
          <h2>Everyone gets a say.</h2>
          <p className="muted">
            We’ll only compare areas when all {group.size} flatmates have
            submitted. Each budget and commute limit is a hard requirement.
          </p>
          <Progress
            value={(ready / group.size) * 100}
            aria-label="Flatmates ready"
          />
          <p className="text-sm" role="status">
            {ready === group.size
              ? 'Everyone is ready. Let’s find your middle ground.'
              : `Waiting for ${group.size - ready} ${group.size - ready === 1 ? 'flatmate' : 'flatmates'}.`}
          </p>
          <Button size="lg" disabled={!groupReady(group)} onClick={onSearch}>
            Find our neighbourhoods <ArrowRight data-icon="inline-end" />
          </Button>
          <p className="fine-print">
            Estimates assume an equal split of whole-flat rent, excluding bills.
          </p>
        </aside>
      </div>
    </>
  );
}

export function MemberForm({
  member,
  onSave,
  onCancel,
}: {
  member: Member;
  onSave: (member: Member) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(member);
  const [submitted, setSubmitted] = useState(false);
  const errors = {
    name: !draft.name.trim() ? 'Enter your first name.' : '',
    budget:
      !Number.isFinite(draft.budget) ||
      draft.budget < 300 ||
      draft.budget > 5000
        ? 'Enter a monthly budget from S$300 to S$5,000.'
        : '',
    commute:
      !Number.isInteger(draft.maxCommute) ||
      draft.maxCommute < 10 ||
      draft.maxCommute > 120
        ? 'Enter a whole number from 10 to 120 minutes.'
        : '',
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Your day. Your say.</h1>
          <p className="lead">
            Tell us what a comfortable home base looks like for you.
          </p>
        </div>
        <Badge variant="outline">
          {member.name || 'New flatmate'}’s preferences
        </Badge>
      </div>
      <div className="content-columns">
        <form
          className="surface"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            setSubmitted(true);
            if (validMember(draft))
              onSave({ ...draft, name: draft.name.trim(), ready: true });
          }}
        >
          <FieldGroup>
            <Field data-invalid={submitted && !!errors.name}>
              <FieldLabel htmlFor="member-name">First name</FieldLabel>
              <Input
                id="member-name"
                value={draft.name}
                maxLength={30}
                aria-invalid={submitted && !!errors.name}
                aria-describedby={
                  submitted && errors.name ? 'name-error' : undefined
                }
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
              {submitted && errors.name && (
                <FieldError id="name-error">{errors.name}</FieldError>
              )}
            </Field>
            <Field>
              <FieldLabel htmlFor="destination">
                Where do you travel to most days?
              </FieldLabel>
              <NativeSelect
                id="destination"
                value={draft.destination}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    destination: e.target.value as Destination,
                  })
                }
              >
                {destinations.map((d) => (
                  <NativeSelectOption key={d.id} value={d.id}>
                    {d.label}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
              <FieldDescription>
                Choose one of five Singapore destinations available in this
                demo. Travel estimates are one way, by public transport.
              </FieldDescription>
            </Field>
            <Field data-invalid={submitted && !!errors.budget}>
              <FieldLabel htmlFor="budget">
                Your monthly rent budget (SGD)
              </FieldLabel>
              <Input
                id="budget"
                type="number"
                inputMode="numeric"
                min={300}
                max={5000}
                value={Number.isNaN(draft.budget) ? '' : draft.budget}
                aria-invalid={submitted && !!errors.budget}
                aria-describedby="budget-help"
                onChange={(e) =>
                  setDraft({ ...draft, budget: e.target.valueAsNumber })
                }
              />
              <FieldDescription id="budget-help">
                Per person, excluding utilities. We won’t recommend areas above
                your limit.
              </FieldDescription>
              {submitted && errors.budget && (
                <FieldError role="alert">{errors.budget}</FieldError>
              )}
            </Field>
            <Field data-invalid={submitted && !!errors.commute}>
              <FieldLabel htmlFor="commute">
                Longest comfortable commute (minutes)
              </FieldLabel>
              <Input
                id="commute"
                type="number"
                inputMode="numeric"
                min={10}
                max={120}
                value={Number.isNaN(draft.maxCommute) ? '' : draft.maxCommute}
                aria-invalid={submitted && !!errors.commute}
                onChange={(e) =>
                  setDraft({ ...draft, maxCommute: e.target.valueAsNumber })
                }
              />
              {submitted && errors.commute && (
                <FieldError role="alert">{errors.commute}</FieldError>
              )}
            </Field>
            <Alert>
              <ShieldCheck />
              <AlertDescription>
                Your group can see these preferences. Only share a campus,
                station, or workplace area you’re comfortable sharing.
              </AlertDescription>
            </Alert>
            <div className="flex flex-wrap justify-end gap-3">
              <Button type="button" variant="outline" onClick={onCancel}>
                Cancel
              </Button>
              <Button type="submit">
                Save my preferences <Check data-icon="inline-end" />
              </Button>
            </div>
          </FieldGroup>
        </form>
        <aside className="flex flex-col gap-6">
          <div className="editorial-note">
            <MapPin size={28} />
            <h2>
              One shared home.
              <br />
              Different daily journeys.
            </h2>
            <p>
              We check every area against everyone’s limits first. Then we look
              for the best balance.
            </p>
          </div>
          <div className="surface flex flex-col gap-3">
            <Clock3 size={22} />
            <h3>You can change your mind.</h3>
            <p className="muted">
              Edit your preferences any time. Your group will run a new search
              so the results reflect everyone’s latest needs.
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}
