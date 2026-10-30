/* global __ENV, open */
import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { sha256 } from 'k6/crypto';
import { Counter } from 'k6/metrics';
import {
  apiBase,
  inspectResponse,
  poolLayout,
  projectManifest,
  projectSample,
  readDestinations,
  validateConfig,
  validatePlan,
} from './protocol.mjs';

function inputFile(path) {
  try {
    if (typeof path !== 'string' || !path.startsWith('/')) throw new Error();
    return JSON.parse(open(path));
  } catch {
    // Native parser/read errors can contain secrets; never attach their cause.
  }
  throw new Error('Unable to read load input.');
}

// k6's binary-level usage reporting must be disabled before starting k6.
if (__ENV.K6_NO_USAGE_REPORT !== 'true') {
  throw new Error('Disable k6 usage reporting before running load tooling.');
}

// All input validation and digest checks happen in init, before any HTTP call.
const plan = validatePlan(inputFile(__ENV.PLAN), (value) =>
  sha256(value, 'hex'),
);
const config = validateConfig(inputFile(__ENV.RUN_CONFIG), plan);
const base = apiBase(config);
const layout = poolLayout(plan);
const maxDurationSeconds = Math.ceil(
  (plan.duration_ms + config.timeout_ms + config.max_lateness_ms + 5000) / 1000,
);
const outcomeCounter = new Counter('load_samples');
const safeSystemTags = [
  'method',
  'status',
  'proto',
  'tls_version',
  'error_code',
  'scenario',
  'expected_response',
];

// Detect metadata only: never read environment tokens or provider credentials.
if (
  Object.keys(__ENV).some((key) =>
    /^K6_(?:CLOUDRUN_|EXECUTION_SEGMENT|HTTP_DEBUG)/.test(key),
  )
) {
  throw new Error('Only unsegmented single-instance execution is supported.');
}

export const options = {
  scenarios: {
    arrivals: {
      executor: 'per-vu-iterations',
      vus: plan.vus,
      iterations: 1,
      maxDuration: `${maxDurationSeconds}s`,
      gracefulStop: '0s',
      exec: 'default',
    },
  },
  setupTimeout: `${config.setup_timeout_seconds}s`,
  maxRedirects: 0,
  throw: true,
  systemTags: safeSystemTags,
  discardResponseBodies: false,
  summaryTrendStats: ['min', 'med', 'max', 'p(95)', 'p(99)'],
};

function durationMS(value) {
  if (typeof value !== 'string') return NaN;
  let duration = 0;
  let consumed = '';
  for (const match of value.matchAll(/([0-9]+(?:\.[0-9]+)?)(ms|s|m|h)/g)) {
    consumed += match[0];
    duration +=
      Number(match[1]) * { ms: 1, s: 1000, m: 60000, h: 3600000 }[match[2]];
  }
  return consumed === value ? duration : NaN;
}

function checkExecution() {
  const actual = exec.test.options;
  const scenarios = actual.scenarios;
  const scenario = scenarios && scenarios.arrivals;
  if (
    !scenarios ||
    Object.keys(scenarios).length !== 1 ||
    !scenario ||
    scenario.executor !== 'per-vu-iterations' ||
    scenario.vus !== plan.vus ||
    scenario.iterations !== 1 ||
    (scenario.exec && scenario.exec !== 'default') ||
    (scenario.startTime && durationMS(scenario.startTime) !== 0) ||
    durationMS(scenario.maxDuration) !== maxDurationSeconds * 1000 ||
    durationMS(scenario.gracefulStop) !== 0 ||
    durationMS(actual.setupTimeout) !== config.setup_timeout_seconds * 1000 ||
    (actual.executionSegment && actual.executionSegment !== '0:1') ||
    (actual.executionSegmentSequence &&
      actual.executionSegmentSequence !== '0,1') ||
    actual.httpDebug ||
    actual.maxRedirects !== 0 ||
    actual.throw !== true ||
    actual.discardResponseBodies !== false ||
    (actual.ext && (actual.ext.cloud || actual.ext.loadimpact)) ||
    (actual.tags && Object.keys(actual.tags).length !== 0) ||
    !Array.isArray(actual.systemTags) ||
    actual.systemTags.some((tag) => !safeSystemTags.includes(tag))
  ) {
    exec.test.abort('Load execution options are not supported.');
  }
}

