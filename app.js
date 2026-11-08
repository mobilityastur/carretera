"use strict";

// Los datos los genera la tarea programada del repo en la rama "datos".
const URL_DATOS = location.hostname === "localhost" || location.hostname === "127.0.0.1"
  ? "data/estado.json"
  : "https://raw.githubusercontent.com/mobilityastur/carretera/datos/estado.json";
const REFRESCO_MS = 3 * 60 * 1000;

const vista = document.getElementById("vista");
const visor = document.getElementById("visor");
let estado = null;
let filtro = "todas";
let mapa = null;

// ---------- utilidades ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ICO = {
  triangulo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 20h20L12 3zM12 10v4M12 17h.01"/></svg>',
  flecha: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>',
  atras: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg>',
  copo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v20M4.9 6.5l14.2 11M19.1 6.5 4.9 17.5"/></svg>',
};

function hace(isoStr) {
  if (!isoStr) return "—";
  const min = Math.round((Date.now() - new Date(isoStr).getTime()) / 60000);
  if (min < 1) return "ahora mismo";
  if (min < 60) return `hace ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `hace ${h} h`;
  return `hace ${Math.round(h / 24)} días`;
}
const fmtHora = (d) => d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
function fmtFecha(isoStr, conHora = true) {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  const hoy = new Date();
  const man = new Date(); man.setDate(hoy.getDate() + 1);
  const mismo = (a, b) => a.toDateString() === b.toDateString();
  let dia = mismo(d, hoy) ? "hoy" : mismo(d, man) ? "mañana"
    : d.toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
  return conHora ? `${dia} a las ${fmtHora(d)}` : dia;
}
function cuando(inc) {
  if (inc.fin) {
    const fin = new Date(inc.fin);
    if (fin - Date.now() > 3 * 86400000) return `Hasta el ${fin.toLocaleDateString("es-ES", { day: "numeric", month: "long" })}`;
    return `Hasta ${fmtFecha(inc.fin)}`;
  }
  if (inc.inicio) {
    const ini = new Date(inc.inicio);
    if (Date.now() - ini > 2 * 86400000) return `Desde el ${ini.toLocaleDateString("es-ES", { day: "numeric", month: "long", year: ini.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined })}`;
    return `Desde ${fmtFecha(inc.inicio)}`;
  }
  return "";
}
const etiquetaNivel = (z) => z.estado;
const tieneNieve = (z) => z.avisos.some((a) => /niev|nevad/i.test(a.fenomeno + a.titulo));
const avisoTexto = (a) => {
  const puertos = estado.zonas.filter((z) => z.tipo === "puerto").map((z) => z.nombre);
  const todos = a.zonas && puertos.every((p) => a.zonas.includes(p));
  const resto = todos ? a.zonas.filter((n) => !puertos.includes(n)) : a.zonas || [];
  const lista = (todos ? ["todos los puertos"] : []).concat(resto);
  const zonas = lista.length ? ` Afecta a ${lista.slice(0, 4).join(", ")}${lista.length > 4 ? "…" : ""}.` : "";
  const per = a.ahora ? `hasta ${fmtFecha(a.fin)}` : `${fmtFecha(a.inicio)} → ${fmtFecha(a.fin)}`;
  return `${a.zonaNombre}, ${per}.${zonas}`;
};

// ---------- carga ----------
async function cargar() {
  try {
    const r = await fetch(`${URL_DATOS}?t=${Math.floor(Date.now() / 60000)}`, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    estado = await r.json();
    try { localStorage.setItem("carretera:ultimo", JSON.stringify(estado)); } catch (e) { /* sin almacenamiento */ }
  } catch (e) {
    if (!estado) {
      try { estado = JSON.parse(localStorage.getItem("carretera:ultimo") || "null"); } catch (e2) { estado = null; }
    }
    if (!estado) {
      vista.innerHTML = '<p class="vacio">No se han podido cargar los datos. Comprueba la conexión y vuelve a intentarlo.</p>';
      return;
    }
  }
  pintar();
}

// ---------- vistas ----------
function cabecera(titulo, extra = "") {
  const viejo = !estado.actualizado || Date.now() - new Date(estado.actualizado) > 40 * 60000;
  const fallos = Object.entries(estado.fuentes || {}).filter(([k, f]) => !f.ok && !(k === "avisos" && /AEMET_API_KEY/.test(f.error || "")));
  const chip = viejo ? '<span class="chip-estado mal">Datos antiguos</span>'
    : fallos.length ? `<span class="chip-estado mal">Sin datos de ${fallos.map(([k]) => k === "camaras" ? "cámaras" : k).join(", ")}</span>` : "";
  return `<header class="cabecera">
    <div class="fila"><span class="marca">mobilityastur · Carretera</span>${chip}</div>
    ${extra}
    <h1>${esc(titulo)}</h1>
    <span class="hora">Actualizado ${hace(estado.actualizado)} · DGT y AEMET</span>
  </header>`;
}

function bloqueAvisos(avisos, max = 2, conDetalle = false) {
  return avisos.slice(0, max).map((a) => `
    <section class="aviso ${esc(a.nivel)} ${a.ahora ? "" : "previsto"}">
      ${ICO.triangulo}
      <div><strong>${a.ahora ? "" : "Previsto: "}Aviso ${esc(a.nivel)} por ${esc((a.fenomeno || a.titulo || "").toLowerCase())}</strong>
      <span>${esc(avisoTexto(a))}${conDetalle && a.texto ? " " + esc(a.texto) : ""}</span></div>
    </section>`).join("");
}

function tarjetaZona(z) {
  return `<a class="zona n${z.nivel}" href="#/zona/${esc(z.id)}">
    <span class="barra"></span>
    <div class="cuerpo">
      <div class="arriba"><strong>${esc(z.nombre)}${tieneNieve(z) ? `<span class="copo" title="Aviso de nevadas">${ICO.copo}</span>` : ""}</strong>
      <span class="etq">${esc(etiquetaNivel(z))}</span></div>
      <span class="sub">${esc(z.carreteras[0])} · ${esc(z.resumen)}</span>
    </div>${ICO.flecha}</a>`;
}

function vistaZonas() {
  const zs = estado.zonas;
  const puertos = zs.filter((z) => z.tipo === "puerto");
  const autovias = zs.filter((z) => z.tipo === "autovia");
  const avisosAhora = (estado.avisos || []);
  const filtroBtn = (id, txt) => `<button type="button" data-filtro="${id}" aria-pressed="${filtro === id}">${txt}</button>`;
  let html = cabecera("Asturias") + bloqueAvisos(avisosAhora) +
    `<nav class="filtros" aria-label="Filtrar zonas">${filtroBtn("todas", "Todas")}${filtroBtn("puertos", "Puertos")}${filtroBtn("autovias", "Autovías")}</nav>`;
  if (filtro !== "autovias") {
    const orden = [...puertos].sort((a, b) => b.nivel - a.nivel);
    html += `<section class="seccion"><h2>Puertos</h2>${orden.map(tarjetaZona).join("")}</section>`;
  }
  if (filtro !== "puertos") {
    html += `<section class="seccion"><h2>Autovías</h2><div class="rejilla">${autovias.map((z) => `
      <a class="autovia n${z.nivel}" href="#/zona/${esc(z.id)}"><strong>${esc(z.nombre)}</strong>
      <span class="etq">${esc(z.nivel ? z.resumen : etiquetaNivel(z))}</span></a>`).join("")}</div></section>`;
  }
  html += pie();
  vista.innerHTML = html;
  vista.querySelectorAll("[data-filtro]").forEach((b) => b.addEventListener("click", () => { filtro = b.dataset.filtro; pintar(); }));
}

function camaras(lista) {
  if (!lista.length) return '<p class="vacio" style="padding:12px 0;text-align:left">La DGT no tiene cámaras en este tramo.</p>';
  const t = Math.floor(Date.now() / 120000);
  return `<div class="cams">${lista.map((c) => {
    const nom = `${c.via} km ${c.km ?? "?"}${c.destino ? " · hacia " + c.destino.charAt(0) + c.destino.slice(1).toLowerCase() : ""}`;
    return `<button type="button" class="cam" data-src="${esc(c.url)}" data-nom="${esc(nom)}">
      <span class="marco"><img loading="lazy" src="${esc(c.url)}?t=${t}" alt="Cámara ${esc(nom)}" onerror="this.parentNode.classList.add('error');this.remove()"></span>
      <span>${esc(nom)}</span></button>`;
  }).join("")}</div>`;
}

function itemInc(i) {
  return `<article class="inc"><span class="ico n${i.nivel}"></span><div>
    <strong>${esc(i.titulo)}</strong>
    ${i.detalle ? `<span class="det">${esc(i.via)} · ${esc(i.detalle)}</span>` : `<span class="det">${esc(i.via)}</span>`}
    ${i.comentario ? `<span class="com">${esc(i.comentario)}</span>` : ""}
    <span class="cuando">${esc(cuando(i))}</span></div></article>`;
}

function vistaZona(id) {
  const z = estado.zonas.find((x) => x.id === id);
  if (!z) { location.hash = "#/"; return; }
  const textoEstado = z.nivel === 0
    ? (z.incidencias.length ? "Circulación normal. Solo hay incidencias menores." : "Circulación normal. La DGT no informa de incidencias.")
    : z.resumen + ".";
  let html = cabecera(z.titulo, `<a class="atras" href="#/">${ICO.atras}Zonas</a>`).replace("<h1>", '<h1 class="medio">');
  html = html.replace('<span class="hora">', `<span class="hora">${esc(z.carreteras.join(" · "))} · ${esc(z.tramo || "")}<br>`);
  html += `<section class="estado-grande n${z.nivel}"><span class="rotulo">Estado ahora</span>
    <strong>${esc(z.estado)}</strong><span>${esc(textoEstado)}</span></section>`;
  if (z.avisos.length) html += `<div style="height:12px"></div>` + bloqueAvisos(z.avisos.map((a) => ({ ...a, zonas: [] })), 3, true);
  html += `<section class="seccion"><div class="cab"><h2>Cámaras</h2><small>DGT</small></div>${camaras(z.camaras)}</section>`;
  html += `<section class="seccion"><h2>Incidencias DGT</h2><div class="lista">${z.incidencias.length
    ? z.incidencias.map(itemInc).join("") : '<p class="nada">Sin incidencias en este tramo.</p>'}</div></section>`;
  if (z.programadas.length) {
    html += `<section class="seccion"><h2>Programadas</h2><div class="lista">${z.programadas.map((i) => itemInc({ ...i, fin: null })).join("")}</div></section>`;
  }
  // alternativa: puerto Pajares ↔ Huerna
  const alt = { pajares: "huerna", huerna: "pajares" }[z.id];
  const za = alt && estado.zonas.find((x) => x.id === alt);
  if (za && z.nivel > 0 && za.nivel < z.nivel) {
    html += `<a class="alternativa" href="#/zona/${esc(za.id)}"><span class="barra n${za.nivel}"></span>
      <div><span class="rot">Alternativa</span><strong>${esc(za.nombre)} (${esc(za.carreteras[0])}): ${esc(za.estado.toLowerCase())}</strong></div>
      <span class="ver">Ver</span></a>`;
  }
  html += pie();
  vista.innerHTML = html;
}

function vistaCamaras() {
  let html = cabecera("Cámaras");
  for (const z of estado.zonas) {
    if (!z.camaras.length) continue;
    html += `<section class="seccion"><div class="cab"><h2>${esc(z.nombre)}</h2>
      <small class="etq n${z.nivel}">${esc(z.estado)}</small></div>${camaras(z.camaras)}</section>`;
  }
  html += pie();
  vista.innerHTML = html;
}

function vistaAvisos() {
  let html = cabecera("Avisos");
  const av = estado.avisos || [];
  const sinClave = /AEMET_API_KEY/.test(estado.fuentes?.avisos?.error || "");
  html += `<section class="seccion" style="padding-left:0;padding-right:0"><h2 style="padding:0 20px">AEMET</h2>${av.length
    ? bloqueAvisos(av, 20, true)
    : `<p class="nada" style="margin:0 20px">${sinClave ? "Avisos de AEMET pendientes de configurar." : "AEMET no tiene avisos en vigor ni previstos para estas zonas."}</p>`}</section>`;
  const prog = estado.zonas.flatMap((z) => z.programadas.map((i) => ({ ...i, zona: z.nombre })));
  html += `<section class="seccion"><h2>Cortes y obras programados</h2><div class="lista">${prog.length
    ? prog.map((i) => itemInc({ ...i, via: `${i.zona} · ${i.via}`, fin: null })).join("")
    : '<p class="nada">No hay cortes programados para los próximos 7 días.</p>'}</div></section>`;
  html += pie();
  vista.innerHTML = html;
}

function vistaMapa() {
  vista.innerHTML = cabecera("Mapa") + `<div id="mapa" role="region" aria-label="Mapa de zonas"></div>
    <div class="leyenda"><span><i style="background:var(--verde)"></i>Normal</span><span><i style="background:var(--ambar)"></i>Precaución</span><span><i style="background:var(--rojo)"></i>Cortes o cadenas</span></div>` + pie();
  if (!window.L) { document.getElementById("mapa").innerHTML = '<p class="vacio">No se ha podido cargar el mapa.</p>'; return; }
  if (mapa) { mapa.remove(); mapa = null; }
  mapa = L.map("mapa", { zoomControl: true, attributionControl: true }).setView([43.25, -5.85], 8);
  // Fondo oscuro de Esri (sin clave) con nombres encima; si falla, OpenStreetMap
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/";
  const fondo = L.tileLayer(`${ESRI}World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, {
    maxZoom: 16, attribution: 'Mapa © <a href="https://www.esri.com/">Esri</a>, HERE, Garmin, © OpenStreetMap',
  }).addTo(mapa);
  const nombres = L.tileLayer(`${ESRI}World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 16 }).addTo(mapa);
  let fallos = 0;
  fondo.on("tileerror", () => {
    if (++fallos !== 4) return;
    mapa.removeLayer(fondo); mapa.removeLayer(nombres);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 16, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(mapa);
  });
  const caja = L.latLngBounds(estado.zonas.flatMap((z) => [[z.bbox[0], z.bbox[1]], [z.bbox[2], z.bbox[3]]]));
  mapa.fitBounds(caja, { padding: [8, 8] });
  const color = (n) => ["#3FBF7F", "#F2B33D", "#F0605A"][n] || "#3FBF7F";
  for (const z of estado.zonas) {
    const [la, lo] = z.centro;
    L.circleMarker([la, lo], { radius: z.tipo === "puerto" ? 11 : 9, color: "#14171B", weight: 3, fillColor: color(z.nivel), fillOpacity: 1 })
      .addTo(mapa).bindPopup(`<strong>${esc(z.nombre)}</strong><br>${esc(z.estado)}<br><a href="#/zona/${esc(z.id)}">Ver detalle</a>`);
    for (const i of z.incidencias) {
      if (i.lat == null || i.nivel === 0) continue;
      L.circleMarker([i.lat, i.lon], { radius: 5, color: color(i.nivel), weight: 2, fillColor: "#14171B", fillOpacity: 1 })
        .addTo(mapa).bindPopup(`<strong>${esc(i.titulo)}</strong><br>${esc(i.via)} · ${esc(i.detalle)}`);
    }
  }
}

function pie() {
  return `<p class="fuentes">Fuentes: <a href="https://nap.dgt.es/" target="_blank" rel="noopener">DGT</a> (incidencias y cámaras, CC BY) ·
    <a href="https://www.aemet.es/" target="_blank" rel="noopener">AEMET</a> (avisos). Información orientativa: ante la duda, consulta la DGT.</p>`;
}

// ---------- navegación ----------
function pintar() {
  if (!estado) return;
  const h = location.hash.replace(/^#\/?/, "");
  const [seccion, arg] = h.split("/");
  const tab = { "": "zonas", zona: "zonas", mapa: "mapa", camaras: "camaras", avisos: "avisos" }[seccion] || "zonas";
  document.querySelectorAll(".pestanas a").forEach((a) => {
    if (a.dataset.tab === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (seccion !== "mapa" && mapa) { mapa.remove(); mapa = null; }
  if (seccion === "zona") vistaZona(arg);
  else if (seccion === "mapa") vistaMapa();
  else if (seccion === "camaras") vistaCamaras();
  else if (seccion === "avisos") vistaAvisos();
  else vistaZonas();
}

vista.addEventListener("click", (e) => {
  const b = e.target.closest(".cam");
  if (!b) return;
  visor.querySelector("img").src = `${b.dataset.src}?t=${Date.now()}`;
  visor.querySelector("img").alt = `Cámara ${b.dataset.nom}`;
  visor.querySelector(".pie").textContent = b.dataset.nom;
  visor.showModal();
});
visor.addEventListener("click", (e) => { if (e.target === visor) visor.close(); });
addEventListener("hashchange", () => { pintar(); scrollTo(0, 0); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) cargar(); });
setInterval(() => { if (!document.hidden && !location.hash.startsWith("#/mapa")) cargar(); }, REFRESCO_MS);
cargar();

// ---------- instalación ----------
if ("serviceWorker" in navigator) {
  addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}

(function avisoInstalar() {
  const caja = document.getElementById("instalar");
  const CLAVE = "carretera:instalar-cerrado";
  const leer = () => { try { return localStorage.getItem(CLAVE); } catch (e) { return null; } };
  const guardar = () => { try { localStorage.setItem(CLAVE, "1"); } catch (e) { /* modo privado */ } };
  const instalada = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  if (instalada || leer()) return;

  const ua = navigator.userAgent;
  const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const interno = /FBAN|FBAV|Instagram|Line\/|; wv\)|WhatsApp/i.test(ua);
  let peticion = null;

  const mostrar = (modo) => {
    caja.classList.remove("modo-android", "modo-ios", "modo-interno");
    caja.classList.add(`modo-${modo}`);
    caja.hidden = false;
  };
  const ocultar = (recordar) => { caja.hidden = true; if (recordar) guardar(); };

  caja.querySelector(".cerrar-instalar").addEventListener("click", () => ocultar(true));
  caja.querySelector(".si").addEventListener("click", async () => {
    if (!peticion) return;
    peticion.prompt();
    const { outcome } = await peticion.userChoice;
    peticion = null;
    ocultar(outcome === "accepted");
  });

  // Android y escritorio con Chrome/Edge: botón de instalar de verdad
  addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    peticion = e;
    if (!leer()) mostrar("android");
  });
  addEventListener("appinstalled", () => ocultar(true));

  // iPhone: instrucciones; navegadores internos de otras apps: abrir fuera
  setTimeout(() => {
    if (!caja.hidden || leer()) return;
    if (interno) mostrar("interno");
    else if (ios) mostrar("ios");
  }, 1500);
})();
