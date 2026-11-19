(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const CSRF = $('meta[name="csrf"]')?.content || '';

  async function api(path, data) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': CSRF },
      body: JSON.stringify(data || {}),
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
  bindForm('#form-nuevo', '/api/registro', () => ({ icon: $('#icon-pick .ic.on')?.dataset.icon }));
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
      tie.hidden = !(a !== null && b !== null && a === b);
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

  $$('.admin-row').forEach(row => row.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const id = +row.dataset.id, uid = +row.dataset.uid;
    try {
      switch (b.dataset.act) {
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
})();
