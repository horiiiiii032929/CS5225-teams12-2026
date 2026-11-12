import { useId, useState } from 'react';
import type { GroupView, SearchView } from '@flatsplit/contracts/api';
import { points, WIDTH, HEIGHT, position, mapMarkers } from './town-map';
import background from './town-map-background.json';
import { formatCommuteMinutes as minutes } from './format-commute';

const money = (value: number | null) =>
  value === null
    ? 'Unavailable'
    : `S$${Math.ceil(value).toLocaleString('en-SG')}`;

const mrtLineNames: Record<string, string> = {
  EW: 'East–West',
  NS: 'North–South',
  NE: 'North East',
  CC: 'Circle',
  DT: 'Downtown',
  TE: 'Thomson–East Coast',
};

const landmarks = [
  { town: 'WOODLANDS', label: 'Woodlands', dx: -12, dy: -26 },
  { town: 'PUNGGOL', label: 'Punggol', dx: 20, dy: -24 },
  { town: 'JURONG EAST', label: 'Jurong East', dx: -32, dy: 34 },
  { town: 'TAMPINES', label: 'Tampines', dx: 39, dy: -22 },
];
export function TownMapResults({
  search,
  group,
}: {
  search: SearchView;
  group: GroupView;
}) {
  const id = useId();
  const [selectedTown, setSelectedTown] = useState('');
  if (
    search.status !== 'complete' ||
    search.groupRevision !== group.revision ||
    !group.allReady ||
    !search.ranked.length
  )
    return null;
  const selected =
    search.ranked.find((area) => area.town === selectedTown) ??
    search.ranked[0]!;
  const stationName = points[selected.town]?.stationName
    .replace(/ MRT STATION.*/, '')
    .toLowerCase()
    .replace(/\b\w/g, (initial) => initial.toUpperCase());
  const pinned = search.ranked.slice(0, 3);
  if (!pinned.some((area) => area.town === selected.town))
    pinned.push(selected);
  const markers = mapMarkers(pinned);

  return (
    <section className="town-explorer" aria-labelledby={`${id}-title`}>
      <div>
        <h4 id={`${id}-title`}>Explore towns by MRT</h4>
        <p className="live-caption" id={`${id}-map-help`}>
          Choose a town by name or select a pin to see its reference station and
          each flatmate’s commute.
        </p>
      </div>
      <div className="town-map-picker">
        <label htmlFor={`${id}-town`}>Town on map</label>
        <select
          id={`${id}-town`}
          value={selected.town}
          aria-controls={`${id}-detail`}
          onChange={(event) => setSelectedTown(event.target.value)}
        >
          {search.ranked.map((area) => (
            <option key={area.town} value={area.town}>
              {area.rank}. {area.displayName}
            </option>
          ))}
        </select>
      </div>
      <div
        className="town-map-canvas"
        role="region"
        aria-label="Singapore town reference map"
        aria-describedby={`${id}-map-help`}
        style={{ aspectRatio: `${WIDTH} / ${HEIGHT}` }}
      >
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true">
          <path d={background.land} className="town-map-land" />
          {background.lines.map(({ code, path }) => (
            <path
              key={code}
              d={path}
              data-line={code}
              className="town-map-rail"
            />
          ))}
          {landmarks.map(({ town, label, dx, dy }) => {
            const { x, y } = position(points[town]!);
            return (
              <text
                key={town}
                x={x + dx}
                y={y + dy}
                className="town-map-landmark"
                textAnchor="middle"
              >
                {label}
              </text>
            );
          })}
          <text x={WIDTH - 52} y={37} className="town-map-north">
            ↑ N
          </text>
          {markers.map(({ area, anchor, marker }) => (
            <g key={area.town}>
              <line
                x1={anchor.x}
                y1={anchor.y}
                x2={marker.x}
                y2={marker.y}
                className="town-map-leader"
              />
              <circle
                cx={anchor.x}
                cy={anchor.y}
                r={4}
                className="town-map-anchor"
              />
            </g>
          ))}
        </svg>
        {markers.map(({ area, marker }) => (
          <button
            key={area.town}
            type="button"
            className="town-map-pin"
            style={{
              left: `${(marker.x / WIDTH) * 100}%`,
              top: `${(marker.y / HEIGHT) * 100}%`,
            }}
            aria-label={`Show ${area.displayName} on map, rank ${area.rank}`}
            aria-pressed={selected.town === area.town}
            aria-controls={`${id}-detail`}
            title={area.displayName}
            onClick={() => setSelectedTown(area.town)}
          >
            {area.rank}
          </button>
        ))}
      </div>
      <div className="town-map-guide">
        <ul className="town-map-legend" aria-label="MRT lines">
          {background.lines.map(({ code }) => (
            <li key={code} data-line={code}>
              <span aria-hidden="true" /> {mrtLineNames[code]}
            </li>
          ))}
        </ul>
        <p className="live-caption town-map-sources">
          Schematic MRT lines ·{' '}
          <a
            href="https://www.lta.gov.sg/content/ltagov/en/map/train.html"
            target="_blank"
            rel="noreferrer"
          >
            Full LTA system map (opens in a new tab)
          </a>
        </p>
      </div>
      <section
        id={`${id}-detail`}
        className="town-detail"
        aria-labelledby={`${id}-selected`}
      >
        <div
          className="town-detail-heading"
          aria-live="polite"
          aria-atomic="true"
        >
          <p className="town-eyebrow">Rank {selected.rank} · Selected town</p>
          <h4 id={`${id}-selected`}>{selected.displayName}</h4>
          <p className="live-caption">
            {stationName
              ? `${stationName} MRT`
              : `No verified map point for ${selected.displayName}.`}
          </p>
        </div>
        <dl className="town-detail-metrics">
          <div>
            <dt>Monthly rent / person</dt>
            <dd>{money(selected.rentPerPerson)}</dd>
          </div>
          <div>
            <dt>Longest commute</dt>
            <dd>{minutes(selected.longestCommute)}</dd>
          </div>
          <div>
            <dt>Commute gap</dt>
            <dd>{minutes(selected.commuteGap)}</dd>
          </div>
        </dl>
        <table className="town-member-table">
          <caption>Each flatmate’s commute in {selected.displayName}</caption>
          <thead>
            <tr>
              <th scope="col">Flatmate</th>
              <th scope="col">Commute</th>
              <th scope="col">Their limit</th>
            </tr>
          </thead>
          <tbody>
            {selected.members.map((outcome, index) => {
              const member = group.members.find(
                (member) => member.memberId === outcome.memberId,
              );
              return (
                <tr key={outcome.memberId}>
                  <th scope="row">{member?.name ?? `Flatmate ${index + 1}`}</th>
                  <td>
                    {outcome.routeStatus === 'ok'
                      ? minutes(outcome.commuteMinutes)
                      : 'Unavailable'}
                  </td>
                  <td>
                    {member?.maxCommute == null
                      ? 'Unavailable'
                      : `${member.maxCommute} min`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="live-caption">
          Whole-flat estimate: {money(selected.wholeFlatRent)}, split equally;
          bills excluded. Times are rounded up for display; the search uses the
          original values.
        </p>
        <p className="live-caption">
          Rent source: {search.data.rentSource}. Period:{' '}
          {search.data.rentPeriod}. {search.data.commuteBasis}. Route
          calculation date unavailable.
        </p>
      </section>
      <p className="live-caption town-map-sources">
        Map data from{' '}
        <a href="https://data.gov.sg/datasets/d_29f066d67df3eae91df8a42f443863c8/view">
          SLA National Map Polygon
        </a>{' '}
        and{' '}
        <a href="https://datamall.lta.gov.sg/content/datamall/en/static-data.html">
          LTA Train Station
        </a>
        , accessed 13 November 2026 under the{' '}
        <a href="https://data.gov.sg/open-data-licence">
          Singapore Open Data Licence
        </a>
        .
      </p>
    </section>
  );
}
