'use strict';

const PROVIDER_MODELS = {
  Anthropic:  ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-3-5'],
  OpenAI:     ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'o1', 'o1-mini', 'o3-mini'],
  OpenRouter: ['openai/gpt-4o', 'anthropic/claude-sonnet-4-5',
               'meta-llama/llama-3.1-70b-instruct', 'google/gemini-pro-1.5',
               'mistralai/mistral-large'],
  Groq:       ['llama-3.1-70b-versatile', 'llama-3.1-8b-instant',
               'mixtral-8x7b-32768', 'gemma2-9b-it'],
};

// ── Navigation ────────────────────────────────────────────────────────────

function showScreen(name) {
  document.querySelectorAll('[data-screen]').forEach(el => {
    el.style.display = el.dataset.screen === name ? 'flex' : 'none';
  });
  if (name === 'settings') _loadSettings();
  if (name === 'main')     _loadHistory();
}

// ── Settings ──────────────────────────────────────────────────────────────

async function _loadSettings() {
  try {
    const s = await window.pywebview.api.get_settings();
    _q('llm-provider').value = s.llm_provider || 'Anthropic';
    onProviderChange(s.llm_provider || 'Anthropic', s.llm_model);
    _q('custom-model-input').value = s.llm_custom_model || '';
    const ttsProv = s.tts_provider || 'gtts';
    _q('tts-provider').value = ttsProv;
    onTtsChange(ttsProv);
    _q('tts-key').value = ttsProv === 'deepgram' ? (s.deepgram_key || '') : (s.elevenlabs_key || '');
    _q('dg-voice').value      = s.deepgram_voice  || 'aura-asteria-en';
    _q('output-folder').value = s.output_folder   || '';
    _q('wpm-slider').value    = s.wpm             || 150;
    _q('wpm-label').textContent = (s.wpm || 150) + ' WPM';
    _q('anthropic-key').value  = s.anthropic_key  || '';
    _q('openai-key').value     = s.openai_key     || '';
    _q('openrouter-key').value = s.openrouter_key || '';
    _q('groq-key').value       = s.groq_key       || '';
    _q('serper-key').value     = s.serper_key     || '';
    const fprimary   = s.footage_primary   || 'pexels';
    const ffallback  = s.footage_fallback  || 'pixabay';
    const ffallback2 = s.footage_fallback2 || 'none';
    _q('footage-primary').value   = fprimary;
    _q('footage-fallback').value  = ffallback;
    _q('footage-fallback2').value = ffallback2;
    _q('footage-shortage-select').value = s.footage_shortage_strategy || 'loop';
    onFootageChange('primary');
    onFootageChange('fallback');
    onFootageChange('fallback2');
    _q('footage-primary-key').value =
      fprimary === 'pexels'   ? (s.pexels_key   || '')
      : fprimary === 'pixabay' ? (s.pixabay_key  || '') : '';
    _q('footage-fallback-key').value =
      ffallback === 'pixabay' ? (s.pixabay_key || '')
      : ffallback === 'pexels' ? (s.pexels_key || '') : '';
    _q('footage-fallback2-key').value =
      ffallback2 === 'pexels'   ? (s.pexels_key   || '')
      : ffallback2 === 'pixabay' ? (s.pixabay_key  || '') : '';
    _q('coverr-key-input').value = s.coverr_key || '';
  } catch (e) { console.error('loadSettings:', e); }
}

function onProviderChange(provider, keepModel) {
  const models = PROVIDER_MODELS[provider] || [];
  const sel = _q('llm-model');
  sel.innerHTML = models.map(m =>
    `<option value="${m}" ${m === keepModel ? 'selected' : ''}>${m}</option>`
  ).join('');
  ['anthropic','openai','openrouter','groq'].forEach(p => {
    const row = _q('key-row-' + p);
    if (row) row.style.display = p !== provider.toLowerCase() ? 'none' : '';
  });
  const customInput = _q('custom-model-input');
  if (customInput) customInput.value = '';
}

function onTtsChange(provider) {
  const noKey = provider === 'gtts' || provider === 'edge';
  _q('tts-key-row').style.display = noKey ? 'none' : '';
  _q('tts-key-label').textContent =
    provider === 'elevenlabs' ? 'ElevenLabs API Key' : 'Deepgram API Key';
  _q('dg-voice-row').style.display =
    provider === 'deepgram' ? '' : 'none';
}

