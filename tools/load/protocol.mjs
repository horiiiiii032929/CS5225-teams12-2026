// Pure validation and evidence projection shared by k6 and Node regression tests.
// No response object, identifier, capability, or input error value is ever projected.
const ALIAS = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const ID = /^[A-Za-z0-9_-]{22}$/;
const SEARCH_ID = /^[A-Za-z0-9_-]{1,64}$/;
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const PLACE = /^[A-Za-z0-9_-]{1,128}$/;
const HASH = /^[a-f0-9]{64}$/;
const OPS = ['create', 'join', 'save', 'read'];
const OUTCOMES = [
  'success',
  'http_error',
  'invalid_response',
  'pending',
  'stale',
  'dropped',
];
const SEARCH_STATUSES = ['complete', 'pending', 'stale', 'unknown'];

function reject() {
  throw new Error('Invalid load input.');
}

function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function exact(value, required, optional = []) {
  if (!object(value)) reject();
  const keys = Object.keys(value);
  if (
    required.some((key) => !Object.prototype.hasOwnProperty.call(value, key)) ||
    keys.some((key) => !required.includes(key) && !optional.includes(key))
  )
    reject();
}

function finite(value, min = -Infinity, max = Infinity) {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= min &&
    value <= max
  );
}

function integer(
  value,
  min = Number.MIN_SAFE_INTEGER,
  max = Number.MAX_SAFE_INTEGER,
) {
  return Number.isSafeInteger(value) && value >= min && value <= max;
}

function text(value, maximum = 256) {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.trim() !== value ||
    value.length > maximum
  )
    return false;
  for (const character of value) {
    const point = character.codePointAt(0);
    if (point < 32 || point === 127 || (point >= 0xd800 && point <= 0xdfff))
      return false;
  }
  return true;
}

// Lossless cross-runtime hash normalization: IEEE-754 binary64, big-endian hex.
// Normalize negative zero, preserve strings/bools/null, and sort object keys.
export function numberHex(value) {
  if (!finite(value)) reject();
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value === 0 ? 0 : value, false);
  return (
    view.getUint32(0, false).toString(16).padStart(8, '0') +
    view.getUint32(4, false).toString(16).padStart(8, '0')
  );
}