function emit(row) {
  // Console data has one explicit allowlist; no request/response object is logged.
  console.log(JSON.stringify(row));
  if (row.kind === 'sample') {
    outcomeCounter.add(1, {
      phase: row.phase,
      cohort: row.cohort,
      op: row.op,
      outcome: row.outcome,
      search_status: row.search_status,
    });
  }
}

function context(phase, worker, op, arrival = null) {
  return {
    run_id: config.run_id,
    target: config.target,
    phase,
    worker,
    op,
    cohort:
      phase === 'setup' ? 'setup' : op === 'read' ? 'warm-complete' : 'mixed',
    ordinal: arrival ? arrival.ordinal : null,
    planned_ms: arrival ? arrival.at_ms : null,
  };
}

function call(ctx, origin, method, path, token, body, expected) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const started = Date.now();
  if (
    ctx.phase === 'measured' &&
    started - origin - ctx.planned_ms > config.max_lateness_ms
  ) {
    const dropped = {
      outcome: 'dropped',
      search_status: 'unknown',
      state: null,
    };
    emit(
      projectSample(
        ctx,
        {
          start_ms: started - origin,
          end_ms: started - origin,
          duration_ms: 0,
          status: 0,
        },
        dropped,
      ),
    );
    return dropped;
  }
  let response = null;
  try {
    response = http.request(
      method,
      `${base}${path}`,
      body === null ? null : JSON.stringify(body),
      {
        headers,
        redirects: 0,
        timeout: `${config.timeout_ms}ms`,
        throw: true,
        responseType: 'text',
        tags: { name: ctx.op, op: ctx.op },
      },
    );
  } catch {
    // throw:true prevents k6's automatic Request Failed warning from logging
    // a dynamic URL/error. Transport failures are represented only by status 0.
  }
  const finished = Date.now();
  const status =
    response &&
    Number.isSafeInteger(response.status) &&
    response.status >= 0 &&
    response.status <= 599
      ? response.status
      : 0;
  let result = inspectResponse(
    ctx.op,
    status,
    response ? response.body : null,
    expected,
  );
  const backwards = finished < started;
  if (backwards)
    result = {
      outcome:
        status >= 200 && status < 300 ? 'invalid_response' : 'http_error',
      search_status: 'unknown',
      state: null,
    };
  emit(
    projectSample(
      ctx,
      {
        start_ms: started - origin,
        end_ms: Math.max(started, finished) - origin,
        // Client elapsed time includes blocking/connection setup, unlike k6's
        // response.timings.duration. Date.now is wall time, not a monotonic clock.
        duration_ms: Math.max(0, finished - started),
        status,
      },
      result,
    ),
  );
  if (backwards) exec.test.abort('Load clock moved backwards.');
  if (ctx.phase === 'setup' && result.outcome !== 'success')
    exec.test.abort('Load setup did not reach ready state.');
  return result;
}

function create(phase, worker, origin, arrival = null) {
  const name = 'loadMember0';
  return call(
    context(phase, worker, 'create', arrival),
    origin,
    'POST',
    '/groups',
    null,
    { groupName: 'load synthetic group', size: 3, name },
    { revision: 1, memberCount: 1, name },
  );
}

function join(phase, worker, origin, group, index, arrival = null) {
  const name = `loadMember${index}`;
  const result = call(
    context(phase, worker, 'join', arrival),
    origin,
    'POST',
    `/groups/${group.groupId}/members`,
    group.inviteToken,
    { name },
    {
      groupId: group.groupId,
      revision: group.revision + 1,
      memberCount: group.revision + 1,
      name,
    },
  );
  if (result.outcome === 'success') group.revision = result.state.revision;
  return result;
}

function threeMembers(worker, origin) {
  const organiser = create('setup', worker, origin).state;
  const members = [{ ...organiser, name: 'loadMember0' }];
  for (let index = 1; index <= 2; index += 1) {
    members.push({
      ...join('setup', worker, origin, organiser, index).state,
      name: `loadMember${index}`,
    });
  }
  return { groupId: organiser.groupId, revision: 3, members };
}