function onFootageChange(role) {
  const val    = _q('footage-' + role).value;
  const keyRow = _q('footage-' + role + '-key-row');
  const keyLbl = _q('footage-' + role + '-key-label');
  if (keyRow) {
    if (val === 'none' || val === 'coverr') {
      keyRow.style.display = 'none';
    } else {
      keyRow.style.display = '';
      if (keyLbl) keyLbl.textContent = (val === 'pexels' ? 'Pexels' : 'Pixabay') + ' API Key';
    }
  }
  const prim  = _q('footage-primary').value;
  const fall  = _q('footage-fallback').value;
  const fall2 = _q('footage-fallback2').value;
  const coverrRow = _q('coverr-key-row');
  if (coverrRow) {
    coverrRow.style.display =
      (prim === 'coverr' || fall === 'coverr' || fall2 === 'coverr') ? '' : 'none';
  }
}

async function saveSettings() {
  const btn = _q('save-btn');
  btn.textContent = 'Saving…'; btn.disabled = true;
  const provider = _q('llm-provider').value;
  const customModel = (_q('custom-model-input').value || '').trim();
  const ttsProv = _q('tts-provider').value;
  const ttsKey  = _q('tts-key').value;
  const fprimary      = _q('footage-primary').value;
  const ffallback     = _q('footage-fallback').value;
  const ffallback2    = _q('footage-fallback2').value;
  const primaryKeyVal   = _q('footage-primary-key').value;
  const fallbackKeyVal  = _q('footage-fallback-key').value;
  const fallback2KeyVal = _q('footage-fallback2-key').value;
  const data = {
    llm_provider:     provider,
    llm_model:        customModel || _q('llm-model').value,
    llm_custom_model: customModel,
    tts_provider:    ttsProv,
    deepgram_voice:  _q('dg-voice').value,
    output_folder:   _q('output-folder').value,
    wpm:             parseInt(_q('wpm-slider').value),
    footage_primary:           fprimary,
    footage_fallback:          ffallback,
    footage_fallback2:         ffallback2,
    footage_shortage_strategy: _q('footage-shortage-select').value,
    anthropic_key:   _q('anthropic-key').value,
    openai_key:      _q('openai-key').value,
    openrouter_key:  _q('openrouter-key').value,
    groq_key:        _q('groq-key').value,
    elevenlabs_key:  ttsProv === 'elevenlabs' ? ttsKey : '',
    deepgram_key:    ttsProv === 'deepgram'   ? ttsKey : '',
    serper_key:      _q('serper-key').value,
    coverr_key:      _q('coverr-key-input').value,
  };
  if (fprimary    === 'pexels')   data.pexels_key  = primaryKeyVal;
  if (fprimary    === 'pixabay')  data.pixabay_key = primaryKeyVal;
  if (ffallback   === 'pexels')   data.pexels_key  = fallbackKeyVal;
  if (ffallback   === 'pixabay')  data.pixabay_key = fallbackKeyVal;
  if (ffallback2  === 'pexels')   data.pexels_key  = fallback2KeyVal;
  if (ffallback2  === 'pixabay')  data.pixabay_key = fallback2KeyVal;
  const res = await window.pywebview.api.save_settings(data);
  if (res.ok) {
    btn.textContent = '✓ Saved';
    btn.classList.replace('bg-accent', 'bg-green-500');
    setTimeout(() => {
      btn.textContent = 'Save settings';
      btn.classList.replace('bg-green-500', 'bg-accent');
      btn.disabled = false;
    }, 1800);
  } else {
    btn.textContent = 'Error — retry'; btn.disabled = false;
  }
}

async function browseFolder() {
  const path = await window.pywebview.api.browse_folder();
  if (path) _q('output-folder').value = path;
}

function toggleReveal(inputId, btn) {
  const inp = _q(inputId);
  inp.type = inp.type === 'password' ? 'text' : 'password';
  btn.textContent = inp.type === 'password' ? 'Reveal' : 'Hide';
}

// ── Run config ────────────────────────────────────────────────────────────

let _runMode = 'guided';

function startConfig(mode) {
  _runMode = mode;
  const badge = _q('config-mode-badge');
  if (mode === 'guided') {
    badge.textContent = 'Guided Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-[#0c2d42] text-sky-400';
    _q('topic-row').style.display = '';
  } else if (mode === 'short') {
    badge.textContent = 'Short / Reel Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-rose-900/40 text-rose-300';
    _q('topic-row').style.display = '';
  } else {
    badge.textContent = 'Full Auto Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-purple-900/40 text-purple-300';
    _q('topic-row').style.display = 'none';
  }
  _q('doc-duration-row').style.display = mode === 'short' ? 'none' : '';
  _q('short-duration-row').style.display = mode === 'short' ? '' : 'none';
  _q('aspect-row').style.display = mode === 'short' ? '' : 'none';
  _q('captions-row').style.display = mode === 'short' ? '' : 'none';
  _q('music-row').style.display = mode === 'short' ? '' : 'none';
  showScreen('config');
}

