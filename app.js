const hero = document.querySelector('#hero-video');
const toggle = document.querySelector('#hero-toggle');
const film = document.querySelector('#project-film');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let manuallyPaused = false;
let heroVisible = false;
let heroLoaded = false;
let lastFocus;

function loadHero() {
  if (heroLoaded) return;
  hero.load();
  heroLoaded = true;
}
function syncHeroControl() {
  toggle.classList.toggle('playing', !hero.paused);
  toggle.setAttribute('aria-label', hero.paused ? 'Play background video' : 'Pause background video');
}
hero.addEventListener('play', syncHeroControl);
hero.addEventListener('pause', syncHeroControl);
toggle.addEventListener('click', () => {
  if (hero.paused) { manuallyPaused = false; loadHero(); hero.play().catch(syncHeroControl); }
  else { manuallyPaused = true; hero.pause(); }
});
const observer = new IntersectionObserver(entries => {
  heroVisible = entries[0].isIntersecting;
  if (heroVisible && !manuallyPaused && !reducedMotion.matches && !navigator.connection?.saveData && film.paused && ![...document.querySelectorAll('.task-video')].some(v => !v.paused) && !document.hidden) {
    loadHero(); hero.play().catch(syncHeroControl);
  } else hero.pause();
}, { threshold: 0.2 });
observer.observe(hero);
film.addEventListener('play', () => {
  hero.pause();
  document.querySelectorAll('.task-video').forEach(v => v.pause());
});
document.querySelectorAll('.task-video').forEach(video => video.addEventListener('play', () => {
  hero.pause();
  film.pause();
  document.querySelectorAll('.task-video').forEach(other => { if (other !== video) other.pause(); });
}));
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { hero.pause(); document.querySelectorAll('.task-video').forEach(v => v.pause()); }
  else if (heroVisible && heroLoaded && !manuallyPaused && !reducedMotion.matches && film.paused) hero.play().catch(syncHeroControl);
});
reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) hero.pause(); });

const chapterButtons = [...document.querySelectorAll('[data-seek]')];
chapterButtons.forEach(button => button.addEventListener('click', () => {
  const seek = () => { film.currentTime = Number(button.dataset.seek); film.play().catch(() => film.focus()); };
  if (film.readyState >= 1) seek();
  else { film.addEventListener('loadedmetadata', seek, { once: true }); film.load(); }
}));
film.addEventListener('timeupdate', () => {
  let selected = -1;
  chapterButtons.forEach((button, index) => { if (film.currentTime >= Number(button.dataset.seek)) selected = index; });
  chapterButtons.forEach((button, index) => {
    button.classList.toggle('active', index === selected);
    if (index === selected) button.setAttribute('aria-current', 'true');
    else button.removeAttribute('aria-current');
  });
});

const dialog = document.querySelector('#image-dialog');
document.querySelectorAll('[data-enlarge]').forEach(button => button.addEventListener('click', () => {
  lastFocus = button;
  document.querySelector('#dialog-image').src = button.dataset.enlarge;
  document.querySelector('#dialog-image').alt = button.dataset.title;
  document.querySelector('#image-dialog-title').textContent = button.dataset.title;
  dialog.showModal();
}));
document.querySelector('#close-dialog').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } });
dialog.addEventListener('close', () => lastFocus?.focus());
document.querySelectorAll('video').forEach(video => video.addEventListener('error', () => {
  const message = document.querySelector('#playback-message');
  message.textContent = 'Video could not load. Please try the download link or reload the page.';
  message.hidden = false;
  setTimeout(() => { message.hidden = true; }, 8000);
}));