export function canonicalJSON(value) {
  if (typeof value === 'number') return JSON.stringify(numberHex(value));
  if (value === null || typeof value === 'boolean' || typeof value === 'string')
    return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(',')}]`;
  if (!object(value)) reject();
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJSON(value[key])}`)
    .join(',')}}`;
}

function ipv4(value) {
  const parts = value.split('.');
  if (
    parts.length !== 4 ||
    parts.some(
      (part) => !/^(?:0|[1-9][0-9]{0,2})$/.test(part) || Number(part) > 255,
    )
  )
    return null;
  return parts.map(Number);
}

function ipv6(value) {
  let address = value;
  if (address.includes('.')) {
    const split = address.lastIndexOf(':');
    const tail = ipv4(address.slice(split + 1));
    if (!tail) return null;
    address = `${address.slice(0, split)}:${(tail[0] * 256 + tail[1]).toString(16)}:${(tail[2] * 256 + tail[3]).toString(16)}`;
  }
  const halves = address.split('::');
  if (halves.length > 2) return null;
  const left = halves[0] ? halves[0].split(':') : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(':') : [];
  if ([...left, ...right].some((part) => !/^[0-9a-f]{1,4}$/i.test(part)))
    return null;
  const missing = 8 - left.length - right.length;
  if (halves.length === 1 ? missing !== 0 : missing < 1) return null;
  return [...left, ...Array(missing).fill('0'), ...right].flatMap((part) => {
    const number = Number.parseInt(part, 16);
    return [number >>> 8, number & 255];
  });
}

function dnsHost(value, publicReference) {
  const host = value.toLowerCase().replace(/\.$/, '');
  if (
    host === 'localhost' ||
    /\.(?:localhost|local)$/.test(host) ||
    host.length > 253 ||
    host
      .split('.')
      .some(
        (label) =>
          !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label),
      )
  )
    reject();
  if (
    publicReference &&
    (!host.includes('.') ||
      /\.(?:internal|invalid|test)$/.test(host) ||
      /^[0-9]+$/.test(host.split('.').pop()))
  )
    reject();
}

function remoteHost(value) {
  const host = value.toLowerCase().replace(/\.$/, '');
  if (host.startsWith('[')) {
    const address = ipv6(host.slice(1, -1));
    if (
      !address ||
      (address.slice(0, 15).every((part) => part === 0) && address[15] <= 1)
    )
      reject();
    // IPv4-mapped loopback/unspecified literals remain local addresses.
    if (
      address.slice(0, 10).every((part) => part === 0) &&
      address[10] === 255 &&
      address[11] === 255 &&
      [0, 127].includes(address[12])
    )
      reject();
  } else if (/^[0-9.]+$/.test(host)) {
    const address = ipv4(host);
    if (!address || [0, 127].includes(address[0])) reject();
  } else {
    dnsHost(host, false);
  }
}

function publicURL(value, local) {
  if (typeof value !== 'string' || /[\s\\]/.test(value)) reject();
  // Deliberately parse the supported grammar, without permissive URL
  // normalization of userinfo or alternate local-address spellings.
  const match =
    /^(https?):\/\/(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::([0-9]{1,5}))?(\/(?:api\/?)?)?$/.exec(
      value,
    );
  if (!match || (match[3] && !integer(Number(match[3]), 1, 65535))) reject();
  if (local) {
    if (
      match[1] !== 'http' ||
      !['localhost', '127.0.0.1', '[::1]'].includes(match[2])
    )
      reject();
  } else {
    if (match[1] !== 'https') reject();
    remoteHost(match[2]);
  }
  return value.replace(/\/$/, '');
}

function receipt(value) {
  if (!text(value, 2048) || /[\s\\?#]/.test(value)) reject();
  const match = /^https:\/\/([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?(?:\/.*)?$/i.exec(
    value,
  );
  if (!match || (match[2] && !integer(Number(match[2]), 1, 65535))) reject();
  dnsHost(match[1], true);
}

export function validateCatalog(catalog) {
  exact(catalog, ['version', 'kind', 'review', 'destinations']);
  if (
    catalog.version !== 1 ||
    !['synthetic-local', 'reviewed-public'].includes(catalog.kind)
  )
    reject();
  exact(catalog.review, ['reviewer', 'revision', 'weight_basis']);
  if (!Object.values(catalog.review).every((value) => text(value, 1024)))
    reject();
  if (
    !Array.isArray(catalog.destinations) ||
    catalog.destinations.length === 0 ||
    (catalog.kind === 'reviewed-public' && catalog.destinations.length !== 30)
  )
    reject();
  const aliases = new Set();
  const receipts = new Set();
  let totalWeight = 0;
  for (const destination of catalog.destinations) {
    exact(destination, [
      'alias',
      'weight',
      'selection_receipt',
      'station',
      'place_ids',
    ]);
    if (
      typeof destination.alias !== 'string' ||
      !ALIAS.test(destination.alias) ||
      aliases.has(destination.alias) ||
      !finite(destination.weight, Number.MIN_VALUE)
    )
      reject();
    aliases.add(destination.alias);
    totalWeight += destination.weight;
    if (!Number.isFinite(totalWeight)) reject();
    exact(destination.station, ['stationKey', 'lat', 'lng']);
    if (
      typeof destination.station.stationKey !== 'string' ||
      !/^[A-Z0-9_]+$/.test(destination.station.stationKey) ||
      !finite(destination.station.lat, -90, 90) ||
      !finite(destination.station.lng, -180, 180)
    )
      reject();
    if (
      !object(destination.place_ids) ||
      Object.keys(destination.place_ids).length === 0
    )
      reject();
    for (const target of Object.keys(destination.place_ids)) {
      if (
        !ALIAS.test(target) ||
        typeof destination.place_ids[target] !== 'string' ||
        !PLACE.test(destination.place_ids[target])
      )
        reject();
    }
    if (catalog.kind === 'synthetic-local') {
      if (destination.selection_receipt !== `synthetic://${destination.alias}`)
        reject();
    } else {
      receipt(destination.selection_receipt);
      if (receipts.has(destination.selection_receipt)) reject();
      receipts.add(destination.selection_receipt);
    }
  }
  return catalog;
}

