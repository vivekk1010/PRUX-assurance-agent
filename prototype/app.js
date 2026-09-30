const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

let fixture;
let activeProfile;

function percentile(values, percent) {
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * percent / 100;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return Math.round(sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower));
}

function profileStats(values) {
  return {
    p50: percentile(values, 50),
    p90: percentile(values, 90),
    p95: percentile(values, 95)
  };
}

function profilesForScope() {
  const scope = $('input[name="scope"]:checked').value;
  return fixture.profiles.filter(profile => profile.type === scope);
}

function fillProfiles(preferredId) {
  const profiles = profilesForScope();
  const select = $('#profile');
  select.innerHTML = profiles.map(profile =>
    `<option value="${profile.id}">${profile.name} · ${profile.target}</option>`
  ).join('');
  select.value = profiles.some(profile => profile.id === preferredId) ? preferredId : profiles[0]?.id;
  chooseProfile();
}

function chooseProfile() {
  activeProfile = fixture.profiles.find(profile => profile.id === $('#profile').value);
  if (!activeProfile) return;
  $('#profile-note').textContent = activeProfile.description;
  $('#iterations').value = activeProfile.iterations;
  $('#virtual-users').value = activeProfile.virtualUsers;
  for (const percentile of ['p50', 'p90', 'p95']) {
    $(`#budget-${percentile}`).value = activeProfile.budgets[percentile];
  }
  clearMetrics();
}

function clearMetrics() {
  $$('.metric').forEach(card => {
    $('.metric-value', card).textContent = '—';
    $('.golden-value', card).textContent = '—';
    $('.budget-badge', card).textContent = '';
    $('.budget-badge', card).className = 'budget-badge';
    $('.current-bar', card).style.height = '0';
    $('.golden-bar', card).style.height = '0';
  });
  $('#trace-toggle').disabled = true;
  $('#trace-panel').hidden = true;
  setStatus('READY', 'ready');
}

function setStatus(text, kind) {
  const status = $('#run-status');
  status.textContent = text;
  status.className = `status-chip ${kind}`;
}

function deterministicSamples(profile, count) {
  const source = profile.samples;
  return Array.from({length: count}, (_, index) => {
    const base = source[index % source.length];
    const cycle = Math.floor(index / source.length);
    return Math.max(1, Math.round(base * (1 + cycle * .012)));
  });
}

async function runPrototype() {
  const button = $('#run-button');
  const count = Math.max(3, Math.min(25, Number($('#iterations').value) || activeProfile.iterations));
  const values = deterministicSamples(activeProfile, count);
  button.disabled = true;
  $('#run-label').textContent = 'Measuring…';
  setStatus('RUNNING', 'running');
  $('#progress-title').textContent = `${activeProfile.name} · controlled ${activeProfile.type} pass`;
  $('#progress-count').textContent = `0 / ${count}`;
  $('#progress-bar').style.width = '0';
  $('#iteration-dots').innerHTML = Array.from({length: count}, () => '<i></i>').join('');

  for (let index = 0; index < count; index++) {
    await sleep(210);
    $$('.iteration-dots i')[index].classList.add('done');
    $('#progress-count').textContent = `${index + 1} / ${count}`;
    $('#progress-bar').style.width = `${(index + 1) / count * 100}%`;
  }

  const stats = profileStats(values);
  let failed = false;
  for (const percentile of ['p50', 'p90', 'p95']) {
    const card = $(`.metric[data-percentile="${percentile}"]`);
    const budget = Number($(`#budget-${percentile}`).value);
    const current = stats[percentile];
    const golden = activeProfile.golden[percentile];
    const passed = current <= budget;
    failed ||= !passed;
    $('.metric-value', card).textContent = `${current} ms`;
    $('.golden-value', card).textContent = `${golden} ms`;
    const badge = $('.budget-badge', card);
    badge.textContent = passed ? 'WITHIN' : 'OVER';
    badge.className = `budget-badge ${passed ? 'pass' : 'fail'}`;
    const ceiling = Math.max(current, golden, budget) * 1.12;
    $('.current-bar', card).style.height = `${Math.max(8, current / ceiling * 34)}px`;
    $('.golden-bar', card).style.height = `${Math.max(8, golden / ceiling * 34)}px`;
  }
  const slowest = Math.max(...values);
  $('#trace-summary-text').textContent = `${slowest} ms · ${activeProfile.trace.services.length} correlated spans`;
  $('#trace-toggle').disabled = false;
  setStatus(failed ? 'REGRESSION' : 'PASS', failed ? 'fail' : 'pass');
  $('#run-label').textContent = 'Run sample test';
  button.disabled = false;
  showToast(failed ? 'Budget regression found — trace is ready.' : 'All configured budgets passed.');
}

function renderTrace() {
  const trace = activeProfile.trace;
  $('#trace-id').textContent = trace.id;
  $('#axis-max').textContent = `${trace.duration} ms`;
  $('#spans').innerHTML = trace.services.map(span => `
    <div class="span-row" title="${span.detail}">
      <span>${span.name}</span>
      <span class="span-track">
        <i class="span-bar ${span.color}" style="left:${span.start / trace.duration * 100}%;width:${Math.max(2, span.duration / trace.duration * 100)}%"></i>
      </span>
      <b>${span.duration} ms</b>
    </div>
  `).join('');
  const over = ['p50', 'p90', 'p95'].filter(name =>
    activeProfile.current[name] > Number($(`#budget-${name}`).value)
  );
  $('#finding-title').textContent = over.length ? `${over.join(', ')} exceed budget` : 'Within approved budgets';
  $('#finding-copy').textContent = over.length
    ? `The correlated trace localizes the slowest ${activeProfile.type} iteration. Inspect the longest backend or render span before promoting a new golden.`
    : 'The current distribution remains inside its absolute budgets. Compare the delta before promoting this run as a new golden.';
  $('#trace-panel').hidden = false;
  $('#trace-toggle').setAttribute('aria-expanded', 'true');
  $('#trace-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2400);
}

async function initialize() {
  try {
    const response = await fetch('fixtures/performance-runs.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    fixture = await response.json();
    $('#environment').textContent = `${fixture.meta.environment} · ${fixture.meta.build}`;
    fillProfiles();
    $$('input[name="scope"]').forEach(input => input.addEventListener('change', () => fillProfiles()));
    $('#profile').addEventListener('change', chooseProfile);
    $('#run-button').addEventListener('click', runPrototype);
    $('#trace-toggle').addEventListener('click', renderTrace);
    $('#trace-close').addEventListener('click', () => {
      $('#trace-panel').hidden = true;
      $('#trace-toggle').setAttribute('aria-expanded', 'false');
    });
  } catch (error) {
    $('#environment').textContent = 'Fixture unavailable';
    setStatus('ERROR', 'fail');
    showToast(`Start a local web server: ${error.message}`);
  }
}

initialize();
