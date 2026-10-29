import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import type { Place } from '@/api/generated/types.gen';
import type { MemberState } from '@flatsplit/contracts/api';
import {
  ApiError,
  errorMessage,
  groupKey,
  savePreferences,
  searchPlaces,
} from './api';
import type { Membership } from './membership';

type FormErrors = {
  name: string;
  destination: string;
  budget: string;
  commute: string;
};

export function MemberPreferencesForm({
  membership,
  member,
  onSaved,
  onCancel,
}: {
  membership: Membership;
  member: MemberState;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(member.name);
  const [destinationQuery, setDestinationQuery] = useState(
    member.destination?.label ?? '',
  );
  const [selectedPlace, setSelectedPlace] = useState<Place | null>(
    member.destination ?? null,
  );
  const [budget, setBudget] = useState(
    member.budget === null || member.budget === undefined
      ? ''
      : String(member.budget),
  );
  const [maxCommute, setMaxCommute] = useState(
    member.maxCommute === null || member.maxCommute === undefined
      ? ''
      : String(member.maxCommute),
  );
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(destinationQuery.trim());
    }, 300);
    return () => clearTimeout(timer);
  }, [destinationQuery]);

  const placesQuery = useQuery({
    queryKey: ['places', debouncedQuery],
    queryFn: ({ signal }) => searchPlaces(debouncedQuery, signal),
    enabled:
      debouncedQuery.length >= 3 &&
      !(selectedPlace && destinationQuery === selectedPlace.label),
    retry: false,
    staleTime: 0,
  });
  const showSearch =
    !selectedPlace &&
    destinationQuery.trim().length >= 3 &&
    destinationQuery.trim() === debouncedQuery;
  const searchResults = showSearch ? (placesQuery.data?.places ?? []) : [];
  const unsupported =
    (showSearch ? placesQuery.data : undefined)?.unsupported.map(
      (item) => `${item.label}: ${item.message}`,
    ) ?? [];
  const searchError =
    showSearch && placesQuery.isError ? errorMessage(placesQuery.error) : '';

  const budgetValue = Number(budget);
  const commuteValue = Number(maxCommute);
  const errors: FormErrors = {
    name:
      name.trim().length === 0 || name.trim().length > 30
        ? 'Enter your first name (1 to 30 characters).'
        : '',
    destination: selectedPlace
      ? ''
      : 'Choose a destination from the search results.',
    budget:
      budget.trim() === '' ||
      !Number.isFinite(budgetValue) ||
      budgetValue < 300 ||
      budgetValue > 5000
        ? 'Enter a monthly budget from S$300 to S$5,000.'
        : '',
    commute:
      maxCommute.trim() === '' ||
      !Number.isInteger(commuteValue) ||
      commuteValue < 10 ||
      commuteValue > 120
        ? 'Enter a whole number from 10 to 120 minutes.'
        : '',
  };
  const isValid = Object.values(errors).every((error) => error === '');

  const save = useMutation({
    mutationFn: async () =>
      savePreferences(membership, {
        name: name.trim(),
        placeId: selectedPlace!.placeId,
        budget: budgetValue,
        maxCommute: commuteValue,
      }),
    retry: false,
    onSuccess: async (group) => {
      // Immediately hide old-revision results, even if the subsequent read fails.
      await queryClient.cancelQueries({ queryKey: groupKey(membership) });
      queryClient.setQueryData(groupKey(membership), group);
      await queryClient.invalidateQueries({
        queryKey: groupKey(membership),
      });
      onSaved();
    },
  });

  return (
    <form
      className="surface"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitted(true);
        if (isValid && !save.isPending) save.mutate();
        else if (!save.isPending) {
          const first = errors.name
            ? 'member-preference-name'
            : errors.destination
              ? 'member-preference-destination'
              : errors.budget
                ? 'member-preference-budget'
                : 'member-preference-commute';
          document.getElementById(first)?.focus();
        }
      }}
    >
      <fieldset disabled={save.isPending}>
        <legend className="sr-only">Your preferences</legend>
        <FieldGroup>
          <Field data-invalid={submitted && !!errors.name}>
            <FieldLabel htmlFor="member-preference-name">First name</FieldLabel>
            <Input
              id="member-preference-name"
              value={name}
              maxLength={30}
              aria-invalid={submitted && !!errors.name}
              aria-describedby={
                submitted && errors.name ? 'member-name-error' : undefined
              }
              onChange={(event) => setName(event.target.value)}
            />
            {submitted && errors.name && (
              <FieldError id="member-name-error">{errors.name}</FieldError>
            )}
          </Field>
          <Field data-invalid={submitted && !!errors.destination}>
            <FieldLabel htmlFor="member-preference-destination">
              Where do you travel to most days?
            </FieldLabel>
            <Input
              id="member-preference-destination"
              value={destinationQuery}
              autoComplete="off"
              aria-invalid={submitted && !!errors.destination}
              aria-describedby={
                submitted && errors.destination
                  ? 'destination-help member-destination-error'
                  : 'destination-help'
              }
              onChange={(event) => {
                setDestinationQuery(event.target.value);
                setSelectedPlace(null);
              }}
            />
            <FieldDescription id="destination-help">
              Type at least 3 characters, then choose one of the results. Your
              group can see these preferences.
            </FieldDescription>
            {!selectedPlace &&
              destinationQuery.trim().length >= 3 &&
              (!showSearch || placesQuery.isFetching) && (
                <p role="status">Searching destinations…</p>
              )}
            {showSearch &&
              placesQuery.isSuccess &&
              !placesQuery.isFetching &&
              searchResults.length === 0 && (
                <p role="status">
                  No supported destinations found. Try another address or
                  station.
                </p>
              )}
            {searchError && (
              <Alert variant="destructive">
                <AlertTitle>Could not search destinations</AlertTitle>
                <AlertDescription>{searchError}</AlertDescription>
              </Alert>
            )}
            {searchResults.length > 0 && (
              <ul aria-label="Destination results">
                {searchResults.map((place) => (
                  <li key={place.placeId}>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedPlace(place);
                        setDestinationQuery(place.label);
                      }}
                    >
                      {place.label} · {place.address}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {unsupported.length > 0 && (
              <ul>
                {unsupported.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            )}
            {selectedPlace && (
              <p role="status">
                Selected: {selectedPlace.label} · {selectedPlace.address}
              </p>
            )}
            {submitted && errors.destination && (
              <FieldError id="member-destination-error" role="alert">
                {errors.destination}
              </FieldError>
            )}
          </Field>
          <Field data-invalid={submitted && !!errors.budget}>
            <FieldLabel htmlFor="member-preference-budget">
              Your monthly rent budget (SGD)
            </FieldLabel>
            <Input
              id="member-preference-budget"
              type="number"
              inputMode="numeric"
              min={300}
              max={5000}
              value={budget}
              aria-invalid={submitted && !!errors.budget}
              aria-describedby={
                submitted && errors.budget ? 'member-budget-error' : undefined
              }
              onChange={(event) => setBudget(event.target.value)}
            />
            <FieldDescription>
              Per person, excluding utilities. We won’t recommend areas above
              your limit.
            </FieldDescription>
            {submitted && errors.budget && (
              <FieldError id="member-budget-error" role="alert">
                {errors.budget}
              </FieldError>
            )}
          </Field>
          <Field data-invalid={submitted && !!errors.commute}>
            <FieldLabel htmlFor="member-preference-commute">
              Longest comfortable commute (minutes)
            </FieldLabel>
            <Input
              id="member-preference-commute"
              type="number"
              inputMode="numeric"
              min={10}
              max={120}
              value={maxCommute}
              aria-invalid={submitted && !!errors.commute}
              aria-describedby={
                submitted && errors.commute ? 'member-commute-error' : undefined
              }
              onChange={(event) => setMaxCommute(event.target.value)}
            />
            {submitted && errors.commute && (
              <FieldError id="member-commute-error" role="alert">
                {errors.commute}
              </FieldError>
            )}
          </Field>
          {save.isError && (
            <Alert variant="destructive">
              <AlertTitle>Could not save your preferences</AlertTitle>
              <AlertDescription>
                {save.error instanceof ApiError && save.error.status === 404
                  ? 'This group or selected destination is no longer available. Search for the destination again and select a fresh result; if saving still fails, refresh your group.'
                  : errorMessage(save.error)}
              </AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap justify-end gap-3">
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save my preferences'}
            </Button>
          </div>
        </FieldGroup>
      </fieldset>
    </form>
  );
}