export function validatePlan(plan, sha256) {
  exact(plan, [
    'version',
    'workload',
    'seed',
    'scale',
    'standard',
    'vus',
    'duration_ms',
    'trace_sha256',
    'catalog_sha256',
    'catalog',
    'arrivals',
  ]);
  if (
    plan.version !== 1 ||
    !['W1', 'W2'].includes(plan.workload) ||
    !integer(plan.seed) ||
    !finite(plan.scale, Number.MIN_VALUE) ||
    typeof plan.standard !== 'boolean' ||
    plan.standard !== (plan.scale === 1) ||
    !integer(plan.vus, 1, 2147483647) ||
    !finite(plan.duration_ms, Number.MIN_VALUE) ||
    typeof plan.trace_sha256 !== 'string' ||
    !HASH.test(plan.trace_sha256) ||
    typeof plan.catalog_sha256 !== 'string' ||
    !HASH.test(plan.catalog_sha256) ||
    typeof sha256 !== 'function'
  )
    reject();
  validateCatalog(plan.catalog);
  if (sha256(canonicalJSON(plan.catalog)) !== plan.catalog_sha256) reject();
  const expectedDuration =
    (plan.workload === 'W1' ? 600000 : 360000) * plan.scale;
  const count =
    plan.workload === 'W1'
      ? Math.floor(1200 * plan.scale)
      : Math.floor((16530 * plan.scale) / 10) * 10;
  if (
    !Number.isSafeInteger(count) ||
    count <= 0 ||
    Math.abs(expectedDuration - plan.duration_ms) > 0.000001 ||
    !Array.isArray(plan.arrivals) ||
    plan.arrivals.length !== count
  )
    reject();
  const aliases = new Set(
    plan.catalog.destinations.map((entry) => entry.alias),
  );
  let previous = -1;
  let block = { create: 0, join: 0, save: 0, read: 0 };
  for (let index = 0; index < count; index += 1) {
    const arrival = plan.arrivals[index];
    exact(arrival, ['ordinal', 'at_ms', 'phase', 'op', 'destination']);
    if (
      arrival.ordinal !== index ||
      !finite(arrival.at_ms, 0, plan.duration_ms) ||
      arrival.at_ms <= previous ||
      !OPS.includes(arrival.op) ||
      !aliases.has(arrival.destination)
    )
      reject();
    let expectedTime;
    let phase;
    if (plan.workload === 'W1') {
      expectedTime = (index + 0.5) * 500;
      phase = 'steady';
      if (arrival.op !== 'read') reject();
    } else {
      const intensity = index + 0.5;
      const rampCount = 1530 * plan.scale;
      if (intensity < rampCount) {
        const slope = 49 / (60 * plan.scale);
        expectedTime =
          ((2 * intensity) / (1 + Math.sqrt(1 + 2 * slope * intensity))) * 1000;
        phase = 'ramp';
      } else {
        expectedTime = (60 * plan.scale + (intensity - rampCount) / 50) * 1000;
        phase = 'hold';
      }
      block[arrival.op] += 1;
      if (index % 10 === 9) {
        if (
          block.create !== 1 ||
          block.join !== 2 ||
          block.save !== 4 ||
          block.read !== 3
        )
          reject();
        block = { create: 0, join: 0, save: 0, read: 0 };
      }
    }
    if (
      arrival.phase !== phase ||
      Math.abs(arrival.at_ms - expectedTime) > 0.000001
    )
      reject();
    previous = arrival.at_ms;
  }
  if (sha256(canonicalJSON(plan.arrivals)) !== plan.trace_sha256) reject();
  return plan;
}

export function poolLayout(plan) {
  const workers = Array.from(
    { length: Math.min(plan.vus, plan.arrivals.length) },
    () => ({ joins: 0, saves: 0, reads: [] }),
  );
  for (const arrival of plan.arrivals) {
    const worker = workers[arrival.ordinal % plan.vus];
    if (arrival.op === 'join') worker.joins += 1;
    if (arrival.op === 'save') worker.saves += 1;
    if (arrival.op === 'read' && !worker.reads.includes(arrival.destination))
      worker.reads.push(arrival.destination);
  }
  return workers;
}

