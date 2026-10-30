import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  apiBase,
  canonicalJSON,
  inspectResponse,
  numberHex,
  poolLayout,
  projectManifest,
  projectSample,
  requestBudget,
  readDestinations,
  validateCatalog,
  validateConfig,
  validatePlan,
} from '../protocol.mjs';

const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const copy = (value) => structuredClone(value);
const groupID = 'g'.repeat(22);
const searchID = `s_${'s'.repeat(22)}`;
const capability = 'T'.repeat(43);
const marker = 'PRIVATE_RESPONSE_MARKER';

function catalog(reviewed = false) {
  return {
    version: 1,
    kind: reviewed ? 'reviewed-public' : 'synthetic-local',
    review: {
      reviewer: 'operator',
      revision: 'review1',
      weight_basis: 'public selection',
    },
    destinations: Array.from({ length: reviewed ? 30 : 2 }, (_, index) => ({
      alias: `destination${index}`,
      weight: index + 1,
      selection_receipt: reviewed
        ? `https://example.org/destinations/${index}`
        : `synthetic://destination${index}`,
      station: {
        stationKey: `STATION_${index}`,
        lat: 1.29330347372,
        lng: 103.784516185,
      },
      place_ids: {
        local: `persisted_place_${index}`,
        eval: `eval_place_${index}`,
      },
    })),
  };
}

function seal(plan) {
  plan.trace_sha256 = sha256(canonicalJSON(plan.arrivals));
  plan.catalog_sha256 = sha256(canonicalJSON(plan.catalog));
  return plan;
}

function plan(workload = 'W1', scale = 0.01, reviewed = false) {
  const destinations = catalog(reviewed);
  const count =
    workload === 'W1'
      ? Math.floor(1200 * scale)
      : Math.floor((16530 * scale) / 10) * 10;
  const block = [
    'create',
    'join',
    'join',
    'save',
    'save',
    'save',
    'save',
    'read',
    'read',
    'read',
  ];
  const arrivals = Array.from({ length: count }, (_, ordinal) => {
    const intensity = ordinal + 0.5;
    const ramp = intensity < 1530 * scale;
    const slope = 49 / (60 * scale);
    const at =
      workload === 'W1'
        ? intensity * 500
        : ramp
          ? ((2 * intensity) / (1 + Math.sqrt(1 + 2 * slope * intensity))) *
            1000
          : (60 * scale + (intensity - 1530 * scale) / 50) * 1000;
    return {
      ordinal,
      at_ms: Number(at.toFixed(9)),
      phase: workload === 'W1' ? 'steady' : ramp ? 'ramp' : 'hold',
      op: workload === 'W1' ? 'read' : block[ordinal % 10],
      destination:
        destinations.destinations[ordinal % destinations.destinations.length]
          .alias,
    };
  });
  return seal({
    version: 1,
    workload,
    seed: -522530,
    scale,
    standard: scale === 1,
    vus: 2,
    duration_ms: (workload === 'W1' ? 600000 : 360000) * scale,
    trace_sha256: '',
    catalog_sha256: '',
    catalog: destinations,
    arrivals,
  });
}

function config(mode = 'local') {
  const value = {
    mode,
    run_id: 'runA',
    target: mode,
    base_url:
      mode === 'local' ? 'http://127.0.0.1:8000' : 'https://eval.example.org',
    source_revision: 'source-abc123',
    max_lateness_ms: 100,
    timeout_ms: 10000,
    setup_timeout_seconds: 120,
  };
  if (mode === 'eval')
    value.approval = {
      operator: 'approved operator',
      stage: 'eval',
      reference: 'approval-ref',
      stop_reference: 'stop-ref',
      client_location: 'Singapore',
      max_requests: 100000,
    };
  return value;
}

function rejectsSafely(action) {
  assert.throws(
    action,
    (error) =>
      error instanceof Error && error.message === 'Invalid load input.',
  );
}

function group(count = 1, revision = 1, ready = false) {
  return {
    groupId: groupID,
    size: 3,
    revision,
    readyCount: ready ? count : 0,
    allReady: ready && count === 3,
    members: Array.from({ length: count }, (_, index) => ({
      memberId: String(index).repeat(22),
      name: `loadMember${index}`,
      ready,
      destination: ready
        ? {
            placeId: 'persisted_place_0',
            station: {
              stationKey: 'STATION_0',
              lat: 1.29330347372,
              lng: 103.784516185,
            },
          }
        : null,
      budget: ready ? 5000 : null,
      maxCommute: ready ? 120 : null,
    })),
  };
}

