// Una sola ventana en vivo: pide el contenido cada 1,5 s y lo reemplaza en su lugar (sin recargar la página).
const FRAG = document.body.dataset.frag, app = document.getElementById('app'), toast = document.getElementById('toast');
let ultimo = '', ocupado = false, conocidos = null;
function avisar(texto) {
  toast.textContent = texto; toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 4000);
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)(), o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination); o.frequency.value = 880; g.gain.setValueAtTime(.08, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(.0001, ctx.currentTime + .35); o.start(); o.stop(ctx.currentTime + .35);
  } catch (e) {}
  if ('Notification' in window && Notification.permission === 'granted') new Notification('Mesa del juez', {body: texto});
}
function revisarNuevos() {
  const meta = document.getElementById('meta'); if (!meta) return;
  const ids = (meta.dataset.pendientes + ',' + meta.dataset.reclamos).split(',').filter(Boolean);
  const nuevos = conocidos ? ids.filter(i => !conocidos.has(i)) : [];
  conocidos = new Set([...(conocidos || []), ...ids]);
  const pend = meta.dataset.pendientes.split(',').filter(Boolean).length;
  document.title = (pend ? '(' + pend + ') ' : '') + 'Tarjeta Roja · Mesa del juez';
  if (nuevos.length) avisar(nuevos.length === 1 ? 'Nuevo para decidir: ' + nuevos[0] : nuevos.length + ' nuevos para decidir');
}
async function refrescar() {
  if (ocupado) return;
  try {
    const html = await (await fetch(FRAG, {cache: 'no-store'})).text();
    if (html !== ultimo) {
      const abiertos = [...document.querySelectorAll('details[open]')].map(d => d.id), y = window.scrollY;
      const antes = new Set([...app.querySelectorAll('[data-k]')].map(e => e.dataset.k));
      app.innerHTML = html; ultimo = html;
      // Solo se anima lo que aparece por primera vez; lo demás se reemplaza sin parpadear.
      app.querySelectorAll('[data-k]').forEach(e => { if (!antes.has(e.dataset.k)) e.classList.add('nuevo'); });
      abiertos.forEach(id => { const d = document.getElementById(id); if (d) d.open = true; });
      window.scrollTo(0, y); revisarNuevos();
    }
  } catch (e) { /* el servidor puede estar reiniciando: reintenta */ }
}
document.addEventListener('submit', async ev => {
  ev.preventDefault();
  const boton = ev.submitter, form = ev.target, datos = new URLSearchParams();
  if (boton && boton.name) datos.append(boton.name, boton.value);
  if (boton && boton.value === 'rechazar') {
    const motivo = prompt('Motivo del rechazo (queda en la auditoría):', '');
    if (motivo === null) return;
    datos.append('motivo', motivo);
  }
  ocupado = true;
  form.querySelectorAll('button').forEach(b => b.disabled = true);
  try { await fetch(form.action, {method: 'POST', body: datos, headers: {'X-Requested-With': 'fetch'}}); }
  finally { ocupado = false; ultimo = ''; refrescar(); }
});
const nb = document.getElementById('notif');
if (FRAG === '/fragmento' && 'Notification' in window && Notification.permission === 'default') {
  nb.hidden = false; nb.onclick = () => Notification.requestPermission().then(() => nb.hidden = true);
}
refrescar(); setInterval(refrescar, 1500);
