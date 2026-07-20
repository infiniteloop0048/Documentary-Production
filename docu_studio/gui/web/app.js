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
    const isTarget = el.dataset.screen === name;
    el.style.display = isTarget ? 'flex' : 'none';
    if (isTarget) {
      // Restart the entrance animation on every navigation, not just first
      // paint — remove the class, force a reflow, then re-add it.
      el.classList.remove('screen-enter-active');
      void el.offsetWidth;
      el.classList.add('screen-enter-active');
    }
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
    _q('reasoning-toggle').checked = !!s.llm_reasoning_enabled;
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
    _q('gemini-key').value     = s.gemini_key     || '';
    _q('replicate-key').value  = s.replicate_key  || '';
    _q('fal-key').value        = s.fal_key        || '';
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
    _q('music-provider').value = s.music_provider || 'local';
    onMusicProviderChange(_q('music-provider').value);
    _q('jamendo-key').value = s.jamendo_key || '';
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
  const reasoningRow = _q('reasoning-row');
  if (reasoningRow) reasoningRow.style.display = provider === 'OpenRouter' ? '' : 'none';
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

function onFootageSourceChange(value) {
  const isAiImage = value === 'ai_image';
  _q('ai-image-model-row').style.display = isAiImage ? '' : 'none';
  _q('ai-story-continuity-row').style.display = isAiImage ? '' : 'none';
  _q('ai-cost-estimate-row').style.display = isAiImage ? '' : 'none';
  if (isAiImage) _updateAiImageCostEstimate();
}

const _AI_IMAGE_PRICES_USD = {
  replicate_flux_schnell: 0.003,
  fal_flux_schnell: 0.003,
  replicate_sdxl: 0.0055,
  replicate_flux_dev: 0.025,
  fal_flux_dev: 0.025,
  gemini_nano_banana: 0.04,
  openai_gpt_image_1: 0.07,
  gemini_nano_banana_pro: 0.15,
};

function _updateAiImageCostEstimate() {
  const model = _q('shorts-ai-image-model-select').value;
  const price = _AI_IMAGE_PRICES_USD[model] || 0;
  // Rough scene-count estimate: one image per ~4.5s of narration at the
  // Shorts default pace — matches the segment cadence the pipeline actually
  // produces closely enough for a pre-run estimate, not exact billing.
  const secs = parseInt(_q('shorts-duration-slider').value) || 30;
  const sceneCount = Math.max(1, Math.round(secs / 4.5));
  const total = (sceneCount * price).toFixed(3);
  _q('ai-cost-estimate-row').textContent =
    `Estimated cost: ~${sceneCount} images × $${price.toFixed(3)} = ~$${total}`;
}

function onMusicProviderChange(provider) {
  _q('jamendo-key-row').style.display = provider === 'jamendo' ? '' : 'none';
}

function onSlideshowMusicToggleChange() {
  const on = _q('slideshow-music-toggle').checked;
  _q('slideshow-music-provider-row').style.display = on ? '' : 'none';
  if (on) onSlideshowMusicProviderChange(_q('slideshow-music-provider-select').value);
}

function onSlideshowMusicProviderChange(provider) {
  _q('slideshow-music-folder-row').style.display = provider === 'local_folder' ? '' : 'none';
}

async function browseSlideshowMusicFolder() {
  const path = await window.pywebview.api.browse_folder();
  if (path) _q('slideshow-music-folder').value = path;
}

function onClipStoryMusicToggleChange() {
  const on = _q('clipstory-music-toggle').checked;
  _q('clipstory-music-provider-row').style.display = on ? '' : 'none';
  if (on) onClipStoryMusicProviderChange(_q('clipstory-music-provider-select').value);
}

function onClipStoryMusicProviderChange(provider) {
  _q('clipstory-music-folder-row').style.display = provider === 'local_folder' ? '' : 'none';
}