function membership(op = 'create') {
  const value = {
    group: group(op === 'create' ? 1 : 2, op === 'create' ? 1 : 2),
    memberId: (op === 'create' ? '0' : '1').repeat(22),
    memberToken: capability,
  };
  if (op === 'create') value.group.inviteToken = 'I'.repeat(43);
  return value;
}

function result() {
  return {
    searchId: searchID,
    groupRevision: 6,
    status: 'complete',
    progress: { total: 54, resolved: 54, unavailable: 2 },
    ranked: [{ town: 'QUEENSTOWN', rank: 1 }],
  };
}

function sample(classification, extra = {}) {
  return projectSample(
    {
      run_id: 'runA',
      target: 'local',
      phase: 'measured',
      cohort: 'warm-complete',
      ordinal: 0,
      op: 'read',
      planned_ms: 250,
      worker: 0,
      ...extra,
    },
    { start_ms: 251, end_ms: 259, duration_ms: 8, status: 200 },
    classification,
  );
}

test('canonical hashes preserve native numeric precision, Unicode and signed-zero equivalence', () => {
  assert.equal(numberHex(1), '3ff0000000000000');
  assert.equal(numberHex(-0), '0000000000000000');
  assert.equal(numberHex(Number.MIN_VALUE), '0000000000000001');
  assert.equal(numberHex(Number.MAX_VALUE), '7fefffffffffffff');
  assert.equal(
    canonicalJSON({ z: true, a: [1, '1', '目的地', null] }),
    '{"a":["3ff0000000000000","1","目的地",null],"z":true}',
  );
  assert.equal(
    sha256(canonicalJSON({ b: -0, a: 1.0 })),
    sha256(canonicalJSON({ a: 1, b: 0 })),
  );
  assert.notEqual(
    sha256(canonicalJSON({ lat: 1.29330347372 })),
    sha256(canonicalJSON({ lat: 1.29330347373 })),
  );
  rejectsSafely(() => canonicalJSON({ value: Infinity }));
});

test('valid workload traces accept signed seeds, rounded times and pinned catalog hashes', () => {
  for (const workload of ['W1', 'W2']) {
    const value = plan(workload);
    assert.equal(validatePlan(value, sha256), value);
    assert.equal(validateConfig(config(), value).mode, 'local');
  }
});

test('plan mutations fail before network even when a caller recomputes the digest', () => {
  const changes = [
    (value) => {
      value.arrivals[0].at_ms += 1;
    },
    (value) => {
      value.arrivals[1].ordinal = 0;
    },
    (value) => {
      value.arrivals[0].phase = 'hold';
    },
    (value) => {
      value.arrivals[0].destination = 'unknown';
    },
    (value) => {
      value.arrivals[0].op = 'join';
    },
    (value) => {
      value.arrivals[0].authorization = marker;
    },
    (value) => {
      value.duration_ms += 1;
    },
    (value) => {
      value.standard = true;
    },
    (value) => {
      value.vus = true;
    },
    (value) => {
      value.seed = Number.MAX_SAFE_INTEGER + 1;
    },
    (value) => {
      value.secret = marker;
    },
  ];
  for (const change of changes) {
    const value = plan();
    change(value);
    seal(value);
    rejectsSafely(() => validatePlan(value, sha256));
  }
  const wrongBlock = plan('W2');
  wrongBlock.arrivals[0].op = 'read';
  rejectsSafely(() => validatePlan(seal(wrongBlock), sha256));
  const wrongHash = plan();
  wrongHash.catalog.destinations[0].station.lat += 0.00000000001;
  rejectsSafely(() => validatePlan(wrongHash, sha256));
  const missingCatalog = plan();
  missingCatalog.catalog = null;
  rejectsSafely(() => validatePlan(missingCatalog, sha256));
});

test('catalog refuses malformed coordinates, unsafe receipts and credential-shaped extra keys', () => {
  const changes = [
    (value) => {
      value.destinations[0].weight = true;
    },
    (value) => {
      value.destinations[0].weight = NaN;
    },
    (value) => {
      value.destinations[0].station.lat = Infinity;
    },
    (value) => {
      value.destinations[0].station.lng = 181;
    },
    (value) => {
      value.destinations[0].station.token = marker;
    },
    (value) => {
      value.review.password = marker;
    },
    (value) => {
      value.destinations[0].place_ids = {};
    },
    (value) => {
      value.destinations[1].alias = value.destinations[0].alias;
    },
    (value) => {
      value.destinations[0].selection_receipt = 'synthetic://other';
    },
    (value) => {
      value.destinations.forEach((destination) => {
        destination.weight = Number.MAX_VALUE;
      });
    },
  ];
  for (const change of changes) {
    const value = catalog();
    change(value);
    rejectsSafely(() => validateCatalog(value));
  }
  for (const url of [
    'https://user:password@example.org/a',
    'https://example.org/a?q=private',
    'https://example.org/a#private',
    'https://localhost/a',
    'http://example.org/a',
  ]) {
    const value = catalog(true);
    value.destinations[0].selection_receipt = url;
    rejectsSafely(() => validateCatalog(value));
  }
  const duplicateReceipt = catalog(true);
  duplicateReceipt.destinations[1].selection_receipt =
    duplicateReceipt.destinations[0].selection_receipt;
  rejectsSafely(() => validateCatalog(duplicateReceipt));
  const precision = catalog();
  precision.destinations[0].weight = Number.MIN_VALUE;
  assert.equal(validateCatalog(precision), precision);
});

