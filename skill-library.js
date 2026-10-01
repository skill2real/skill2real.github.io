/* Skill browser for the paper's two memory levels. */
(() => {
  const { entries, categories } = skillLibraryData;
  const list = document.querySelector('#skill-list');
  const categoryPicker = document.querySelector('#skill-categories');
  const actionPicker = document.querySelector('#skill-action');
  const search = document.querySelector('#skill-search');
  const reader = document.querySelector('#skill-reader');
  const pageSize = 6;
  let layer = 'all';
  let category = 'all';
  let page = 0;
  let selected = entries[0].id;
  let results = [];
  const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  const categoryName = id => categories.find(c => c.id === id).name;
  function selectEntry(entry, announce = true) {
    selected = entry.id;
    reader.hidden = false;
    document.querySelector('#skill-reader-title').textContent = entry.title;
    document.querySelector('#skill-reader-meta').textContent = `${entry.layer} / ${categoryName(entry.category)}`;
    document.querySelector('#skill-reader-tags').innerHTML = entry.tags.map(t => `<span>${escape(t)}</span>`).join('');
    document.querySelector('#skill-reader-fields').innerHTML = entry.fields.map(([heading, text]) => heading === 'Code template'
      ? `<section><h4>${escape(heading)}</h4><pre class="skill-card-code"><code>${escape(text)}</code></pre></section>`
      : `<section><h4>${escape(heading)}</h4>${text.split('\n\n').map(paragraph => `<p>${escape(paragraph)}</p>`).join('')}</section>`).join('');
    document.querySelector('#skill-reader-fields').scrollTop = 0;
    list.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.skill === selected)));
    if (announce) document.querySelector('#skill-live-status').textContent = `${entry.title}. ${entry.layer}. Decision selected.`;
  }
  function configureLayer() {
    const layerEntries = entries.filter(e => layer === 'all' || e.layer === layer);
    const tags = [...new Set(layerEntries.flatMap(e => e.tags))].sort();
    actionPicker.innerHTML = '<option value="all">All actions</option>' + tags.map(tag => `<option value="${escape(tag)}">${escape(tag)}</option>`).join('');
    actionPicker.closest('label').hidden = layer === 'Brain';
    document.querySelectorAll('[data-memory-level]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.memoryLevel === layer)));
    category = 'all';
    page = 0;
  }
  function matchesBase(entry) {
    const query = search.value.trim().toLowerCase();
    return (layer === 'all' || entry.layer === layer)
      && (actionPicker.value === 'all' || entry.tags.includes(actionPicker.value))
      && (!query || [entry.title, categoryName(entry.category), ...entry.tags, ...entry.fields.map(field => field[1])].join(' ').toLowerCase().includes(query));
  }
  function renderCategories(base) {
    categoryPicker.replaceChildren();
    [{id:'all',name:'All categories'}, ...categories.filter(c => layer === 'all' || c.layer === layer)].forEach(item => {
      const count = base.filter(entry => item.id === 'all' || entry.category === item.id).length;
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.skillCategory = item.id;
      button.innerHTML = `${escape(item.name)} <span>${count}</span>`;
      button.setAttribute('aria-pressed', String(category === item.id));
      button.addEventListener('click', () => { category = item.id; page = 0; render(); categoryPicker.querySelector(`[data-skill-category="${item.id}"]`).focus({preventScroll:true}); });
      categoryPicker.append(button);
    });
  }
  function render() {
    const base = entries.filter(matchesBase);
    results = base.filter(entry => category === 'all' || entry.category === category);
    const pageCount = Math.max(1, Math.ceil(results.length / pageSize));
    page = Math.min(page, pageCount - 1);
    const visible = results.slice(page * pageSize, (page + 1) * pageSize);
    renderCategories(base);
    document.querySelector('#skill-category-description').textContent = category === 'all'
      ? (layer === 'all' ? 'Browse local manipulation and task-level composition skills together.' : layer === 'Cerebellum' ? 'Local knowledge for perception, grasping, placement and contact interaction.' : 'Task-level knowledge for identity, bindings, destinations, ordering and supported progress.')
      : categories.find(c => c.id === category).description;
    document.querySelector('#skill-result-count').textContent = `${results.length} ${results.length === 1 ? 'skill' : 'skills'}`;
    document.querySelector('#skill-page-status').textContent = results.length ? `${page * pageSize + 1}–${page * pageSize + visible.length} of ${results.length}` : 'No matches';
    document.querySelector('#skill-prev').disabled = page === 0;
    document.querySelector('#skill-next').disabled = page >= pageCount - 1;
    list.replaceChildren();
    visible.forEach(entry => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.skill = entry.id;
      button.className = 'skill-choice';
      button.setAttribute('aria-controls', 'skill-reader');
      button.innerHTML = `<span>${escape(categoryName(entry.category))}</span><strong>${escape(entry.title)}</strong>`;
      button.addEventListener('click', () => selectEntry(entry));
      list.append(button);
    });
    if (!visible.length) {
      const empty = document.createElement('p');
      empty.className = 'skill-empty';
      empty.textContent = 'No skills match these filters. Try a broader term or another category.';
      list.append(empty);
      reader.hidden = true;
    } else {
      selectEntry(visible.find(entry => entry.id === selected) || visible[0], false);
    }
    document.querySelector('#skill-live-status').textContent = `${results.length} ${layer === 'all' ? 'total' : layer} skills match the filters.`;
  }
  document.querySelectorAll('[data-memory-level]').forEach(button => button.addEventListener('click', () => { layer = button.dataset.memoryLevel; configureLayer(); render(); }));
  actionPicker.addEventListener('change', () => { page = 0; render(); });
  search.addEventListener('input', () => { page = 0; render(); });
  document.querySelector('#skill-prev').addEventListener('click', () => { page--; render(); });
  document.querySelector('#skill-next').addEventListener('click', () => { page++; render(); });
  document.querySelector('#skill-template-link').addEventListener('click', () => {
    const template = document.querySelector('#skill-api-template');
    template.scrollIntoView({behavior: 'smooth', block: 'start'});
  });
  document.querySelector('.skill-api-link').addEventListener('click', () => { document.querySelector('#standard-api').open = true; });
  configureLayer();
  render();
})();