async function browseClipStoryMusicFolder() {
  const path = await window.pywebview.api.browse_folder();
  if (path) _q('clipstory-music-folder').value = path;
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
    llm_reasoning_enabled: _q('reasoning-toggle').checked,
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
    music_provider:  _q('music-provider').value,
    jamendo_key:     _q('jamendo-key').value,
    gemini_key:      _q('gemini-key').value,
    replicate_key:   _q('replicate-key').value,
    fal_key:         _q('fal-key').value,
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
    // Rare, once-per-visit confirmation — a small delight pop is within
    // budget here in a way it wouldn't be on something seen daily.
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      btn.style.transform = 'scale(1.03)';
      setTimeout(() => { btn.style.transform = ''; }, 160);
    }
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
  _q('start-run-btn').disabled = false;
  const badge = _q('config-mode-badge');
  if (mode === 'guided') {
    badge.textContent = 'Guided Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-[#10312d] text-teal-400';
    _q('topic-row').style.display = '';
  } else if (mode === 'short') {
    badge.textContent = 'Short / Reel Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-rose-900/40 text-rose-300';
    _q('topic-row').style.display = '';
  } else if (mode === 'slideshow') {
    badge.textContent = 'Slideshow Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-emerald-900/40 text-emerald-300';
    _q('topic-row').style.display = 'none';
  } else if (mode === 'clipstory') {
    badge.textContent = 'Clip Story Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-amber-900/40 text-amber-300';
    _q('topic-row').style.display = 'none';
  } else {
    badge.textContent = 'Full Auto Mode';
    badge.className = 'text-xs font-semibold px-3 py-1 rounded-full bg-purple-900/40 text-purple-300';
    _q('topic-row').style.display = 'none';
  }
  _q('doc-duration-row').style.display = (mode === 'short' || mode === 'slideshow' || mode === 'clipstory') ? 'none' : '';
  _q('short-duration-row').style.display = mode === 'short' ? '' : 'none';
  _q('footage-source-row').style.display = mode === 'short' ? '' : 'none';
  if (mode === 'short') onFootageSourceChange(_q('shorts-footage-source-select').value);
  _q('aspect-row').style.display = mode === 'short' ? '' : 'none';
  _q('captions-row').style.display = mode === 'short' ? '' : 'none';
  _q('caption-style-row').style.display = mode === 'short' ? '' : 'none';
  _q('music-row').style.display = mode === 'short' ? '' : 'none';
  _q('music-volume-row').style.display = mode === 'short' ? '' : 'none';
  _q('advanced-row').style.display = mode === 'short' ? '' : 'none';
  _q('slideshow-topic-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-images-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-script-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-aspect-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-transition-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-vignette-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-grain-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-captions-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-caption-style-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-music-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-music-volume-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('slideshow-advanced-row').style.display = mode === 'slideshow' ? '' : 'none';
  _q('clipstory-topic-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-canvas-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-clips-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-review-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-transition-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-captions-row').style.display = mode === 'clipstory' ? '' : 'none';
  _q('clipstory-music-row').style.display = mode === 'clipstory' ? '' : 'none';
  onSlideshowMusicToggleChange();
  onClipStoryMusicToggleChange();
  showScreen('config');
}

let _clipStoryClips = [];   // [{path, duration, posterPath, trimIn, trimOut, scriptText, useLlm}]
let _clipStoryReview = {};  // {index: {text, pace_estimate_seconds}}

async function browseClipStoryClips() {
  const paths = await window.pywebview.api.browse_videos();
  if (!paths || !paths.length) return;
  const meta = await window.pywebview.api.get_clip_metadata(paths);
  if (!meta.ok) { alert('Failed to read clip metadata: ' + meta.error); return; }
  meta.clips.forEach(c => {
    _clipStoryClips.push({
      path: c.path, duration: c.duration, posterPath: c.poster_path,
      trimIn: 0, trimOut: c.duration, scriptText: '', useLlm: false,
    });
  });
  if (Object.keys(_clipStoryReview).length > 0) {
    _clipStoryReview = {};
    _renderClipStoryReview();
  }
  _renderClipStoryClips(meta.clips.length);
}