function _clampSeconds(s) {
  return Math.min(59, Math.max(0, s));
}

function updateDurationHint() {
  const mins = parseInt(_q('duration-input').value) || 0;
  const secs = _clampSeconds(parseInt(_q('duration-seconds-input').value) || 0);
  const words = Math.round((mins + secs / 60) * 150);
  _q('duration-hint').textContent =
    `Target: ${mins} min ${secs} s ≈ ${words} words of narration`;
}

function updateShortsDurationHint() {
  const secs = parseInt(_q('shorts-duration-slider').value) || 30;
  _q('shorts-duration-label').textContent = secs + ' s';
  const words = Math.round((secs / 60) * 170);
  _q('shorts-duration-hint').textContent = `Target: ${secs}s ≈ ${words} words of narration`;
}

async function startRun() {
  const topic = (_q('topic-input')?.value || '').trim();
  if (_runMode === 'short') {
    if (!topic) {
      _q('topic-input').focus();
      _q('topic-input').classList.add('border-red-500');
      return;
    }
    const secs = parseInt(_q('shorts-duration-slider').value) || 30;
    showScreen('progress');
    _resetProgress();
    startPolling();
    const res = await window.pywebview.api.start_shorts_run({
      topic, duration_seconds: secs,
      captions_enabled: _q('captions-toggle').checked,
      music_enabled: _q('music-toggle').checked,
    });
    if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
    return;
  }
  const minutes = parseInt(_q('duration-input').value) || 0;
  const seconds = _clampSeconds(parseInt(_q('duration-seconds-input').value) || 0);
  if (_runMode === 'guided' && !topic) {
    _q('topic-input').focus();
    _q('topic-input').classList.add('border-red-500');
    return;
  }
  if (minutes * 60 + seconds <= 0) {
    _q('duration-input').focus();
    _q('duration-input').classList.add('border-red-500');
    return;
  }
  showScreen('progress');
  _resetProgress();
  startPolling();
  const res = await window.pywebview.api.start_run({
    mode: _runMode, topic, duration_minutes: minutes, duration_seconds: seconds,
  });
  if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
}

async function cancelRun() {
  if (!confirm('Cancel this run? Progress will be lost.')) return;
  stopPolling();
  await window.pywebview.api.cancel_run();
  showScreen('main');
}

// ── Progress & polling ────────────────────────────────────────────────────

const STAGES = ['Script','Scenes','Audio','Keywords','Footage','Sync','Timeline','Done'];
const SHORT_STAGES = ['Script','TTS','Alignment','Footage','Assembly','Captions & Music','Mux'];

function _resetProgress() {
  _q('progress-title').textContent = 'Generating…';
  _q('log-area').innerHTML = '';
  _q('open-folder-btn').style.display = 'none';
  const isShort = _runMode === 'short';
  _q('stage-track').style.display = isShort ? 'none' : '';
  _q('shorts-stage-track').style.display = isShort ? '' : 'none';
  const stages = isShort ? SHORT_STAGES : STAGES;
  stages.forEach((_, i) => _setStage(i, 'pending'));
}

function _setStage(i, state) {
  const prefix = _runMode === 'short' ? 'short-stage-' : 'stage-';
  const el = _q(prefix + i);
  if (!el) return;
  const base = 'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border ';
  const styles = {
    pending:  base + 'bg-[#2e313a] text-[#7a8099] border-[#383b45]',
    active:   base + 'bg-[#0c2d42] text-sky-400 border-sky-400',
    complete: base + 'bg-[#052e16] text-green-400 border-green-500',
    error:    base + 'bg-[#2d0a0a] text-red-400 border-red-500',
  };
  el.className = styles[state] || styles.pending;
  const dot = el.querySelector('.stage-dot');
  if (dot) {
    const dc = { pending:'bg-[#7a8099]', active:'bg-sky-400 animate-pulse',
                 complete:'bg-green-400', error:'bg-red-400' };
    dot.className = 'stage-dot w-2 h-2 rounded-full ' + (dc[state] || dc.pending);
  }
}

function appendLog(text, type = 'info') {
  const area = _q('log-area');
  const d = document.createElement('div');
  d.className = { info:'text-[#b0b8d0]', success:'text-green-400',
                  error:'text-red-400',   warning:'text-amber-400' }[type] || 'text-[#b0b8d0]';
  d.textContent = text;
  area.appendChild(d);
  area.scrollTop = area.scrollHeight;
}