test('local target grammar rejects remote, alternate-loopback and path/credential misuse', () => {
  const value = plan();
  for (const base_url of [
    'https://127.0.0.1',
    'http://example.org',
    'http://127.1',
    'http://2130706433',
    'http://0x7f000001',
    'http://127.000.000.001',
    'http://localhost.example.org',
    'http://localhost.',
    'http://user:private@localhost',
    'http://localhost/api?token=private',
    'http://localhost/api#private',
    'http://localhost/other',
    'http://localhost//api',
    'http://localhost:0',
    'http://localhost:65536',
    'http://[::ffff:127.0.0.1]',
    'http://localhost\\@example.org',
    'http://localhost\n',
  ]) {
    rejectsSafely(() => validateConfig({ ...config(), base_url }, value));
  }
  for (const base_url of [
    'http://localhost',
    'http://127.0.0.1:8080/',
    'http://[::1]:8080/api',
    'http://localhost/api/',
  ]) {
    const safe = { ...config(), base_url };
    assert.equal(validateConfig(safe, value), safe);
    assert.ok(apiBase(safe).endsWith('/api'));
  }
});

test('run configuration rejects extra secrets, malformed numbers and missing target mappings', () => {
  const value = plan();
  for (const extra of [
    { token: marker },
    { timeout_ms: true },
    { timeout_ms: 0 },
    { timeout_ms: Infinity },
    { max_lateness_ms: -1 },
    { setup_timeout_seconds: 0 },
    { run_id: marker + '/private' },
    { source_revision: 'revision\nprivate' },
    { target: 'missing' },
    { approval: { operator: marker } },
  ]) {
    rejectsSafely(() => validateConfig({ ...config(), ...extra }, value));
  }
});

test('eval is gated by full standard workload, public catalog and inclusive setup request ceiling', () => {
  const value = plan('W1', 1, true);
  validatePlan(value, sha256);
  const approved = config('eval');
  const count = requestBudget(value);
  assert.equal(count, 1440);
  approved.approval.max_requests = count;
  assert.equal(validateConfig(approved, value), approved);
  approved.approval.max_requests -= 1;
  rejectsSafely(() => validateConfig(approved, value));
  rejectsSafely(() => validateConfig(config('eval'), plan('W1', 0.01, true)));
  rejectsSafely(() => validateConfig(config('eval'), plan('W1', 1, false)));
  for (const extra of [
    { approval: undefined },
    { base_url: 'https://localhost' },
    { base_url: 'http://eval.example.org' },
  ]) {
    rejectsSafely(() => validateConfig({ ...config('eval'), ...extra }, value));
  }
  const wrongLocation = config('eval');
  wrongLocation.approval.client_location = 'elsewhere';
  rejectsSafely(() => validateConfig(wrongLocation, value));
});

test('separate pool allocation budgets paired joins, independent saves and each read destination', () => {
  const value = {
    vus: 2,
    arrivals: [
      { ordinal: 0, op: 'join', destination: 'a' },
      { ordinal: 1, op: 'save', destination: 'a' },
      { ordinal: 2, op: 'join', destination: 'a' },
      { ordinal: 3, op: 'read', destination: 'a' },
      { ordinal: 4, op: 'join', destination: 'b' },
      { ordinal: 5, op: 'read', destination: 'b' },
      { ordinal: 6, op: 'read', destination: 'a' },
    ],
  };
  assert.deepEqual(poolLayout(value), [
    { joins: 3, saves: 0, reads: ['a'] },
    { joins: 0, saves: 1, reads: ['a', 'b'] },
  ]);
  assert.equal(requestBudget(value), 36);
});

