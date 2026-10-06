(() => {
  const slides = [...document.querySelectorAll('.slide')];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hooks = [];
  let cur = 0, step = 0;

  // The HTML holds each number's final text; countUp animates from 0 to it.
  function countUp(el) {
    const target = parseFloat(el.dataset.count), fmt = el.dataset.format || 'int';
    const show = v => fmt === 'usd2' ? '$' + v.toFixed(2)
      : fmt === 'usd3' ? '$' + v.toFixed(3)
      : fmt === 'pct' ? v.toFixed(1) + '%'
      : fmt === 'dec' ? (v < 0 ? '−' : '') + Math.abs(v).toFixed(1)
      : Math.round(v).toLocaleString('en-US');
    if (reduce) { el.textContent = show(target); return; }
    const t0 = performance.now(), dur = 1600;
    const tick = t => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 4);
      el.textContent = show(target * e);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // slide hooks
  // Technical solution: each step of the walkthrough highlights its part of the architecture
  const mini = document.getElementById('archMini');
  hooks.push((s, st) => {
    if (!s.classList.contains('s-how')) return;
    const shown = [...s.querySelectorAll('[data-focus]')].filter(li => +li.dataset.step <= st);
    const last = shown.at(-1);
    const focus = new Set((last?.dataset.focus || '').split(' '));
    mini.classList.add('focusing');
    mini.querySelectorAll('[data-node]').forEach(n => n.classList.toggle('focus', focus.has(n.dataset.node)));
    s.querySelectorAll('.walk li').forEach(li => li.classList.toggle('current', li === last));
    s.querySelectorAll('.walk-detail > div').forEach((d, i) => d.classList.toggle('current', i === shown.length - 1));
  });
  // Cloud switch (AWS / any cloud): renames every [data-term] (the diagram, the walkthrough, the footer).
  // Like a theme switch, but the deck always opens on AWS: nothing is remembered.
  const terms = JSON.parse(document.getElementById('cloudTerms').textContent);
  const CLOUDS = ['aws', 'generic'];
  const cloudBox = document.getElementById('cloud');
  let cloud = 'aws';
  // A name wider than its box shrinks to fit, so a long equivalent never spills out
  function fitTerms() {
    document.querySelectorAll('.arch .node').forEach(node => {
      const room = +node.querySelector('rect').getAttribute('width') - 16;
      node.querySelectorAll('tspan[data-term]').forEach(t => {
        t.style.fontSize = '';
        const len = t.getComputedTextLength();
        if (len > room) t.style.fontSize = (parseFloat(getComputedStyle(t).fontSize) * room / len).toFixed(1) + 'px';
      });
    });
  }
  function setCloud(c) {
    cloud = c;
    document.querySelectorAll('[data-term]').forEach(el => {
      el.textContent = terms[el.dataset.term][c];
      if (el.classList.contains('cloud-note')) el.hidden = c === 'aws';
    });
    cloudBox.querySelectorAll('button').forEach(b => b.setAttribute('aria-checked', b.dataset.cloud === c));
    fitTerms();
  }
  cloudBox.querySelectorAll('button').forEach(b => b.onclick = () => setCloud(b.dataset.cloud));
  document.fonts?.ready.then(fitTerms);
  // The switch shows only on the slide it changes
  hooks.push(s => cloudBox.classList.toggle('show', s.classList.contains('s-how')));

  // Model evaluation: the finalist switch (the winner, v12, by default; the runner-up is v11) moves every bar and number to that prompt's value
  const evSlide = document.querySelector('.s-eval');
  const evBox = document.getElementById('evPrompt');
  let prompt = 'v12';
  function tween(el, from, to) {
    const show = v => el.dataset.fmt === 'dec2' ? v.toFixed(2) : Math.round(v) + (el.dataset.fmt === 'pct' ? '%' : '');
    if (reduce) { el.textContent = show(to); return; }
    const t0 = performance.now();
    const tick = t => {
      const p = Math.min(1, (t - t0) / 900), e = 1 - Math.pow(1 - p, 3);
      el.textContent = show(from + (to - from) * e);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  function setPrompt(p, scope = evSlide, fromZero = false) {
    const was = prompt;
    prompt = p;
    scope.querySelectorAll('[data-v11]').forEach(el => {
      tween(el, fromZero ? 0 : +el.dataset[was], +el.dataset[p]);
      el.closest('.ev-bar')?.querySelector('i').style.setProperty('--v', el.dataset[p] + '%');
    });
    evSlide.querySelectorAll('[data-ev-p]').forEach(el => el.textContent = p === 'v12' ? 'winning' : 'runner-up');
    evBox.querySelectorAll('button').forEach(b => b.setAttribute('aria-checked', b.dataset.p === p));
  }
  evBox.querySelectorAll('button').forEach(b => b.onclick = () => { if (b.dataset.p !== prompt) setPrompt(b.dataset.p); });
  // Each card's numbers count up from 0 the first time its step shows; leaving the slide resets them
  const evShown = new Set();
  hooks.push((s, st) => {
    if (s !== evSlide) { evShown.clear(); return; }
    evSlide.querySelectorAll('[data-step]').forEach(card => {
      if (!card.querySelector('[data-v11]') || +card.dataset.step > st || evShown.has(card)) return;
      evShown.add(card);
      setPrompt(prompt, card, true);
    });
  });

  // Solution slide: the lens closes as the slide arrives
  hooks.push(s => document.getElementById('heroMark').classList.toggle('split', !s.classList.contains('s-solution')));

  function render() {
    document.activeElement?.closest?.('.cost')?.blur();
    slides.forEach((s, i) => {
      s.classList.toggle('active', i === cur);
      s.classList.toggle('past', i < cur);
      s.setAttribute('aria-hidden', i !== cur);
      if (i === cur) s.dataset.at = step;
    });
    const s = slides[cur];
    s.querySelectorAll('[data-step]').forEach(el => el.classList.toggle('on', +el.dataset.step <= step));

    // Numbers count up the first time their step shows; leaving the slide resets them
    slides.forEach((sl, i) => sl.querySelectorAll('[data-count]').forEach(el => {
      const holder = el.closest('[data-step]');
      const shown = i === cur && (!holder || +holder.dataset.step <= step);
      if (shown && !el.dataset.counted) { el.dataset.counted = '1'; countUp(el); }
      if (!shown) delete el.dataset.counted;
    }));
    hooks.forEach(h => h(s, step));

    const total = slides.reduce((n, sl) => n + 1 + +sl.dataset.steps, 0);
    const done = slides.slice(0, cur).reduce((n, sl) => n + 1 + +sl.dataset.steps, 0) + step + 1;
    document.getElementById('progress').style.width = (done / total * 100) + '%';
    document.getElementById('count').textContent = (cur + 1) + ' / ' + slides.length;
    document.getElementById('brand').classList.toggle('show', !s.classList.contains('s-solution'));
    showGuide();
  }

  // The guide shows on the opening screen; Esc shows or hides it anywhere
  let guideOpen = false;
  function showGuide() {
    document.getElementById('hint').style.opacity = guideOpen || (cur === 0 && step === 0) ? 1 : 0;
  }

  function next() {
    if (step < +slides[cur].dataset.steps) step++;
    else if (cur < slides.length - 1) { cur++; step = 0; }
    render();
  }
  function prev() {
    if (step > 0) step--;
    else if (cur > 0) { cur--; step = +slides[cur].dataset.steps; }
    render();
  }
  function go(i) { cur = Math.max(0, Math.min(slides.length - 1, i)); step = 0; render(); }

  // Short screens: shrink a slide's content so its last step still fits (desktop only)
  function fit() {
    slides.forEach(s => {
      const inner = s.querySelector('.inner');
      inner.style.zoom = '';
      if (innerWidth <= 900) return;
      const cs = getComputedStyle(s);
      const room = s.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
      const z = Math.min(1, room / inner.offsetHeight);
      if (z < 1) inner.style.zoom = z.toFixed(3);
    });
  }
  fit();
  addEventListener('resize', fit);
  document.fonts?.ready.then(fit);

  addEventListener('keydown', e => {
    // Space and Enter on a switch button pick that option instead of advancing
    if (e.target.closest?.('.cloud, .ev-prompt') && [' ', 'Enter'].includes(e.key)) return;
    if (e.key === 'Escape') { guideOpen = !guideOpen; showGuide(); return; }
    if (e.key === 'p' && slides[cur].classList.contains('s-eval')) { setPrompt(prompt === 'v12' ? 'v11' : 'v12'); return; }
    if (e.key === 'c' && cloudBox.classList.contains('show')) { setCloud(CLOUDS[(CLOUDS.indexOf(cloud) + 1) % CLOUDS.length]); return; }
    if (['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'].includes(e.key)) { e.preventDefault(); next(); }
    else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(e.key)) { e.preventDefault(); prev(); }
    else if (e.key === 'Home') go(0);
    else if (e.key === 'End') go(slides.length - 1);
    else if (/^[1-6]$/.test(e.key)) go(+e.key - 1);
    else if (e.key === 'f') toggleFs();
  });
  document.getElementById('next').onclick = next;
  document.getElementById('prev').onclick = prev;
  function toggleFs() { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.(); }
  document.getElementById('fs').onclick = toggleFs;

  // A click on the slide advances, except on tooltips, sources and links; swipe on touch
  document.getElementById('deck').addEventListener('click', e => { if (!e.target.closest('a,button,.cost,details,summary')) next(); });
  let tx = null;
  addEventListener('touchstart', e => { tx = e.touches[0].clientX; }, { passive: true });
  addEventListener('touchend', e => {
    if (tx === null) return;
    const dx = e.changedTouches[0].clientX - tx; tx = null;
    if (Math.abs(dx) > 50) dx < 0 ? next() : prev();
  });
  let wheelLock = 0;
  addEventListener('wheel', e => {
    if (innerWidth <= 900 || Date.now() < wheelLock || Math.abs(e.deltaY) < 20) return;
    wheelLock = Date.now() + 800; e.deltaY > 0 ? next() : prev();
  }, { passive: true });

  // Deep link: #3 opens slide 3, #3.2 opens it at step 2
  const m = location.hash.match(/^#(\d)(?:\.(\d))?$/);
  if (m) {
    cur = Math.max(0, Math.min(slides.length - 1, +m[1] - 1));
    step = Math.min(+(m[2] || 0), +slides[cur].dataset.steps);
  }
  render();
})();