let _pollTimer = null;

function startPolling() {
  _pollTimer = setInterval(async () => {
    try {
      const events = await window.pywebview.api.get_events();
      events.forEach(_handleEvent);
    } catch (_) {}
  }, 300);
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

function _handleEvent(ev) {
  if (ev.type === 'log')   appendLog(ev.message, ev.level || 'info');
  if (ev.type === 'stage') _setStage(ev.index, ev.state);
  if (ev.type === 'complete') {
    stopPolling();
    _q('progress-title').textContent = '✓ Complete!';
    _q('progress-title').className = 'font-semibold text-green-400 ml-4';
    const btn = _q('open-folder-btn');
    btn.style.display = '';
    btn.onclick = () => window.pywebview.api.open_output_folder(ev.output_path);
    _setStage(_runMode === 'short' ? 6 : 7, 'complete');
    _q('cancel-btn').style.display = 'none';
    _q('back-btn').style.display = '';
  }
  if (ev.type === 'error') {
    stopPolling();
    _q('progress-title').textContent = '✗ Failed';
    _q('progress-title').className = 'font-semibold text-red-400 ml-4';
    appendLog('Run failed: ' + ev.message, 'error');
    _q('cancel-btn').style.display = 'none';
    _q('back-btn').style.display = '';
  }
}

// ── History ───────────────────────────────────────────────────────────────

const STATUS_BADGE_STYLES = {
  completed: 'bg-green-900/40 text-green-400',
  cancelled: 'bg-amber-900/40 text-amber-400',
  failed:    'bg-red-900/40 text-red-400',
};

function _statusBadgeClass(status) {
  return STATUS_BADGE_STYLES[status] || 'bg-amber-900/40 text-amber-400';
}

async function _loadHistory() {
  try {
    const runs = await window.pywebview.api.get_history();
    const empty = _q('history-empty');
    const list  = _q('history-list');
    if (!runs || runs.length === 0) {
      empty.style.display = ''; list.style.display = 'none'; return;
    }
    empty.style.display = 'none'; list.style.display = '';
    list.innerHTML = runs.slice(0, 5).map((r, i) => `
      <div class="anim-card flex items-center justify-between bg-card border border-border rounded-xl px-5 py-4 mb-3" style="animation-delay:${i * 40}ms">
        <div>
          <div class="text-sm font-medium text-white">${r.topic || 'Auto topic'}</div>
          <div class="text-xs text-faint mt-0.5">${r.created_at || ''} · ${r.duration_minutes || '?'} min</div>
        </div>
        <span class="badge-enter text-xs px-2.5 py-1 rounded-full ${_statusBadgeClass(r.status)}" style="animation-delay:${i * 40 + 100}ms">${r.status}</span>
      </div>
    `).join('');
  } catch (_) {}
}

// ── Utility ───────────────────────────────────────────────────────────────

function _q(id) { return document.getElementById(id); }

function _addRipple(e) {
  const btn = e.currentTarget;
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height) * 1.6;
  const ripple = document.createElement('span');
  ripple.className = 'ripple';
  ripple.style.width = ripple.style.height = size + 'px';
  ripple.style.left = (e.clientX - rect.left - size / 2) + 'px';
  ripple.style.top = (e.clientY - rect.top - size / 2) + 'px';
  const prevPosition = getComputedStyle(btn).position;
  if (prevPosition === 'static') btn.style.position = 'relative';
  btn.style.overflow = 'hidden';
  btn.appendChild(ripple);
  ripple.addEventListener('animationend', () => ripple.remove());
}

// Init
document.addEventListener('DOMContentLoaded', () => {
  _loadHistory();
  // Wire provider change
  _q('llm-provider').addEventListener('change', e => onProviderChange(e.target.value));
  // Wire duration hint
  const dur = _q('duration-input');
  if (dur) dur.addEventListener('input', updateDurationHint);
  const durSec = _q('duration-seconds-input');
  if (durSec) durSec.addEventListener('input', updateDurationHint);
  const shortsDur = _q('shorts-duration-slider');
  if (shortsDur) shortsDur.addEventListener('input', updateShortsDurationHint);
  // Wire cancel button
  _q('cancel-btn').addEventListener('click', cancelRun);
  // Init provider models
  onProviderChange('Anthropic');
  // Wire ripple effect on primary CTA buttons
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    ['start-run-btn', 'save-btn'].forEach(id => {
      const el = _q(id);
      if (el) el.addEventListener('click', _addRipple);
    });
  }
});