function _renderClipStoryClips(newCount = 0) {
  const list = _q('clipstory-clip-list');
  list.innerHTML = '';
  const firstNewIndex = _clipStoryClips.length - newCount;
  _clipStoryClips.forEach((clip, i) => {
    const row = document.createElement('div');
    const isNew = i >= firstNewIndex;
    row.className = (isNew ? 'list-item-enter ' : '') +
      'bg-input border border-border rounded-lg px-3 py-3 text-sm text-white';
    if (isNew) row.style.animationDelay = Math.min((i - firstNewIndex) * 40, 400) + 'ms';

    const topRow = document.createElement('div');
    topRow.className = 'flex items-center gap-2';

    const thumb = document.createElement('img');
    thumb.src = _toFileUrl(clip.posterPath);
    thumb.className = 'w-14 h-10 object-cover rounded shrink-0';
    thumb.alt = '';
    topRow.appendChild(thumb);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'flex-1 truncate';
    nameSpan.textContent = `${i + 1}. ${clip.path.split(/[\\/]/).pop()} (${clip.duration.toFixed(1)}s)`;
    topRow.appendChild(nameSpan);

    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'text-faint hover:text-white px-1';
    upBtn.textContent = '↑';
    upBtn.onclick = () => _moveClipStoryClip(i, -1);
    topRow.appendChild(upBtn);

    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'text-faint hover:text-white px-1';
    downBtn.textContent = '↓';
    downBtn.onclick = () => _moveClipStoryClip(i, 1);
    topRow.appendChild(downBtn);

    const rmBtn = document.createElement('button');
    rmBtn.type = 'button';
    rmBtn.className = 'text-faint hover:text-red-400 px-1';
    rmBtn.textContent = '✕';
    rmBtn.onclick = () => _removeClipStoryClip(i);
    topRow.appendChild(rmBtn);

    row.appendChild(topRow);

    const trimRow = document.createElement('div');
    trimRow.className = 'mt-2 flex items-center gap-2 text-xs text-dim';
    trimRow.innerHTML = `
      <label>Trim in (s)</label>
      <input type="number" min="0" step="0.1" value="${clip.trimIn}" data-idx="${i}" data-field="trimIn"
        class="w-20 bg-panel border border-border rounded px-2 py-1 text-white">
      <label>Trim out (s)</label>
      <input type="number" min="0" step="0.1" value="${clip.trimOut}" data-idx="${i}" data-field="trimOut"
        class="w-20 bg-panel border border-border rounded px-2 py-1 text-white">
    `;
    trimRow.querySelectorAll('input').forEach(input => {
      input.onchange = (e) => _updateClipStoryTrim(i, e.target.dataset.field, parseFloat(e.target.value));
    });
    row.appendChild(trimRow);

    const scriptRow = document.createElement('div');
    scriptRow.className = 'mt-2';
    const llmLabel = document.createElement('label');
    llmLabel.className = 'flex items-center gap-2 text-xs text-dim';
    llmLabel.innerHTML = `<input type="checkbox" ${clip.useLlm ? 'checked' : ''} class="accent-accent"> Generate with AI`;
    llmLabel.querySelector('input').onchange = (e) => _updateClipStoryLlmFlag(i, e.target.checked);
    scriptRow.appendChild(llmLabel);
    if (!clip.useLlm) {
      const textarea = document.createElement('textarea');
      textarea.rows = 2;
      textarea.placeholder = 'Write narration for this clip…';
      textarea.value = clip.scriptText;
      textarea.className = 'mt-1 w-full bg-panel border border-border rounded px-2 py-1 text-white text-xs';
      textarea.onchange = (e) => _updateClipStoryScript(i, e.target.value);
      scriptRow.appendChild(textarea);
    }
    row.appendChild(scriptRow);

    list.appendChild(row);
  });
  _updateClipStoryGenerateButtonState();
}

function _moveClipStoryClip(i, delta) {
  const j = i + delta;
  if (j < 0 || j >= _clipStoryClips.length) return;
  [_clipStoryClips[i], _clipStoryClips[j]] = [_clipStoryClips[j], _clipStoryClips[i]];
  if (Object.keys(_clipStoryReview).length > 0) {
    _clipStoryReview = {};
    _renderClipStoryReview();
  }
  _renderClipStoryClips();
}

function _removeClipStoryClip(i) {
  _clipStoryClips.splice(i, 1);
  if (Object.keys(_clipStoryReview).length > 0) {
    _clipStoryReview = {};
    _renderClipStoryReview();
  }
  _renderClipStoryClips();
}

function _updateClipStoryTrim(i, field, value) {
  if (Number.isNaN(value)) return;
  _clipStoryClips[i][field] = value;
}

function _updateClipStoryScript(i, text) {
  _clipStoryClips[i].scriptText = text;
}