test('create/join accept only known capability locations and internally retain valid auth', () => {
  const created = inspectResponse('create', 201, membership(), {
    revision: 1,
    memberCount: 1,
    name: 'loadMember0',
  });
  assert.equal(created.outcome, 'success');
  assert.equal(created.state.memberToken, capability);
  assert.equal(created.state.inviteToken, 'I'.repeat(43));
  const joined = inspectResponse('join', 201, membership('join'), {
    groupId: groupID,
    revision: 2,
    memberCount: 2,
    name: 'loadMember1',
  });
  assert.equal(joined.outcome, 'success');
  assert.equal(joined.state.inviteToken, null);
  const afterMissedFirstJoin = membership('join');
  afterMissedFirstJoin.group.members[1].name = 'loadMember2';
  assert.equal(
    inspectResponse('join', 201, afterMissedFirstJoin, {
      groupId: groupID,
      revision: 2,
      memberCount: 2,
      name: 'loadMember2',
    }).outcome,
    'success',
  );
  const wrongLocation = membership();
  wrongLocation.inviteToken = wrongLocation.group.inviteToken;
  delete wrongLocation.group.inviteToken;
  assert.equal(
    inspectResponse('create', 201, wrongLocation).outcome,
    'invalid_response',
  );
  const extraNested = membership();
  extraNested.group.members[0].memberToken = marker;
  assert.equal(
    inspectResponse('create', 201, extraNested).outcome,
    'invalid_response',
  );
  const shortToken = membership();
  shortToken.memberToken = marker;
  assert.equal(
    inspectResponse('create', 201, shortToken).outcome,
    'invalid_response',
  );
  const duplicate = membership('join');
  duplicate.group.members[1].memberId = duplicate.group.members[0].memberId;
  assert.equal(
    inspectResponse('join', 201, duplicate).outcome,
    'invalid_response',
  );
  for (const field of ['memberToken', 'memberId']) {
    const malformed = membership();
    malformed[field] = [malformed[field]];
    assert.equal(
      inspectResponse('create', 201, malformed).outcome,
      'invalid_response',
    );
  }
});

test('save success confirms persisted selected destination, readiness and next group revision', () => {
  const expected = {
    groupId: groupID,
    revision: 7,
    memberId: '1'.repeat(22),
    name: 'loadMember1',
    placeId: 'persisted_place_0',
    station: {
      stationKey: 'STATION_0',
      lat: 1.29330347372,
      lng: 103.784516185,
    },
  };
  const saved = { group: group(3, 7, true) };
  assert.equal(
    inspectResponse('save', 200, saved, expected).outcome,
    'success',
  );
  for (const mutate of [
    (value) => {
      value.group.revision = 6;
    },
    (value) => {
      value.group.members[1].destination.placeId = 'wrong_place';
    },
    (value) => {
      value.group.members[1].budget = 4999;
    },
    (value) => {
      value.group.members[1].destination.station.lat += 0.000001;
    },
    (value) => {
      value.group.members[1].destination.station.lng = true;
    },
    (value) => {
      value.group.members[1].destination.station.stationKey = 'WRONG_STATION';
    },
    (value) => {
      value.group.members[1].ready = false;
    },
  ]) {
    const changed = copy(saved);
    mutate(changed);
    assert.equal(
      inspectResponse('save', 200, changed, expected).outcome,
      'invalid_response',
    );
  }
});

test('read transitions distinguish complete eligibility, pending, stale, fast errors and malformed data', () => {
  const expected = { searchId: searchID, revision: 6 };
  assert.equal(
    inspectResponse('read', 200, result(), expected).outcome,
    'success',
  );
  assert.equal(
    inspectResponse('search', 201, result(), { revision: 6 }).outcome,
    'success',
  );
  const pending = {
    ...result(),
    status: 'pending',
    progress: { total: 54, resolved: 2, unavailable: 2 },
    ranked: [],
  };
  assert.deepEqual(inspectResponse('read', 200, pending, expected), {
    outcome: 'pending',
    search_status: 'pending',
    state: null,
  });
  assert.equal(
    inspectResponse('search', 202, pending, { revision: 6 }).outcome,
    'pending',
  );
  assert.equal(
    inspectResponse('read', 200, { ...result(), groupRevision: 5 }, expected)
      .outcome,
    'stale',
  );
  assert.equal(
    inspectResponse(
      'read',
      200,
      {
        ...result(),
        status: 'stale',
        ranked: [],
        progress: { total: 0, resolved: 0, unavailable: 0 },
      },
      expected,
    ).outcome,
    'stale',
  );
  for (const status of [0, 301, 400, 401, 409, 429, 503]) {
    assert.deepEqual(inspectResponse('read', status, marker, expected), {
      outcome: 'http_error',
      search_status: 'unknown',
      state: null,
    });
  }
  const malformed = [
    null,
    true,
    [],
    '{broken',
    { ...result(), ranked: [] },
    { ...result(), searchId: 'x'.repeat(22) },
    { ...result(), searchId: [searchID] },
    { ...result(), searchId: '../private' },
    { ...result(), progress: { total: 54, resolved: 53, unavailable: 0 } },
    { ...result(), progress: { total: 54, resolved: 2, unavailable: 3 } },
    { ...pending, progress: { total: 54, resolved: 54, unavailable: 0 } },
    { ...result(), ranked: [{ town: 'QUEENSTOWN', rank: 0 }] },
  ];
  for (const body of malformed)
    assert.equal(
      inspectResponse('read', 200, body, expected).outcome,
      'invalid_response',
    );
});

