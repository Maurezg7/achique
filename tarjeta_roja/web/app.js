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
      window.scrollTo(0, y); revisarNuevos(); reaplicarFoco();
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

// Asistente del juez: "Mostrame dónde" / "ver" resaltan el elemento (y lo mantienen resaltado tras cada refresco).
let foco = null, focoHasta = 0;
function marcar(sel, desplazar) {
  document.querySelectorAll('.foco').forEach(e => e.classList.remove('foco'));
  let el = null; try { el = sel && document.querySelector(sel); } catch (e) {}
  if (!el) return null;
  el.classList.add('foco');
  if (desplazar) el.scrollIntoView({behavior: 'smooth', block: 'center'});
  return el;
}
function reaplicarFoco() {
  if (paso >= 0) return mostrarPaso(false);
  if (foco && Date.now() < focoHasta) marcar(foco, false); else if (foco) { foco = null; marcar(null); }
}
document.addEventListener('click', ev => {
  const b = ev.target.closest('[data-foco]');
  if (b) { foco = b.dataset.foco; focoHasta = Date.now() + 4000; marcar(foco, true); }
  if (ev.target.closest('[data-guia]')) iniciarGuia();
});

// Guía de la mesa: tour paso a paso por la pantalla del juez.
const PASOS = [
  {sel: '.marcador', t: 'El partido en vivo', d: 'Marcador y reloj del partido. Las detecciones de streams piratas llegan en tiempo real mientras se juega.'},
  {sel: '.duty', t: 'Juez de turno y auditoría', d: 'Solo el juez de turno puede decidir y firmar. El candado verde indica que la cadena de auditoría está íntegra.'},
  {sel: '.timeline', t: 'Línea de tiempo', d: 'Cada marca es un stream pirata detectado (ámbar = con riesgo de daño colateral). También muestra los cambios de turno.'},
  {sel: '.kpis', t: 'Indicadores', d: 'Cuántos expedientes esperan tu firma, bloqueos activos, clientes cubiertos y la demora media detección → bloqueo.'},
  {sel: '#asistente', t: 'Asistente del juez', d: 'Vigila la plataforma y te dice el siguiente paso. Tocá "Mostrame dónde" para ubicarlo. Recomienda, nunca firma.'},
  {sel: 'main .card:not(.reclamo)', t: 'Un expediente', d: 'Cada stream pirata llega como expediente sellado: servidor, IP, organización y la marca de agua de la señal oficial.', falta: 'Todavía no llegó ninguno: aparece acá apenas haya una detección.'},
  {sel: 'main .card:not(.reclamo) .alerta, main .card:not(.reclamo) .limpio', t: 'Riesgo de daño colateral', d: 'Si la IP también sirve a otros sitios, la plataforma lo marca en rojo y propone bloquear solo el dominio.'},
  {sel: 'main .card:not(.reclamo) .pedido', t: 'Orden propuesta', d: 'Qué se va a bloquear (IP o dominio) y hasta cuándo. Vence sola al terminar el partido.'},
  {sel: 'main .card:not(.reclamo) .asis', t: 'Explicación del asistente', d: 'Abrila para leer en criollo por qué se propone IP o dominio y qué conviene revisar antes de firmar.'},
  {sel: 'main .card:not(.reclamo) .btn.aprobar', t: 'Aprobar y firmar', d: 'Con un clic firmás con tu clave de turno y la orden sale a cada proveedor en el tipo de bloqueo que acepta. "Rechazar" pide un motivo.'},
  {sel: '.card.reclamo', t: 'Reclamos', d: 'Si un sitio legítimo quedó bloqueado, aparece acá con la propuesta de la plataforma (levantar y precisar). Vos decidís.', falta: 'No hay reclamos ahora: aparecen acá cuando algún sitio reclame.'},
  {sel: 'aside .lista', t: 'Órdenes en proveedores', d: 'El estado de cada bloqueo por proveedor (aplicada, fallida, vencida…) y el porcentaje de clientes cubiertos.'},
  {sel: '.pub', t: 'Registro público', d: 'Vista de transparencia: qué se bloqueó, cuándo, por orden de quién y hasta cuándo, sin evidencia interna.'},
];
const guia = document.getElementById('guia');
let paso = -1;
function mostrarPaso(desplazar) {
  const p = PASOS[paso], el = marcar(p.sel, desplazar);
  const clave = paso + ':' + !!el;
  if (!desplazar && guia.dataset.paso === clave) return;
  guia.dataset.paso = clave;
  guia.innerHTML = `<small>Guía de la mesa · ${paso + 1} de ${PASOS.length}</small><h4>${p.t}</h4><p>${p.d}</p>` +
    (el ? '' : `<p class="falta">${p.falta || 'No está en pantalla en este momento.'}</p>`) +
    `<nav><button class="saltar" data-g="fin">Saltar guía</button>${paso ? '<button data-g="-1">Anterior</button>' : ''}` +
    `<button class="sig" data-g="1">${paso === PASOS.length - 1 ? 'Terminar' : 'Siguiente'}</button></nav>`;
}
function iniciarGuia() { paso = 0; guia.hidden = false; delete guia.dataset.paso; mostrarPaso(true); }
function terminarGuia() { paso = -1; guia.hidden = true; marcar(null); localStorage.setItem('tr-guia-vista', '1'); }
guia.addEventListener('click', ev => {
  const g = ev.target.dataset.g; if (!g) return;
  if (g === 'fin' || paso + Number(g) >= PASOS.length) return terminarGuia();
  paso = Math.max(0, paso + Number(g)); mostrarPaso(true);
});
document.addEventListener('keydown', ev => { if (paso >= 0 && ev.key === 'Escape') terminarGuia(); });

refrescar(); setInterval(refrescar, 1500);
if (FRAG === '/fragmento' && !localStorage.getItem('tr-guia-vista')) setTimeout(iniciarGuia, 1200);