function _updateClipStoryLlmFlag(i, checked) {
  _clipStoryClips[i].useLlm = checked;
  if (checked) _clipStoryClips[i].scriptText = '';
  _renderClipStoryClips();
}

function _updateClipStoryGenerateButtonState() {
  const btn = _q('clipstory-generate-btn');
  if (!btn) return;
  const enabled = _clipStoryClips.length > 0 && _clipStoryClips.every(
    c => c.trimOut > c.trimIn && (c.useLlm || c.scriptText.trim().length > 0)
  );
  btn.disabled = !enabled;
  btn.className = enabled
    ? 'text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-dim hover:text-white hover:border-bstrong transition-colors cursor-pointer'
    : 'text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-faint cursor-not-allowed transition-colors';
}

async function generateClipStoryNarration() {
  const topic = (_q('clipstory-topic-input')?.value || '').trim();
  const clips = _clipStoryClips.map(c => ({
    path: c.path, trim_in: c.trimIn, trim_out: c.trimOut,
    script_text: c.scriptText, use_llm_generation: c.useLlm,
  }));
  const res = await window.pywebview.api.generate_clipstory_narration(topic, clips);
  if (!res.ok) { alert('Narration generation failed: ' + res.error); return; }
  _clipStoryReview = res.review;
  _renderClipStoryReview();
}

function _renderClipStoryReview() {
  const list = _q('clipstory-review-list');
  list.innerHTML = '';
  Object.keys(_clipStoryReview).sort((a, b) => a - b).forEach(idx => {
    const entry = _clipStoryReview[idx];
    const clip = _clipStoryClips[idx];
    const targetDuration = (clip.trimOut - clip.trimIn).toFixed(1);
    const row = document.createElement('div');
    row.className = 'bg-input border border-border rounded-lg px-3 py-3 text-sm text-white';

    const label = document.createElement('div');
    label.className = 'text-xs text-faint';
    label.textContent = `Clip ${Number(idx) + 1} — target ${targetDuration}s, estimated pace ${entry.pace_estimate_seconds.toFixed(1)}s`;
    row.appendChild(label);

    const textarea = document.createElement('textarea');
    textarea.rows = 3;
    textarea.dataset.idx = idx;
    textarea.className = 'mt-1 w-full bg-panel border border-border rounded px-2 py-1 text-white text-xs';
    textarea.value = entry.text;
    textarea.onchange = (e) => {
      _clipStoryReview[idx].text = e.target.value;
      _clipStoryClips[idx].scriptText = e.target.value;
    };
    row.appendChild(textarea);

    list.appendChild(row);
  });
  const startBtn = _q('start-run-btn');
  if (_runMode === 'clipstory') startBtn.disabled = Object.keys(_clipStoryReview).length !== _clipStoryClips.length;
}

let _slideshowImages = [];

// Build a file:// URL from a raw OS filesystem path, percent-encoding each
// path segment so characters that are reserved in URLs (space, #, ?, &, %,
// non-ASCII) don't corrupt or truncate the path. Preserves a Windows drive
// letter segment (e.g. "C:") unencoded since Chromium's file-URL parser only
// recognizes it in that literal form.
function _toFileUrl(path) {
  const normalized = path.replace(/\\/g, '/');
  const encoded = normalized
    .split('/')
    .map((segment, i) => (i === 0 && /^[a-zA-Z]:$/.test(segment) ? segment : encodeURIComponent(segment)))
    .join('/');
  return 'file://' + (encoded.startsWith('/') ? encoded : '/' + encoded);
}

async function browseSlideshowImages() {
  const paths = await window.pywebview.api.browse_images();
  if (paths && paths.length) {
    _slideshowImages = _slideshowImages.concat(paths);
    _renderSlideshowImages(paths.length);
  }
}