test('malformed nested counters and credentials never enter evidence or exception strings', () => {
  const expected = { searchId: searchID, revision: 6 };
  for (const body of [
    {
      ...result(),
      progress: {
        total: 54,
        resolved: 54,
        unavailable: { memberToken: marker },
      },
    },
    { ...result(), diagnostic: { nested: [{ authorization: marker }] } },
    {
      ...result(),
      progress: { total: 54, resolved: 54, unavailable: { detail: marker } },
    },
  ]) {
    const classification = inspectResponse(
      'read',
      200,
      JSON.stringify(body),
      expected,
    );
    assert.equal(classification.outcome, 'invalid_response');
    const projected = sample(classification, {
      response: body,
      detail: marker,
    });
    assert.ok(!JSON.stringify(projected).includes(marker));
    assert.ok(!JSON.stringify(projected).includes('authorization'));
  }
  const created = inspectResponse('create', 201, membership(), { revision: 1 });
  const projected = sample(created, { op: 'create', cohort: 'mixed' });
  assert.ok(!JSON.stringify(projected).includes(capability));
  assert.ok(!JSON.stringify(projected).includes(groupID));
  assert.ok(!Object.hasOwn(projected, 'state'));
});

test('fixed evidence manifests omit config approval/targets and dropped rows have no HTTP duration', () => {
  const value = plan();
  const settings = { ...config(), arbitrary: marker };
  const manifest = projectManifest(value, settings, '2026-10-28T00:00:00.000Z');
  assert.ok(!JSON.stringify(manifest).includes(marker));
  assert.ok(!Object.hasOwn(manifest, 'base_url'));
  const dropped = projectSample(
    {
      run_id: 'runA',
      target: 'local',
      phase: 'measured',
      cohort: 'warm-complete',
      ordinal: 0,
      op: 'read',
      planned_ms: 250,
      worker: 0,
    },
    { start_ms: 300, end_ms: 300, duration_ms: 0, status: 0 },
    { outcome: 'dropped', search_status: 'unknown' },
  );
  assert.equal(dropped.outcome, 'dropped');
  rejectsSafely(() =>
    projectSample(
      { ...dropped },
      { start_ms: 300, end_ms: 301, duration_ms: 1, status: 0 },
      { outcome: 'dropped', search_status: 'unknown' },
    ),
  );
});

test('evidence refuses invalid outcome/status transitions rather than miscounting fast failures', () => {
  rejectsSafely(() =>
    sample({ outcome: 'http_error', search_status: 'unknown' }),
  );
  rejectsSafely(() => sample({ outcome: 'success', search_status: 'unknown' }));
  rejectsSafely(() =>
    sample({ outcome: 'pending', search_status: 'complete' }),
  );
  rejectsSafely(() =>
    sample(
      { outcome: 'stale', search_status: 'stale' },
      { op: 'save', cohort: 'mixed' },
    ),
  );
  rejectsSafely(() => sample({ outcome: 'dropped', search_status: 'unknown' }));
});

test('read cohorts use reproducible weighted member destinations rather than one forced station', () => {
  const value = plan();
  const aliases = new Set(
    value.catalog.destinations.map((entry) => entry.alias),
  );
  const selections = Array.from({ length: 100 }, (_, worker) =>
    readDestinations(value, worker, 'destination0', sha256),
  );
  assert.deepEqual(
    selections,
    Array.from({ length: 100 }, (_, worker) =>
      readDestinations(copy(value), worker, 'destination0', sha256),
    ),
  );
  assert.ok(
    selections.every(
      (members) =>
        members[0] === 'destination0' &&
        members.every((alias) => aliases.has(alias)),
    ),
  );
  const companions = selections.flatMap((members) => members.slice(1));
  const second = companions.filter((alias) => alias === 'destination1').length;
  assert.ok(second > 100 && second < 170);
  rejectsSafely(() => readDestinations(value, 0, 'unknown', sha256));
});