function save(phase, worker, origin, group, member, alias, arrival = null) {
  const selected = plan.catalog.destinations.find(
    (destination) => destination.alias === alias,
  );
  const placeId = selected.place_ids[config.target];
  const result = call(
    context(phase, worker, 'save', arrival),
    origin,
    'PUT',
    `/groups/${group.groupId}/members/${member.memberId}`,
    member.memberToken,
    { name: member.name, placeId, budget: 5000, maxCommute: 120 },
    {
      groupId: group.groupId,
      revision: group.revision + 1,
      memberId: member.memberId,
      name: member.name,
      placeId,
      station: selected.station,
    },
  );
  if (result.outcome === 'success') group.revision = result.state.revision;
  return result;
}

export function setup() {
  checkExecution();
  emit(projectManifest(plan, config, new Date().toISOString()));
  const origin = Date.now();
  const workers = [];
  for (let worker = 0; worker < layout.length; worker += 1) {
    const allocation = layout[worker];
    const pools = { joins: [], save: null, reads: Object.create(null) };
    for (let index = 0; index < Math.ceil(allocation.joins / 2); index += 1) {
      const group = create('setup', worker, origin).state;
      pools.joins.push({
        groupId: group.groupId,
        inviteToken: group.inviteToken,
        revision: group.revision,
      });
    }
    if (allocation.saves > 0) pools.save = threeMembers(worker, origin);
    for (const alias of allocation.reads) {
      const group = threeMembers(worker, origin);
      const destinations = readDestinations(plan, worker, alias, (value) =>
        sha256(value, 'hex'),
      );
      for (const [index, member] of group.members.entries()) {
        save('setup', worker, origin, group, member, destinations[index]);
      }
      const search = call(
        context('setup', worker, 'search'),
        origin,
        'POST',
        `/groups/${group.groupId}/searches`,
        group.members[0].memberToken,
        null,
        { revision: group.revision },
      ).state;
      const readState = {
        groupId: group.groupId,
        memberToken: group.members[0].memberToken,
        searchId: search.searchId,
        revision: search.revision,
      };
      call(
        context('setup', worker, 'read'),
        origin,
        'GET',
        `/groups/${group.groupId}/searches/${search.searchId}`,
        readState.memberToken,
        null,
        { searchId: search.searchId, revision: search.revision },
      );
      pools.reads[alias] = readState;
    }
    workers.push(pools);
  }
  return { workers };
}

export default function run(data) {
  const worker = exec.vu.idInTest - 1;
  if (worker < 0 || worker >= plan.vus)
    exec.test.abort('Load worker identity is not supported.');
  const pools = data.workers[worker];
  const origin = exec.scenario.startTime;
  let joins = 0;
  let saves = 0;
  for (
    let ordinal = worker;
    ordinal < plan.arrivals.length;
    ordinal += plan.vus
  ) {
    const arrival = plan.arrivals[ordinal];
    const joinIndex = arrival.op === 'join' ? joins++ : -1;
    const saveIndex = arrival.op === 'save' ? saves++ : -1;
    let now = Date.now() - origin;
    while (now < arrival.at_ms) {
      sleep((arrival.at_ms - now) / 1000);
      now = Date.now() - origin;
    }
    if (now - arrival.at_ms > config.max_lateness_ms) {
      emit(
        projectSample(
          context('measured', worker, arrival.op, arrival),
          {
            start_ms: now,
            end_ms: now,
            duration_ms: 0,
            status: 0,
          },
          { outcome: 'dropped', search_status: 'unknown' },
        ),
      );
      continue;
    }
    if (arrival.op === 'create') create('measured', worker, origin, arrival);
    if (arrival.op === 'join')
      join(
        'measured',
        worker,
        origin,
        pools.joins[Math.floor(joinIndex / 2)],
        (joinIndex % 2) + 1,
        arrival,
      );
    if (arrival.op === 'save')
      save(
        'measured',
        worker,
        origin,
        pools.save,
        pools.save.members[saveIndex % 3],
        arrival.destination,
        arrival,
      );
    if (arrival.op === 'read') {
      const group = pools.reads[arrival.destination];
      call(
        context('measured', worker, 'read', arrival),
        origin,
        'GET',
        `/groups/${group.groupId}/searches/${group.searchId}`,
        group.memberToken,
        null,
        { searchId: group.searchId, revision: group.revision },
      );
    }
  }
}

// Never serialize setupData (which contains in-memory group capabilities).
export function handleSummary() {
  return {};
}