// The scheduled alias supplies member 0. Independently weighted companions
// avoid benchmarking only one shared station partition for a three-member group.
export function readDestinations(plan, worker, primary, sha256) {
  const destinations = plan.catalog.destinations;
  if (!destinations.some((entry) => entry.alias === primary)) reject();
  const maximum = Math.max(...destinations.map((entry) => entry.weight));
  const weights = destinations.map((entry) => entry.weight / maximum);
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  const selected = [primary];
  for (let member = 1; member < 3; member += 1) {
    const digest = sha256(
      `read-members:${plan.seed}:${worker}:${primary}:${member}`,
    );
    let point =
      (Number.parseInt(digest.slice(0, 13), 16) / 0x10000000000000) * total;
    let alias = destinations[destinations.length - 1].alias;
    for (let index = 0; index < destinations.length; index += 1) {
      point -= weights[index];
      if (point < 0) {
        alias = destinations[index].alias;
        break;
      }
    }
    selected.push(alias);
  }
  return selected;
}

export function requestBudget(plan) {
  return (
    plan.arrivals.length +
    poolLayout(plan).reduce(
      (total, worker) =>
        total +
        Math.ceil(worker.joins / 2) +
        (worker.saves > 0 ? 3 : 0) +
        worker.reads.length * 8,
      0,
    )
  );
}

export function validateConfig(config, plan) {
  exact(
    config,
    [
      'mode',
      'run_id',
      'target',
      'base_url',
      'source_revision',
      'max_lateness_ms',
      'timeout_ms',
      'setup_timeout_seconds',
    ],
    ['approval'],
  );
  if (
    !['local', 'eval'].includes(config.mode) ||
    typeof config.run_id !== 'string' ||
    !ALIAS.test(config.run_id) ||
    typeof config.target !== 'string' ||
    !ALIAS.test(config.target) ||
    typeof config.source_revision !== 'string' ||
    !/^[A-Za-z0-9][A-Za-z0-9._+@:/-]{0,255}$/.test(config.source_revision) ||
    !finite(config.max_lateness_ms, 0, 120000) ||
    !finite(config.timeout_ms, 1, 120000) ||
    !finite(config.setup_timeout_seconds, 1, 3600)
  )
    reject();
  publicURL(config.base_url, config.mode === 'local');
  for (const destination of plan.catalog.destinations) {
    if (
      !Object.prototype.hasOwnProperty.call(
        destination.place_ids,
        config.target,
      )
    )
      reject();
  }
  if (config.mode === 'local') {
    if (Object.prototype.hasOwnProperty.call(config, 'approval')) reject();
  } else {
    if (
      !plan.standard ||
      plan.scale !== 1 ||
      plan.catalog.kind !== 'reviewed-public'
    )
      reject();
    exact(config.approval, [
      'operator',
      'stage',
      'reference',
      'stop_reference',
      'client_location',
      'max_requests',
    ]);
    const approval = config.approval;
    if (
      !text(approval.operator) ||
      !text(approval.reference) ||
      !text(approval.stop_reference) ||
      approval.stage !== 'eval' ||
      approval.client_location !== 'Singapore' ||
      !integer(approval.max_requests, 1) ||
      requestBudget(plan) > approval.max_requests
    )
      reject();
  }
  return config;
}

export function apiBase(config) {
  const base = publicURL(config.base_url, config.mode === 'local');
  return base.endsWith('/api') ? base : `${base}/api`;
}

function forbiddenCredentials(value, op, path = '', depth = 0) {
  if (depth > 64) return true;
  if (Array.isArray(value))
    return value.some((entry, index) =>
      forbiddenCredentials(entry, op, `${path}.${index}`, depth + 1),
    );
  if (!object(value)) return false;
  for (const key of Object.keys(value)) {
    const next = path ? `${path}.${key}` : key;
    const normalized = key.toLowerCase().replace(/[^a-z0-9]/g, '');
    const allowed =
      ((op === 'create' || op === 'join') && next === 'memberToken') ||
      (op === 'create' && next === 'group.inviteToken');
    if (
      !allowed &&
      /token|secret|credential|password|authorization|cookie|apikey|accesskey|privatekey|signature/.test(
        normalized,
      )
    )
      return true;
    if (forbiddenCredentials(value[key], op, next, depth + 1)) return true;
  }
  return false;
}