function _renderSlideshowImages(newCount = 0) {
  const list = _q('slideshow-image-list');
  list.innerHTML = '';
  const firstNewIndex = _slideshowImages.length - newCount;
  _slideshowImages.forEach((path, i) => {
    const row = document.createElement('div');
    const isNew = i >= firstNewIndex;
    row.className = (isNew ? 'list-item-enter ' : '') +
      'flex items-center gap-2 bg-input border border-border rounded-lg px-3 py-2 text-sm text-white';
    if (isNew) row.style.animationDelay = Math.min((i - firstNewIndex) * 40, 400) + 'ms';
    row.style.transition = 'opacity 150ms var(--ease-out), transform 150ms var(--ease-out), box-shadow 150ms var(--ease-out)';
    // Drag-and-drop reordering to any position, in addition to the ↑/↓
    // buttons below — the OS file-picker's multi-select order is not
    // reliably the click order, so full manual reordering is the only way
    // users get real control over final sequence.
    row.draggable = true;
    row.addEventListener('dragstart', (e) => {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(i));
      row.style.opacity = '0.5';
      row.style.transform = 'scale(1.02)';
      row.style.boxShadow = '0 8px 20px -6px rgba(0,0,0,.5)';
    });
    row.addEventListener('dragend', () => {
      row.style.opacity = '';
      row.style.transform = '';
      row.style.boxShadow = '';
    });
    row.addEventListener('dragover', (e) => e.preventDefault());
    row.addEventListener('drop', (e) => {
      e.preventDefault();
      const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
      _reorderSlideshowImage(from, i);
    });

    const handle = document.createElement('span');
    handle.className = 'text-faint cursor-grab select-none px-1';
    handle.textContent = '⠿';
    handle.title = 'Drag to reorder';
    row.appendChild(handle);

    const thumb = document.createElement('img');
    thumb.src = _toFileUrl(path);
    thumb.className = 'w-10 h-10 object-cover rounded shrink-0';
    thumb.alt = '';
    row.appendChild(thumb);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'flex-1 truncate';
    nameSpan.textContent = `${i + 1}. ${path.split(/[\\/]/).pop()}`;
    row.appendChild(nameSpan);

    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'text-faint hover:text-white px-1';
    upBtn.textContent = '↑';
    upBtn.onclick = () => _moveSlideshowImage(i, -1);
    row.appendChild(upBtn);

    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'text-faint hover:text-white px-1';
    downBtn.textContent = '↓';
    downBtn.onclick = () => _moveSlideshowImage(i, 1);
    row.appendChild(downBtn);

    const rmBtn = document.createElement('button');
    rmBtn.type = 'button';
    rmBtn.className = 'text-faint hover:text-red-400 px-1';
    rmBtn.textContent = '✕';
    rmBtn.onclick = () => _removeSlideshowImage(i);
    row.appendChild(rmBtn);

    list.appendChild(row);
  });
  _updateGenerateButtonState();
}

function _reorderSlideshowImage(fromIndex, toIndex) {
  if (Number.isNaN(fromIndex) || fromIndex === toIndex) return;
  if (fromIndex < 0 || fromIndex >= _slideshowImages.length) return;
  if (toIndex < 0 || toIndex >= _slideshowImages.length) return;
  const [moved] = _slideshowImages.splice(fromIndex, 1);
  _slideshowImages.splice(toIndex, 0, moved);
  _renderSlideshowImages();
}

function _moveSlideshowImage(i, delta) {
  const j = i + delta;
  if (j < 0 || j >= _slideshowImages.length) return;
  [_slideshowImages[i], _slideshowImages[j]] = [_slideshowImages[j], _slideshowImages[i]];
  _renderSlideshowImages();
}

function _removeSlideshowImage(i) {
  _slideshowImages.splice(i, 1);
  _renderSlideshowImages();
}

