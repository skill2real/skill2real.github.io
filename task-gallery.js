/* Task recordings, code and execution stages. */
(() => {
  const { tasks, programs } = taskGalleryData;
  const picker = document.querySelector('#task-picker');
  const player = document.querySelector('#task-player');
  const playButton = document.querySelector('#task-play-toggle');
  const playLabel = document.querySelector('#task-play-label');
  const playbackStatus = document.querySelector('#task-playback-status');
  const codeBlock = document.querySelector('#task-code');
  const copy = document.querySelector('#copy-task-code');
  let selected = tasks[0];
  let codeView = 'program';
  let currentCode = '';
  let copyTimer;
  let activeSuite = 'all';
  let activeRealCategory = 'all';
  let expanded = false;
  let playRequest = 0;
  let mediaFailed = false;
  const suiteOrder = ['libero90', 'prolong', 'robosuite', 'real', 'tabletop'];
  const groups = suiteOrder.map(suite => tasks.filter(task => task.suite === suite));
  const balancedTasks = Array.from({ length: Math.max(...groups.map(group => group.length)) }, (_, index) => groups.map(group => group[index]).filter(Boolean)).flat();
  const showMore = document.querySelector('#task-show-more');
  const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const stageSelect = document.querySelector('#task-code-stage');
  const realFilters = document.querySelector('#real-task-filters');
  const realCategories = {
    all: 'All real tasks', placement: 'Pick & place', sorting: 'Color sorting',
    insertion: 'Insertion', 'push-pull': 'Push & pull', storage: 'Drawer storage',
    arithmetic: 'Equations', lighting: 'Lighting changes'
  };
  Object.entries(realCategories).forEach(([category, label]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.category = category;
    button.setAttribute('aria-pressed', String(category === 'all'));
    const count = tasks.filter(task => task.suite === 'real' && (category === 'all' || task.category === category)).length;
    button.innerHTML = `${escape(label)} <span>${count}</span>`;
    button.addEventListener('click', () => { activeRealCategory = category; renderPicker(); });
    realFilters.append(button);
  });
  function highlightPython(line) {
    const tokens = /#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\bapi\.[a-z_]+|\b(?:def|return|if|else|elif|for|in|not|and|or|try|except|raise|lambda|is|None|True|False)\b/g;
    let html = '', cursor = 0;
    for (const match of line.matchAll(tokens)) {
      html += escape(line.slice(cursor, match.index));
      const value = match[0];
      const kind = value.startsWith('#') ? 'comment' : /^["']/.test(value) ? 'string' : value.startsWith('api.') ? 'api' : 'keyword';
      html += `<span class="py-${kind}">${escape(value)}</span>`;
      cursor = match.index + value.length;
    }
    return html + escape(line.slice(cursor));
  }
  function showStage() {
    const phase = stageSelect.value;
    const lines = currentCode.split('\n');
    const stage = programs[selected.id].stages.find(item => item.id === phase);
    const marker = stage?.marker || `if phase == '${phase}':`;
    const number = phase === 'overview' ? 0 : lines.findIndex(line => line.trim() === marker);
    const target = codeBlock.querySelector(`[data-line="${Math.max(0, number)}"]`);
    const scroller = document.querySelector('#task-code-scroll');
    scroller.scrollTop = target ? target.offsetTop - codeBlock.offsetTop - 16 : 0;
    codeBlock.querySelectorAll('.active-code-line').forEach(line => line.classList.remove('active-code-line'));
    target?.classList.toggle('active-code-line', phase !== 'overview');
  }
  function syncPlaybackButton() {
    const playing = !player.paused && !player.ended;
    playButton.classList.toggle('playing', playing);
    playLabel.textContent = mediaFailed ? 'Retry video' : player.ended ? 'Replay video' : playing ? 'Pause video' : 'Play video';
  }
  function playbackError() {
    mediaFailed = true;
    playbackStatus.textContent = 'Video could not load. Retry or use the Video link below.';
    syncPlaybackButton();
  }
  async function playTask(reveal = false) {
    const request = ++playRequest;
    if (reveal) {
      document.querySelector('.task-explorer').scrollIntoView({
        block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'
      });
    }
    if (mediaFailed || player.error || player.networkState === HTMLMediaElement.NETWORK_NO_SOURCE) player.load();
    mediaFailed = false;
    if (player.ended) player.currentTime = 0;
    playbackStatus.textContent = 'Loading video…';
    syncPlaybackButton();
    try {
      await player.play();
      if (request !== playRequest) return;
      playbackStatus.textContent = 'Playing';
      syncPlaybackButton();
    } catch (error) {
      if (request !== playRequest || error.name === 'AbortError') return;
      if (error.name === 'NotAllowedError') {
        playbackStatus.textContent = 'Press Play video to start this recording.';
        syncPlaybackButton();
      } else playbackError();
    }
  }
  playButton.addEventListener('click', () => {
    if (player.paused || player.ended || mediaFailed) playTask();
    else { ++playRequest; player.pause(); }
  });
  player.addEventListener('play', syncPlaybackButton);
  player.addEventListener('playing', () => { playbackStatus.textContent = 'Playing'; syncPlaybackButton(); });
  player.addEventListener('waiting', () => { playbackStatus.textContent = 'Buffering…'; });
  player.addEventListener('pause', () => {
    if (!mediaFailed) playbackStatus.textContent = player.ended ? 'Recording complete' : player.currentTime ? 'Paused' : 'Ready to play';
    syncPlaybackButton();
  });
  player.addEventListener('ended', () => { playbackStatus.textContent = 'Recording complete'; syncPlaybackButton(); });
  player.addEventListener('error', playbackError);
  player.querySelector('source').addEventListener('error', playbackError);
  function renderCode() {
    const program = programs[selected.id];
    currentCode = program.code;
    codeBlock.innerHTML = currentCode.split('\n').map((line, index) => `<span class="code-line" data-line="${index}">${highlightPython(line) || ' '}</span>`).join('\n');
    stageSelect.innerHTML = '<option value="overview">Program overview</option>' + program.stages.map(stage => `<option value="${escape(stage.id)}">${escape(stage.title)}</option>`).join('');
    const steps = document.querySelector('#task-program-steps');
    steps.innerHTML = `<p class="program-summary">${escape(program.summary)}</p><ol>${program.stages.map(stage => `<li><strong>${escape(stage.title)}</strong><p>${escape(stage.description)}</p></li>`).join('')}</ol>`;
    const programView = codeView === 'program';
    document.querySelector('#task-code-scroll').hidden = !programView;
    document.querySelector('.task-stage-select').hidden = !programView;
    steps.hidden = programView;
    document.querySelector('#code-filename').textContent = program.file.split('/').pop();
    document.querySelector('#task-code-download').href = program.file;
    document.querySelector('#task-code-scroll').scrollTop = 0;
    document.querySelector('#task-code-scroll').scrollLeft = 0;
    document.querySelectorAll('[data-code-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.codeView === codeView)));
    clearTimeout(copyTimer);
    copy.textContent = 'Copy';
  }
  stageSelect.addEventListener('change', showStage);
  function selectTask(task, initial = false) {
    const changed = selected.id !== task.id;
    selected = task;
    if (!initial && changed) {
      ++playRequest;
      player.pause();
      mediaFailed = false;
      player.poster = task.poster;
      player.querySelector('source').src = task.video;
      player.load();
      playbackStatus.textContent = 'Ready to play';
    }
    syncPlaybackButton();
    player.setAttribute('aria-label', `${task.title} task recording`);
    document.querySelector('#selected-task-title').textContent = task.title;
    document.querySelector('#selected-task-instruction').textContent = task.instruction;
    document.querySelector('#selected-task-environment').textContent = task.environment;
    const speed = task.mediaNote.match(/(\d+(?:\.\d+)?)×/);
    document.querySelector('#task-media-note').textContent = speed ? `${speed[1]}× speed`
      : /final release|excerpt/i.test(task.mediaNote) ? 'Task excerpt'
      : /replay/i.test(task.mediaNote) ? 'Simulation replay'
      : /scripted/i.test(task.mediaNote) ? 'Scripted demo'
      : task.suite === 'real' ? 'Recorded sequence' : 'Simulation recording';
    document.querySelector('.task-flow').hidden = task.suite === 'tabletop';
    document.querySelector('#task-video-download').href = task.video;
    picker.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.task === task.id)));
    renderCode();
    if (!initial) document.querySelector('#task-selection-status').textContent = `${task.title} selected. ${task.environment}. Video and task code updated.`;
  }
  balancedTasks.forEach(task => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'task-choice';
    button.dataset.task = task.id;
    button.dataset.suite = task.suite;
    button.setAttribute('aria-pressed', 'false');
    button.setAttribute('aria-controls', 'task-player task-code');
    button.setAttribute('aria-label', `Play ${task.title} — ${task.environment}`);
    button.innerHTML = `<img data-src="${escape(task.poster)}" alt="" loading="lazy" width="240" height="180"><span class="task-choice-play" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></span><span class="task-choice-text"><small>${escape(task.environment)}</small><strong>${escape(task.title)}</strong></span>`;
    const thumbnail = button.querySelector('img');
    thumbnail.addEventListener('error', () => {
      if (thumbnail.dataset.retried) return;
      thumbnail.dataset.retried = 'true';
      setTimeout(() => { thumbnail.src = `${thumbnail.dataset.src}?retry=1`; }, 500);
    });
    button.addEventListener('click', () => { selectTask(task); playTask(true); });
    picker.append(button);
  });
  function renderPicker() {
    const matching = balancedTasks.filter(task => (activeSuite === 'all' || task.suite === activeSuite)
      && (activeSuite !== 'real' || activeRealCategory === 'all' || task.category === activeRealCategory));
    realFilters.hidden = activeSuite !== 'real';
    realFilters.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.category === activeRealCategory)));
    const visible = activeSuite === 'all' && !expanded ? matching.slice(0, 12) : matching;
    const ids = new Set(visible.map(task => task.id));
    picker.querySelectorAll('button').forEach(button => {
      button.hidden = !ids.has(button.dataset.task);
      const thumbnail = button.querySelector('img');
      if (!button.hidden && !thumbnail.hasAttribute('src')) thumbnail.src = thumbnail.dataset.src;
    });
    document.querySelectorAll('.domain-filters button').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.suite === activeSuite));
      button.querySelector('span').textContent = tasks.filter(task => button.dataset.suite === 'all' || task.suite === button.dataset.suite).length;
    });
    showMore.hidden = activeSuite !== 'all';
    showMore.setAttribute('aria-expanded', String(expanded));
    showMore.textContent = expanded ? 'Show highlights ↑' : `Show all ${tasks.length} recordings ↓`;
    document.querySelector('#task-gallery-summary').textContent = activeSuite === 'all'
      ? (expanded ? `All ${tasks.length} recordings across ${suiteOrder.length} collections.` : `12 highlights from ${tasks.length} recordings. Choose a collection to see every task.`)
      : activeSuite === 'real' && activeRealCategory !== 'all'
        ? `${matching.length} recordings · ${realCategories[activeRealCategory]}`
        : `${matching.length} ${matching[0].environment} recordings. Select a task to watch.`;
    if (!ids.has(selected.id)) selectTask(visible[0]);
  }
  document.querySelectorAll('.domain-filters button').forEach(button => button.addEventListener('click', () => {
    activeSuite = button.dataset.suite;
    activeRealCategory = 'all';
    expanded = false;
    renderPicker();
  }));
  showMore.addEventListener('click', () => { expanded = !expanded; renderPicker(); });
  document.querySelectorAll('[data-code-view]').forEach(button => button.addEventListener('click', () => { codeView = button.dataset.codeView; renderCode(); }));
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(currentCode);
      copy.textContent = 'Copied';
      document.querySelector('#task-selection-status').textContent = `${selected.title} program copied.`;
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(codeBlock);
      selection.removeAllRanges();
      selection.addRange(range);
      copy.textContent = 'Selected';
      document.querySelector('#task-selection-status').textContent = 'Program selected. Use your device copy command or the download link.';
    }
    copyTimer = setTimeout(() => { copy.textContent = 'Copy'; }, 2400);
  });
  document.querySelector('.api-jump').addEventListener('click', () => { document.querySelector('#standard-api').open = true; });
  selectTask(selected, true);
  renderPicker();
})();
