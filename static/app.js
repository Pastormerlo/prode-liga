(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const CSRF = $('meta[name="csrf"]')?.content || '';
  const GROUP = $('meta[name="group"]')?.content || '';

  async function api(path, data) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': CSRF },
      body: JSON.stringify({ group: GROUP, ...(data || {}) }),
    });
    let j = {};
    try { j = await r.json(); } catch (_) { /* respuesta sin JSON */ }
    if (r.status === 429) throw new Error(j.error || 'Demasiados intentos. Esperá unos minutos.');
    if (!r.ok || j.ok === false) throw new Error(j.error || 'Algo salió mal. Probá de nuevo.');
    return j;
  }

  let toastTimer;
  function toast(msg, bad) {
    const t = $('#toast');
    t.textContent = msg;
    t.className = 'show' + (bad ? ' bad' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.className = ''), 2600);
  }

  // ---------------------------------------------------------------- pestañas
  const tabs = $$('[data-tab]');
  function showTab(name) {
    if (!$('#tab-' + name)) name = 'pronosticos';
    $$('.tab-panel').forEach(p => (p.hidden = p.id !== 'tab-' + name));
    tabs.forEach(a => a.classList.toggle('on', a.dataset.tab === name));
    try { localStorage.setItem('prode-tab', name); } catch (_) {}
  }
  if (tabs.length) {
    tabs.forEach(a => a.addEventListener('click', e => {
      e.preventDefault();
      history.replaceState(null, '', '#' + a.dataset.tab);
      showTab(a.dataset.tab);
      window.scrollTo({ top: 0 });
    }));
    let start = location.hash.slice(1);
    if (!start) { try { start = localStorage.getItem('prode-tab') || ''; } catch (_) {} }
    showTab(start || 'pronosticos');
  }

  // ---------------------------------------------------------------- anotarse / entrar
  $$('[data-join]').forEach(b => b.addEventListener('click', () => {
    $$('[data-join]').forEach(x => x.classList.toggle('on', x === b));
    $('#form-nuevo').hidden = b.dataset.join !== 'nuevo';
    $('#form-volver').hidden = b.dataset.join !== 'volver';
  }));
  $$('#icon-pick .ic').forEach(b => b.addEventListener('click', () => {
    $$('#icon-pick .ic').forEach(x => x.classList.toggle('on', x === b));
  }));
  $$('input.pin').forEach(i => i.addEventListener('input', () => (i.value = i.value.replace(/\D/g, '').slice(0, 4))));

  function bindForm(id, path, extra) {
    const f = $(id);
    if (!f) return;
    f.addEventListener('submit', async e => {
      e.preventDefault();
      const msg = $('.form-msg', f);
      const btn = $('button[type=submit]', f);
      msg.textContent = ''; msg.className = 'form-msg';
      const data = { name: f.name.value.trim(), pin: f.pin.value, ...(extra ? extra() : {}) };
      btn.disabled = true;
      try {
        await api(path, data);
        location.hash = '#pronosticos';
        location.reload();
      } catch (err) {
        msg.textContent = err.message; msg.className = 'form-msg err';
        btn.disabled = false;
      }
    });
  }
  bindForm('#form-nuevo', '/api/registro', () => ({
    icon: $('#icon-pick .ic.on')?.dataset.icon,
    clave: $('#form-nuevo input[name=clave]')?.value || '',
  }));
  bindForm('#form-volver', '/api/ingresar');

  // ---------------------------------------------------------------- menú del usuario
  const meBtn = $('#btn-me'), menu = $('#me-menu');
  if (meBtn && menu) {
    meBtn.addEventListener('click', e => { e.stopPropagation(); menu.hidden = !menu.hidden; });
    document.addEventListener('click', e => { if (!menu.contains(e.target)) menu.hidden = true; });
    $('#btn-logout').addEventListener('click', async () => {
      if (!confirm('¿Salir? Para volver vas a necesitar tu nombre y PIN.')) return;
      await api('/api/salir'); location.reload();
    });
    $$('[data-set-icon]').forEach(b => b.addEventListener('click', async () => {
      try { await api('/api/perfil', { icon: b.dataset.setIcon }); location.reload(); }
      catch (err) { toast(err.message, true); }
    }));
  }

  // ---------------------------------------------------------------- pronósticos
  $$('.match').forEach(card => {
    const inputs = $$('.stepper input', card);
    if (inputs.length !== 2) return;
    const tie = $('.tie', card), save = $('.save', card), msg = $('.save-msg', card);
    let adv = $('.tie-opts .on', card)?.dataset.adv || null;

    const vals = () => inputs.map(i => (i.value === '' ? null : parseInt(i.value, 10)));
    function dirty() {
      save.hidden = false;
      msg.textContent = '';
      card.classList.add('dirty');
    }
    function refreshTie() {
      const [a, b] = vals();
      const isTie = a !== null && b !== null && a === b;
      // al pasar a empate, nadie viene marcado: hay que elegir quién pasa
      if (isTie && tie.hidden) {
        adv = null;
        $$('.tie-opts button', card).forEach(x => x.classList.toggle('on', false));
      }
      tie.hidden = !isTie;
    }
    $$('.stepper', card).forEach(st => {
      const inp = $('input', st);
      $('.up', st).addEventListener('click', () => {
        inp.value = Math.min(20, (parseInt(inp.value, 10) || 0) + 1);
        const other = inputs.find(i => i !== inp);
        if (other.value === '') other.value = 0;
        refreshTie(); dirty();
      });
      $('.down', st).addEventListener('click', () => {
        inp.value = Math.max(0, (parseInt(inp.value, 10) || 0) - 1);
        const other = inputs.find(i => i !== inp);
        if (other.value === '') other.value = 0;
        refreshTie(); dirty();
      });
      inp.addEventListener('input', () => {
        if (inp.value !== '') inp.value = Math.max(0, Math.min(20, parseInt(inp.value, 10) || 0));
        refreshTie(); dirty();
      });
      inp.addEventListener('focus', () => inp.select());
    });
    $$('.tie-opts button', card).forEach(b => b.addEventListener('click', () => {
      adv = b.dataset.adv;
      $$('.tie-opts button', card).forEach(x => x.classList.toggle('on', x === b));
      dirty();
    }));
    save.addEventListener('click', async () => {
      const [a, b] = vals();
      if (a === null || b === null) return toast('Cargá los goles de los dos equipos', true);
      if (a === b && !adv) { tie.classList.add('shake'); setTimeout(() => tie.classList.remove('shake'), 500); return toast('Elegí quién pasa', true); }
      save.disabled = true;
      try {
        await api('/api/pronostico', { match_id: +card.dataset.id, goals_a: a, goals_b: b, advance: a === b ? adv : null });
        save.hidden = true;
        msg.textContent = '✓ Guardado';
        msg.classList.remove('pop'); void msg.offsetWidth; msg.classList.add('pop');
        card.classList.remove('dirty', 'needs');
        toast('Pronóstico guardado');
        updatePending();
      } catch (err) {
        toast(err.message, true);
      } finally {
        save.disabled = false;
      }
    });
  });

  function updatePending() {
    const n = $$('.match.needs').length;
    const dot = $('[data-tab="pronosticos"] .dot');
    if (dot) { dot.textContent = n; dot.hidden = n === 0; }
  }

  // ---------------------------------------------------------------- cuenta regresiva
  function fmtLeft(ms) {
    const m = Math.floor(ms / 60000), h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (d >= 1) return `Cierra en ${d}d ${h % 24}h`;
    if (h >= 1) return `Cierra en ${h}h ${m % 60}m`;
    return `Cierra en ${Math.max(1, m)}m`;
  }
  function tick() {
    const now = Date.now();
    $$('.countdown').forEach(c => {
      const left = new Date(c.dataset.until).getTime() - now;
      if (left <= 0) {
        c.textContent = '🔒 Cerrado';
        const card = c.closest('.match');
        if (card && !card.classList.contains('is-locked')) {
          card.classList.add('is-locked');
          $$('button, input', card).forEach(x => (x.disabled = true));
        }
      } else {
        c.textContent = fmtLeft(left);
        c.classList.toggle('soon', left < 3 * 3600 * 1000);
      }
    });
  }
  tick(); setInterval(tick, 30000);

  // ---------------------------------------------------------------- admin
  const syncBtn = $('#btn-sync');
  if (syncBtn) syncBtn.addEventListener('click', async () => {
    syncBtn.disabled = true;
    const old = syncBtn.textContent;
    syncBtn.textContent = 'Leyendo Promiedos…';
    try {
      const r = await api('/api/admin/sync');
      toast(r.cambios.length ? `${r.cambios.length} cambios cargados` : 'Sin cambios: todo al día');
      setTimeout(() => location.reload(), 900);
    } catch (err) {
      toast(err.message, true);
      syncBtn.disabled = false; syncBtn.textContent = old;
    }
  });

  const newGroup = $('#form-grupo');
  if (newGroup) newGroup.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api('/api/admin/grupo', { action: 'crear', name: newGroup.name.value, clave: newGroup.clave.value });
      toast('Grupo creado');
      setTimeout(() => location.reload(), 600);
    } catch (err) { toast(err.message, true); }
  });

  $$('.admin-row').forEach(row => row.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const id = +row.dataset.id, uid = +row.dataset.uid, gid = +row.dataset.gid;
    try {
      switch (b.dataset.act) {
        case 'save-group':
          await api('/api/admin/grupo', { action: 'editar', group_id: gid,
            name: $('.g-name', row).value, clave: $('.g-clave', row).value });
          break;
        case 'delete-group':
          if (!confirm('¿Borrar este grupo con todos sus participantes y pronósticos? No se puede deshacer.')) return;
          await api('/api/admin/grupo', { action: 'borrar', group_id: gid });
          break;
        case 'copy-link':
          await navigator.clipboard.writeText(location.origin + b.dataset.link);
          return toast('Link copiado');
        case 'save-result': {
          const ga = $('[data-g=a]', row).value, gb = $('[data-g=b]', row).value;
          if (ga === '' || gb === '') return toast('Cargá los dos marcadores', true);
          await api('/api/admin/resultado', { match_id: id, goals_a: +ga, goals_b: +gb, advance: $('.adv', row).value || null });
          break;
        }
        case 'clear-result':
          if (!confirm('¿Borrar el resultado y volver a leerlo de Promiedos?')) return;
          await api('/api/admin/resultado', { match_id: id, clear: true });
          break;
        case 'save-ko':
          await api('/api/admin/horario', { match_id: id, kickoff: $('.ko', row).value });
          break;
        case 'reset-pin': {
          const pin = prompt('Nuevo PIN de 4 números para este participante:');
          if (!pin) return;
          await api('/api/admin/usuario', { user_id: uid, action: 'pin', pin });
          break;
        }
        case 'delete-user':
          if (!confirm('¿Borrar este participante y todos sus pronósticos? No se puede deshacer.')) return;
          await api('/api/admin/usuario', { user_id: uid, action: 'borrar' });
          break;
      }
      toast('Listo');
      setTimeout(() => location.reload(), 600);
    } catch (err) {
      toast(err.message, true);
    }
  }));
  // ---------------------------------------------------------------- festejos
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} },
  };

  function confetti(gold) {
    if (calm) return;
    const cv = document.createElement('canvas');
    cv.className = 'confetti';
    document.body.appendChild(cv);
    const ctx = cv.getContext('2d');
    const W = cv.width = innerWidth, H = cv.height = innerHeight;
    const colors = gold ? ['#f5c542', '#ffe08a', '#fff4cc', '#d9a520'] : ['#6cc4f5', '#ffffff', '#f5c542', '#2f8fd0', '#ff5d6c'];
    const ps = Array.from({ length: gold ? 220 : 160 }, () => ({
      x: W / 2 + (Math.random() - .5) * W * .3, y: H * .35,
      vx: (Math.random() - .5) * 14, vy: -Math.random() * 15 - 5,
      w: 6 + Math.random() * 6, h: 8 + Math.random() * 8,
      r: Math.random() * 6, vr: (Math.random() - .5) * .3,
      c: colors[Math.floor(Math.random() * colors.length)],
    }));
    const t0 = performance.now();
    (function frame(t) {
      ctx.clearRect(0, 0, W, H);
      ps.forEach(p => {
        p.vy += .35; p.vx *= .99; p.x += p.vx; p.y += p.vy; p.r += p.vr;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r);
        ctx.fillStyle = p.c; ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h * Math.cos(p.r * 2));
        ctx.restore();
      });
      if (t - t0 < 4500) requestAnimationFrame(frame); else cv.remove();
    })(t0);
  }

  function celebrate(emoji, title, items, gold) {
    const box = $('#celebrate');
    $('#cel-emoji').textContent = emoji;
    $('#cel-title').textContent = title;
    const ul = $('#cel-list');
    ul.replaceChildren(...items.map(([txt, pts]) => {
      const li = document.createElement('li');
      const a = document.createElement('span'); a.textContent = txt;
      li.appendChild(a);
      if (pts) { const b = document.createElement('span'); b.className = 'chip pts p' + pts; b.textContent = '+' + pts; li.appendChild(b); }
      return li;
    }));
    box.classList.toggle('gold', !!gold);
    box.hidden = false;
    requestAnimationFrame(() => box.classList.add('show'));
    return new Promise(res => {
      const close = () => { box.classList.remove('show'); setTimeout(() => (box.hidden = true), 250); res(); };
      $('#cel-ok').onclick = close;
      box.onclick = e => { if (e.target === box) close(); };
    });
  }

  const festEl = $('#fest');
  if (festEl) (async () => {
    const F = JSON.parse(festEl.textContent);
    const K = 'prode-fest-' + F.key;
    const saved = store.get(K);
    const state = saved || { seen: [], pos: null, prev: null, champ: false };

    // flechita de puestos en la tabla
    if (F.pos != null) {
      if (state.pos != null && state.pos !== F.pos) { state.prev = state.pos; }
      state.pos = F.pos;
      const mv = $('#my-move');
      if (mv && state.prev != null && state.prev !== F.pos) {
        const d = state.prev - F.pos;
        mv.textContent = (d > 0 ? '▲' : '▼') + Math.abs(d);
        mv.className = 'move ' + (d > 0 ? 'up' : 'down');
        mv.title = d > 0 ? `Subiste ${d} puesto${d > 1 ? 's' : ''}` : `Bajaste ${-d} puesto${d < -1 ? 's' : ''}`;
        mv.hidden = false;
      }
    }

    // la primera vez en este celular no se festeja lo viejo
    const fresh = saved ? F.hits.filter(h => !state.seen.includes(h.id)) : [];
    state.seen = F.hits.map(h => h.id);
    const champNow = F.champ && !state.champ;
    state.champ = state.champ || F.champ;
    store.set(K, state);

    if (fresh.length && $('#celebrate')) {
      const exactos = fresh.filter(h => h.exacto).length;
      const total = fresh.reduce((a, h) => a + h.pts, 0);
      const title = exactos ? (exactos > 1 ? `¡${exactos} exactos!` : '¡Clavaste el resultado!') : `¡Sumaste ${total} punto${total > 1 ? 's' : ''}!`;
      if (exactos) confetti(false);
      await celebrate(exactos ? '🎯' : '👏', title, fresh.map(h => [(h.exacto ? 'Exacto · ' : '') + h.txt, h.pts]));
    }
    if (champNow && $('#celebrate')) {
      confetti(true);
      setTimeout(() => confetti(true), 900);
      await celebrate('🏆', '¡Campeón del prode!', [[`Terminaste 1° del grupo · campeón ${F.champ_team || ''}`.trim(), 0]], true);
    }
  })();

})();