async function fetchSlideshowTopicImages() {
  const topic = (_q('slideshow-topic-input')?.value || '').trim();
  if (!topic) {
    _q('slideshow-topic-input').focus();
    _q('slideshow-topic-input').classList.add('border-red-500');
    return;
  }
  const count = Math.min(15, Math.max(3, parseInt(_q('slideshow-fetch-count').value) || 8));
  const btn = _q('slideshow-fetch-btn');
  const status = _q('slideshow-fetch-status');
  btn.disabled = true;
  btn.textContent = 'Fetching…';
  status.textContent = '';
  try {
    const res = await window.pywebview.api.fetch_slideshow_images(topic, count);
    if (res.ok) {
      _slideshowImages = _slideshowImages.concat(res.paths);
      _renderSlideshowImages(res.paths.length);
      status.textContent = res.message || '';
    } else {
      status.textContent = 'Failed to fetch images: ' + (res.error || '');
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'Fetch images';
  }
}

async function generateSlideshowScript() {
  const topic = (_q('slideshow-topic-input')?.value || '').trim();
  if (!topic) {
    _q('slideshow-topic-input').focus();
    _q('slideshow-topic-input').classList.add('border-red-500');
    return;
  }
  if (_slideshowImages.length === 0) return;
  const btn = _q('slideshow-generate-btn');
  btn.disabled = true;
  btn.textContent = 'Generating…';
  try {
    const res = await window.pywebview.api.generate_slideshow_script(topic, _slideshowImages.length);
    if (res.ok) {
      _q('slideshow-script-input').value = res.script_text;
    } else {
      alert('Failed to generate script: ' + (res.error || ''));
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate with LLM';
  }
}

function _updateGenerateButtonState() {
  const btn = _q('slideshow-generate-btn');
  if (!btn) return;
  const enabled = _slideshowImages.length > 0;
  btn.disabled = !enabled;
  btn.className = enabled
    ? 'text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-dim hover:text-white hover:border-bstrong transition-colors cursor-pointer'
    : 'text-xs font-semibold px-3 py-1.5 rounded-lg bg-card border border-border text-faint cursor-not-allowed transition-colors';
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
  if (_q('shorts-footage-source-select').value === 'ai_image') _updateAiImageCostEstimate();
}

function updateMusicVolumeLabel() {
  const db = parseInt(_q('music-volume-slider').value);
  _q('music-volume-label').textContent = db + ' dB';
}

function updateSlideshowMusicVolumeLabel() {
  const db = parseInt(_q('slideshow-music-volume-slider').value);
  _q('slideshow-music-volume-label').textContent = db + ' dB';
}

async function startRun() {
  const topic = (_q('topic-input')?.value || '').trim();
  if (_runMode === 'clipstory') {
    const clipsTopic = (_q('clipstory-topic-input')?.value || '').trim();
    if (Object.keys(_clipStoryReview).length !== _clipStoryClips.length) {
      alert('Please generate/review narration for every clip first.');
      return;
    }
    showScreen('progress');
    _resetProgress();
    startPolling();
    const res = await window.pywebview.api.start_clipstory_run({
      topic: clipsTopic,
      output_resolution: _q('clipstory-canvas-select').value,
      clips: _clipStoryClips.map((c, i) => ({
        path: c.path, trim_in: c.trimIn, trim_out: c.trimOut,
        script_text: _clipStoryReview[i].text, use_llm_generation: false,
      })),
      transition: _q('clipstory-transition-select').value,
      captions: _q('clipstory-captions-toggle').checked,
      music_enabled: _q('clipstory-music-toggle').checked,
      music_provider: _q('clipstory-music-provider-select').value,
      music_folder: _q('clipstory-music-folder').value,
    });
    if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
    return;
  }
  if (_runMode === 'slideshow') {
    const scriptText = (_q('slideshow-script-input')?.value || '').trim();
    if (!scriptText) {
      _q('slideshow-script-input').focus();
      _q('slideshow-script-input').classList.add('border-red-500');
      return;
    }
    if (_slideshowImages.length === 0) {
      alert('Please choose at least one image.');
      return;
    }
    showScreen('progress');
    _resetProgress();
    startPolling();
    const res = await window.pywebview.api.start_slideshow_run({
      script_text: scriptText,
      image_paths: _slideshowImages,
      aspect_ratio: _q('slideshow-aspect-select').value,
      transition: _q('slideshow-transition-select').value,
      vignette: _q('slideshow-vignette-toggle').checked,
      grain: _q('slideshow-grain-toggle').checked,
      captions: _q('slideshow-captions-toggle').checked,
      caption_style: _q('slideshow-caption-style-select').value,
      music_enabled: _q('slideshow-music-toggle').checked,
      music_provider: _q('slideshow-music-provider-select').value,
      music_folder: _q('slideshow-music-folder').value,
      music_volume_db: parseInt(_q('slideshow-music-volume-slider').value),
      loop_revisit_enabled: _q('slideshow-loop-revisit-toggle').checked,
      cinematic_ending_enabled: _q('slideshow-cinematic-ending-toggle').checked,
    });
    if (!res.ok) appendLog('Failed to start: ' + (res.error || ''), 'error');
    return;
  }
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
      footage_source: _q('shorts-footage-source-select').value,
      ai_image_model: _q('shorts-ai-image-model-select').value,
      ai_story_continuity: _q('ai-story-continuity-toggle').checked,
      aspect_ratio: _q('shorts-aspect-select').value,
      captions_enabled: _q('captions-toggle').checked,
      caption_style: _q('caption-style-select').value,
      music_enabled: _q('music-toggle').checked,
      music_volume_db: parseInt(_q('music-volume-slider').value),
      beat_sync_enabled: _q('beat-sync-toggle').checked,
      speed_ramp_enabled: _q('speed-ramp-toggle').checked,
      loop_revisit_enabled: _q('loop-revisit-toggle').checked,
      cinematic_ending_enabled: _q('cinematic-ending-toggle').checked,
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
const SLIDESHOW_STAGES = ['TTS','Assembly','Mux'];
const CLIPSTORY_STAGES = ['Assembly'];

function _resetProgress() {
  _q('progress-title').textContent = 'Generating…';
  _q('log-area').innerHTML = '';
  _q('open-folder-btn').style.display = 'none';
  _q('stage-track').style.display = (_runMode === 'short' || _runMode === 'slideshow' || _runMode === 'clipstory') ? 'none' : '';
  _q('shorts-stage-track').style.display = _runMode === 'short' ? '' : 'none';
  _q('slideshow-stage-track').style.display = _runMode === 'slideshow' ? '' : 'none';
  _q('clipstory-stage-track').style.display = _runMode === 'clipstory' ? '' : 'none';
  const stages = _runMode === 'short' ? SHORT_STAGES : _runMode === 'slideshow' ? SLIDESHOW_STAGES : _runMode === 'clipstory' ? CLIPSTORY_STAGES : STAGES;
  stages.forEach((_, i) => _setStage(i, 'pending'));
}

function _setStage(i, state) {
  const prefix = _runMode === 'short' ? 'short-stage-' : _runMode === 'slideshow' ? 'slideshow-stage-' : _runMode === 'clipstory' ? 'clipstory-stage-' : 'stage-';
  const el = _q(prefix + i);
  if (!el) return;
  // stage-pill stays present across every state so the color/border swap
  // below transitions instead of snapping; is-active adds a small state-
  // indication scale bump only while this stage is the current one.
  const base = 'stage-pill flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border ';
  const styles = {
    pending:  base + 'bg-[#2e313a] text-[#7a8099] border-[#383b45]',
    active:   base + 'bg-[#10312d] text-teal-400 border-teal-400 is-active',
    complete: base + 'bg-[#052e16] text-green-400 border-green-500',
    error:    base + 'bg-[#2d0a0a] text-red-400 border-red-500',
  };
  el.className = styles[state] || styles.pending;
  const dot = el.querySelector('.stage-dot');
  if (dot) {
    const dc = { pending:'bg-[#7a8099]', active:'bg-teal-400 animate-pulse',
                 complete:'bg-green-400', error:'bg-red-400' };
    dot.className = 'stage-dot w-2 h-2 rounded-full ' + (dc[state] || dc.pending);
  }
}

function appendLog(text, type = 'info') {
  const area = _q('log-area');
  const d = document.createElement('div');
  const color = { info:'text-[#b0b8d0]', success:'text-green-400',
                  error:'text-red-400',   warning:'text-amber-400' }[type] || 'text-[#b0b8d0]';
  d.className = 'log-line ' + color;
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
    // Note: no 'slideshow' arm here — pre-existing gap, not introduced by this
    // feature. Slideshow's "complete" stage-track cell has never lit up; left
    // as-is to avoid an undisclosed behavior change to Slideshow.
    _setStage(_runMode === 'short' ? 6 : _runMode === 'clipstory' ? 0 : 7, 'complete');
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
  const musicVol = _q('music-volume-slider');
  if (musicVol) musicVol.addEventListener('input', updateMusicVolumeLabel);
  const slideshowMusicVol = _q('slideshow-music-volume-slider');
  if (slideshowMusicVol) slideshowMusicVol.addEventListener('input', updateSlideshowMusicVolumeLabel);
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
