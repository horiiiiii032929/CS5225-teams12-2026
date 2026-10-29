import { useId, useState } from 'react';
import type { GroupView, SearchView } from '@flatsplit/contracts/api';
import { points, WIDTH, HEIGHT, position, mapMarkers } from './town-map';

const money = (value: number | null) =>
  value === null
    ? 'Unavailable'
    : `S$${Math.ceil(value).toLocaleString('en-SG')}`;
const minutes = (value: number | null) =>
  value === null ? 'Unavailable' : `${Math.ceil(value)} min`;

/** #24's map/detail surface. #23 can reuse it with the public response/group
 * props; it owns neither fetches nor a second copy of server result data. */
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
  const selectedPoint = points[selected.town];
  const markers = mapMarkers(search.ranked);
  const unmapped = search.ranked.filter((area) => !points[area.town]);
  const select = (town: string) => setSelectedTown(town);

  return (
    <section className="town-explorer" aria-labelledby={`${id}-title`}>
      <div className="town-explorer-heading">
        <div>
          <p className="town-eyebrow">Your shortlist, on the map</p>
          <h4 id={`${id}-title`}>Find your bearings.</h4>
        </div>
        <span className="town-map-key">
          <span aria-hidden="true" /> Recommended town
        </span>
      </div>
      <p className="live-caption" id={`${id}-map-help`}>
        Select a numbered pin or a town below. Points mark each town’s reference
        MRT station, not a property or town boundary. On small screens, scroll
        the map sideways.
      </p>
      <div
        className="town-map-scroll"
        role="region"
        aria-label="Singapore town reference map"
        aria-describedby={`${id}-map-help`}
        tabIndex={0}
      >
        <div className="town-map-canvas">
          <svg
            width={WIDTH}
            height={HEIGHT}
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            aria-hidden="true"
          >
            {[103.7, 103.8, 103.9, 104].map((lon) => (
              <g key={lon}>
                <line
                  x1={position({ lat: 0, lon }).x}
                  x2={position({ lat: 0, lon }).x}
                  y1={24}
                  y2={HEIGHT - 28}
                  className="town-map-grid"
                />
                <text
                  x={position({ lat: 0, lon }).x}
                  y={HEIGHT - 10}
                  textAnchor="middle"
                  className="town-map-axis"
                >
                  {lon.toFixed(1)}° E
                </text>
              </g>
            ))}
            {[1.3, 1.4].map((lat) => (
              <g key={lat}>
                <line
                  x1={30}
                  x2={WIDTH - 20}
                  y1={position({ lat, lon: 0 }).y}
                  y2={position({ lat, lon: 0 }).y}
                  className="town-map-grid"
                />
                <text
                  x={5}
                  y={position({ lat, lon: 0 }).y - 8}
                  className="town-map-axis"
                >
                  {lat.toFixed(1)}° N
                </text>
              </g>
            ))}
            {Object.entries(points).map(([town, point]) => {
              const anchor = position(point);
              return (
                <circle
                  key={town}
                  cx={anchor.x}
                  cy={anchor.y}
                  r={3}
                  className="town-map-reference"
                />
              );
            })}
            {markers.map(({ area, anchor, marker }) => (
              <line
                key={area.town}
                x1={anchor.x}
                y1={anchor.y}
                x2={marker.x}
                y2={marker.y}
                className="town-map-leader"
              />
            ))}
            <text x={WIDTH - 30} y={30} className="town-map-north">
              ↑ N
            </text>
          </svg>
          {markers.map(({ area, marker }) => (
            <button
              key={area.town}
              type="button"
              className="town-map-pin"
              style={{ left: marker.x, top: marker.y }}
              aria-label={`Show ${area.displayName} on map, rank ${area.rank}`}
              aria-pressed={selected.town === area.town}
              aria-controls={`${id}-detail`}
              title={area.displayName}
              onClick={() => select(area.town)}
            >
              {area.rank}
            </button>
          ))}
        </div>
      </div>
      {unmapped.length > 0 && (
        <p className="live-caption">
          No verified map point for{' '}
          {unmapped.map((area) => area.displayName).join(', ')}. Their details
          are available in the town list.
        </p>
      )}
      <ol className="town-choice-list" aria-label="Recommended towns">
        {search.ranked.map((area) => (
          <li key={area.town}>
            <button
              type="button"
              aria-pressed={selected.town === area.town}
              aria-controls={`${id}-detail`}
              onClick={() => select(area.town)}
            >
              <span className="town-choice-rank" aria-hidden="true">
                {area.rank}
              </span>
              <span className="town-choice-name">{area.displayName}</span>
              <span className="town-choice-rent">
                {money(area.rentPerPerson)}
                <small>/ person / month</small>
              </span>
            </button>
          </li>
        ))}
      </ol>
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
        </div>
        <p className="live-caption">
          {selectedPoint
            ? `Map reference: ${selectedPoint.stationName}.`
            : 'No verified map point available.'}
        </p>
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
    </section>
  );
}