function groupState(group, expected) {
  if (
    !object(group) ||
    typeof group.groupId !== 'string' ||
    !ID.test(group.groupId) ||
    !integer(group.revision, 1) ||
    group.size !== 3 ||
    !Array.isArray(group.members) ||
    group.members.length < 1 ||
    group.members.length > 3 ||
    !integer(group.readyCount, 0, 3) ||
    typeof group.allReady !== 'boolean'
  )
    return false;
  if (
    expected.memberCount !== undefined &&
    group.members.length !== expected.memberCount
  )
    return false;
  if (expected.groupId && group.groupId !== expected.groupId) return false;
  if (expected.revision !== undefined && group.revision !== expected.revision)
    return false;
  const ids = new Set();
  for (const member of group.members) {
    if (
      !object(member) ||
      typeof member.memberId !== 'string' ||
      !ID.test(member.memberId) ||
      ids.has(member.memberId) ||
      typeof member.ready !== 'boolean' ||
      !text(member.name, 30)
    )
      return false;
    ids.add(member.memberId);
  }
  if (
    group.readyCount !==
      group.members.filter((member) => member.ready).length ||
    group.allReady !== (group.members.length === 3 && group.readyCount === 3)
  )
    return false;
  return true;
}

// The returned state is private in-memory request state, NOT an evidence row.
// Only projectSample/projectManifest may be passed to console/metrics.
export function inspectResponse(op, status, raw, expected = {}) {
  const invalid = {
    outcome: 'invalid_response',
    search_status: 'unknown',
    state: null,
  };
  if (!integer(status, 0, 599)) return invalid;
  if (status < 200 || status >= 300)
    return { outcome: 'http_error', search_status: 'unknown', state: null };
  let body;
  try {
    body = typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch {
    return invalid;
  }
  if (!object(body) || forbiddenCredentials(body, op)) return invalid;
  if (op === 'create' || op === 'join') {
    if (
      status !== 201 ||
      !groupState(body.group, expected) ||
      typeof body.memberId !== 'string' ||
      !ID.test(body.memberId) ||
      typeof body.memberToken !== 'string' ||
      !TOKEN.test(body.memberToken) ||
      !body.group.members.some(
        (member) =>
          member.memberId === body.memberId &&
          (!expected.name || member.name === expected.name),
      ) ||
      (op === 'create' &&
        (typeof body.group.inviteToken !== 'string' ||
          !TOKEN.test(body.group.inviteToken))) ||
      (op === 'join' &&
        Object.prototype.hasOwnProperty.call(body.group, 'inviteToken'))
    )
      return invalid;
    return {
      outcome: 'success',
      search_status: 'unknown',
      state: {
        groupId: body.group.groupId,
        revision: body.group.revision,
        memberId: body.memberId,
        memberToken: body.memberToken,
        inviteToken: op === 'create' ? body.group.inviteToken : null,
      },
    };
  }
  if (op === 'save') {
    if (status !== 200 || !groupState(body.group, expected)) return invalid;
    const member = body.group.members.find(
      (entry) => entry.memberId === expected.memberId,
    );
    if (
      !member ||
      !member.ready ||
      member.name !== expected.name ||
      member.budget !== 5000 ||
      member.maxCommute !== 120 ||
      !object(member.destination) ||
      !object(member.destination.station) ||
      !object(expected.station) ||
      (Object.prototype.hasOwnProperty.call(member.destination, 'placeId') &&
        member.destination.placeId !== expected.placeId) ||
      member.destination.station.stationKey !== expected.station.stationKey ||
      !finite(member.destination.station.lat, -90, 90) ||
      !finite(member.destination.station.lng, -180, 180) ||
      Math.abs(member.destination.station.lat - expected.station.lat) >
        0.000000001 ||
      Math.abs(member.destination.station.lng - expected.station.lng) >
        0.000000001
    )
      return invalid;
    return {
      outcome: 'success',
      search_status: 'unknown',
      state: { revision: body.group.revision },
    };
  }
  if (op !== 'search' && op !== 'read') return invalid;
  if (
    (op === 'read' && status !== 200) ||
    (op === 'search' && ![200, 201, 202].includes(status)) ||
    typeof body.searchId !== 'string' ||
    !SEARCH_ID.test(body.searchId) ||
    !integer(body.groupRevision, 1) ||
    (expected.searchId && body.searchId !== expected.searchId) ||
    !SEARCH_STATUSES.slice(0, 3).includes(body.status) ||
    !Array.isArray(body.ranked) ||
    !object(body.progress) ||
    !integer(body.progress.total, 0) ||
    !integer(body.progress.resolved, 0, body.progress.total) ||
    !integer(body.progress.unavailable, 0, body.progress.resolved)
  )
    return invalid;
  if (
    body.status === 'stale' ||
    (expected.revision !== undefined &&
      body.groupRevision !== expected.revision)
  ) {
    return { outcome: 'stale', search_status: 'stale', state: null };
  }
  if (body.status === 'pending') {
    if (
      body.progress.total === 0 ||
      body.progress.resolved === body.progress.total ||
      body.ranked.length !== 0
    )
      return invalid;
    return { outcome: 'pending', search_status: 'pending', state: null };
  }
  if (
    body.progress.total === 0 ||
    body.progress.resolved !== body.progress.total ||
    body.ranked.length === 0 ||
    !body.ranked.every(
      (entry) =>
        object(entry) && text(entry.town, 128) && integer(entry.rank, 1),
    )
  )
    return invalid;
  return {
    outcome: 'success',
    search_status: 'complete',
    state: { searchId: body.searchId, revision: body.groupRevision },
  };
}

export function projectManifest(plan, config, startUTC) {
  if (
    typeof startUTC !== 'string' ||
    !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(startUTC)
  )
    reject();
  return {
    kind: 'manifest',
    run_id: config.run_id,
    target: config.target,
    workload: plan.workload,
    mode: config.mode,
    seed: plan.seed,
    trace_sha256: plan.trace_sha256,
    catalog_sha256: plan.catalog_sha256,
    source_revision: config.source_revision,
    standard: plan.standard,
    vus: plan.vus,
    duration_ms: plan.duration_ms,
    start_utc: startUTC,
  };
}

export function projectSample(context, timing, classification) {
  if (
    typeof context.run_id !== 'string' ||
    !ALIAS.test(context.run_id) ||
    typeof context.target !== 'string' ||
    !ALIAS.test(context.target) ||
    !['setup', 'measured'].includes(context.phase) ||
    !['setup', 'warm-complete', 'mixed'].includes(context.cohort) ||
    !['create', 'join', 'save', 'search', 'read'].includes(context.op) ||
    !integer(context.worker, 0) ||
    !OUTCOMES.includes(classification.outcome) ||
    !SEARCH_STATUSES.includes(classification.search_status) ||
    !finite(timing.start_ms, 0) ||
    !finite(timing.end_ms, timing.start_ms) ||
    !finite(timing.duration_ms, 0) ||
    Math.abs(timing.end_ms - timing.start_ms - timing.duration_ms) > 0.000001 ||
    !integer(timing.status, 0, 599)
  )
    reject();
  if (
    context.phase === 'setup'
      ? context.ordinal !== null ||
        context.planned_ms !== null ||
        context.cohort !== 'setup'
      : !integer(context.ordinal, 0) ||
        !finite(context.planned_ms, 0) ||
        context.cohort !== (context.op === 'read' ? 'warm-complete' : 'mixed')
  )
    reject();
  if (
    classification.outcome === 'dropped' &&
    (context.phase !== 'measured' ||
      timing.status !== 0 ||
      timing.duration_ms !== 0 ||
      timing.start_ms !== timing.end_ms)
  )
    reject();
  const successfulHTTP = timing.status >= 200 && timing.status < 300;
  const search = context.op === 'read' || context.op === 'search';
  if (
    (classification.outcome === 'success' &&
      (!successfulHTTP ||
        classification.search_status !== (search ? 'complete' : 'unknown'))) ||
    (classification.outcome === 'http_error' &&
      (successfulHTTP || classification.search_status !== 'unknown')) ||
    (classification.outcome === 'invalid_response' &&
      (!successfulHTTP || classification.search_status !== 'unknown')) ||
    (['pending', 'stale'].includes(classification.outcome) &&
      (!successfulHTTP ||
        !search ||
        classification.search_status !== classification.outcome)) ||
    (classification.outcome === 'dropped' &&
      classification.search_status !== 'unknown')
  )
    reject();
  return {
    kind: 'sample',
    run_id: context.run_id,
    target: context.target,
    phase: context.phase,
    cohort: context.cohort,
    ordinal: context.ordinal,
    op: context.op,
    planned_ms: context.planned_ms,
    start_ms: timing.start_ms,
    end_ms: timing.end_ms,
    duration_ms: timing.duration_ms,
    status: timing.status,
    outcome: classification.outcome,
    search_status: classification.search_status,
    worker: context.worker,
  };
}
