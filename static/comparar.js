// Comparador: evolucion de varias materias (o grupos enteros) a la vez, en base 100.
// Sirve para cualquier bloque .comparar de la pagina (materias de apoyo en «Comparar»,
// metales en «Mercado»). Cada bloque lleva sus datos en un <script data-cmp="datos">,
// su clave de memoria en data-clave y su eleccion inicial en data-inicial.
document.querySelectorAll(".comparar[data-clave]").forEach(function (raiz) {
  function q(nombre) { return raiz.querySelector('[data-cmp="' + nombre + '"]'); }
  var nodo = q("datos");
  if (!nodo) return;
  var DATOS = JSON.parse(nodo.textContent);
  var MAX = 8;                                    // colores de la paleta: nunca se repiten
  var MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  var NOMBRE_AMB = { espana: "España", europa: "Europa", global: "Global" };
  var CLAVE = raiz.dataset.clave;
  var svg = q("svg");
  var globo = q("globo");
  var NS = "http://www.w3.org/2000/svg";
  var ANCHO = 720, ALTO = 340, IZQ = 48, DER = 128, ARR = 16, ABA = 32;

  var estado = { vista: "espana", anios: 3, elegidos: [], colores: {}, total: false };
  try {
    var g = JSON.parse(localStorage.getItem(CLAVE) || "null");
    if (g && Array.isArray(g.elegidos)) estado = Object.assign(estado, g);
  } catch (e) {}
  if (!estado.elegidos.length) {                   // ejemplo inicial: dos grupos juntos
    JSON.parse(raiz.dataset.inicial || "[]").forEach(function (k) { if (existe(k)) elegir(k, true); });
  }
  estado.elegidos = estado.elegidos.filter(existe);

  function guardar() { try { localStorage.setItem(CLAVE, JSON.stringify(estado)); } catch (e) {} }
  function existe(k) {
    var p = k.split(":");
    return p[0] === "m" ? !!DATOS.materias[p[1]] : p[0] === "g" ? !!pestana(p[1]) : p[0] === "t";
  }
  function pestana(id) { return DATOS.pestanas.filter(function (p) { return p.id === id; })[0]; }
  function lineas() { return estado.elegidos.length + (estado.total ? 1 : 0); }
  function slotLibre() {
    var usados = Object.keys(estado.colores).map(function (k) { return estado.colores[k]; });
    for (var i = 1; i <= MAX; i++) if (usados.indexOf(i) < 0) return i;
    return null;
  }
  // El color sigue a la linea: se le da al elegirla y no cambia al quitar otras
  function elegir(k, si) {
    var i = estado.elegidos.indexOf(k);
    if (si && i < 0) {
      if (lineas() >= MAX) return false;
      estado.elegidos.push(k);
      estado.colores[k] = slotLibre();
    } else if (!si && i >= 0) {
      estado.elegidos.splice(i, 1);
      delete estado.colores[k];
    }
    return true;
  }

  // ---------------------------------------------------------------- numeros
  var fmt = {};
  function numero(v, d) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    if (!fmt[d]) fmt[d] = new Intl.NumberFormat("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });
    return fmt[d].format(v).replace("-", "−");
  }
  function mesLargo(m) { return MESES[+m.slice(5, 7) - 1] + " " + m.slice(0, 4); }
  function sumarMeses(m, n) {
    var a = +m.slice(0, 4), mm = +m.slice(5, 7) - 1 + n;
    a += Math.floor(mm / 12); mm = ((mm % 12) + 12) % 12;
    return a + "-" + (mm < 9 ? "0" : "") + (mm + 1);
  }

  // ---------------------------------------------------------------- series
  function serieMateria(id) {
    var m = DATOS.materias[id];
    var amb = m.vistas[estado.vista] || Object.keys(m.ambitos)[0];
    var d = m.ambitos[amb];
    var mapa = {};
    d.serie.forEach(function (p) { mapa[p[0]] = p[1]; });
    return { mapa: mapa, unidad: d.unidad, decimales: d.decimales, ambito: amb, nombre: m.nombre,
             fin: d.serie[d.serie.length - 1][0] };
  }
  function enBase(s, meses) {
    var base = null, desde = null, out = {};
    meses.forEach(function (m) {
      var v = s.mapa[m];
      if (v === undefined) return;
      if (base === null) { base = v; desde = m; }
      if (base) out[m] = v / base * 100;
    });
    return { valores: out, desde: desde };
  }
  function media(listas, meses) {
    var out = {};
    meses.forEach(function (m) {
      var vs = listas.map(function (l) { return l[m]; }).filter(function (v) { return v !== undefined; });
      if (vs.length) out[m] = vs.reduce(function (a, b) { return a + b; }, 0) / vs.length;
    });
    return out;
  }

  function calcular() {
    // Fin del periodo: el ultimo mes con datos entre todo lo elegido
    var ids = [];
    estado.elegidos.forEach(function (k) {
      var p = k.split(":");
      (p[0] === "m" ? [p[1]] : pestana(p[1]).materias).forEach(function (id) { if (ids.indexOf(id) < 0) ids.push(id); });
    });
    if (!ids.length) return { meses: [], series: [] };
    var fin = ids.map(function (id) { return serieMateria(id).fin; }).sort().pop();
    var inicio = sumarMeses(fin, -12 * estado.anios);
    var meses = [];
    for (var m = inicio; m <= fin; m = sumarMeses(m, 1)) meses.push(m);

    var cache = {};
    function materia(id) {
      if (!cache[id]) { var s = serieMateria(id); cache[id] = Object.assign(s, enBase(s, meses)); }
      return cache[id];
    }
    var series = estado.elegidos.map(function (k) {
      var p = k.split(":");
      if (p[0] === "m") {
        var s = materia(p[1]);
        // el ambito solo se indica si se puede elegir (en «Mercado» todo es global)
        var partes = [];
        if (raiz.querySelector("[data-cmp-vista]")) partes.push(NOMBRE_AMB[s.ambito]);
        if (s.desde && s.desde !== meses[0]) partes.push("desde " + mesLargo(s.desde));
        return { clave: k, nombre: s.nombre, detalle: partes.join(", "),
                 valores: s.valores, real: s };
      }
      var pe = pestana(p[1]);
      var miembros = pe.materias.map(materia).filter(function (s) { return s.desde; });
      return { clave: k, nombre: pe.nombre + " (en conjunto)", corto: pe.nombre, detalle: "media de " + miembros.length + " materias",
               valores: media(miembros.map(function (s) { return s.valores; }), meses) };
    });
    if (estado.total && ids.length) {
      var todas = ids.map(materia).filter(function (s) { return s.desde; });
      series.push({ clave: "t:total", nombre: "Media de todo lo elegido", corto: "Media", detalle: "media de " + todas.length + " materias",
                    valores: media(todas.map(function (s) { return s.valores; }), meses) });
    }
    return { meses: meses, series: series };
  }

  // ---------------------------------------------------------------- lista de eleccion
  function pintarLista() {
    var cont = q("lista");
    cont.innerHTML = "";
    DATOS.pestanas.forEach(function (p, i) {
      var det = document.createElement("details");
      det.open = i === 0 || p.materias.some(function (id) { return estado.elegidos.indexOf("m:" + id) >= 0; }) ||
                 estado.elegidos.indexOf("g:" + p.id) >= 0;
      var sum = document.createElement("summary");
      sum.textContent = p.nombre;
      det.appendChild(sum);
      if (p.materias.length > 1) det.appendChild(casilla("g:" + p.id, "Todo el grupo, en conjunto", true));
      p.materias.forEach(function (id) { det.appendChild(casilla("m:" + id, DATOS.materias[id].nombre, false)); });
      cont.appendChild(det);
    });
    q("total").checked = estado.total;
  }
  function casilla(k, texto, grupo) {
    var l = document.createElement("label");
    l.className = "cmp-casilla" + (grupo ? " cmp-casilla--grupo" : "");
    var c = document.createElement("input");
    c.type = "checkbox"; c.dataset.clave = k; c.checked = estado.elegidos.indexOf(k) >= 0;
    var marca = document.createElement("span");
    marca.className = "cmp-color";
    if (estado.colores[k]) marca.style.background = "var(--serie-" + estado.colores[k] + ")";
    l.appendChild(c); l.appendChild(marca); l.appendChild(document.createTextNode(texto));
    return l;
  }
  q("lista").addEventListener("change", function (e) {
    var c = e.target;
    if (!c.dataset || !c.dataset.clave) return;
    if (!elegir(c.dataset.clave, c.checked)) {
      c.checked = false;
      aviso("Como mucho " + MAX + " líneas a la vez, para que se distingan. Quita alguna para añadir otra.");
      return;
    }
    actualizar();
  });
  q("total").addEventListener("change", function (e) {
    if (e.target.checked && lineas() >= MAX) {
      e.target.checked = false;
      aviso("Como mucho " + MAX + " líneas a la vez. Quita alguna para añadir la media.");
      return;
    }
    estado.total = e.target.checked;
    if (estado.total) estado.colores["t:total"] = slotLibre(); else delete estado.colores["t:total"];
    actualizar();
  });
  q("limpiar").addEventListener("click", function () {
    estado.elegidos = []; estado.colores = {}; estado.total = false;
    actualizar();
  });
  raiz.querySelectorAll("[data-cmp-vista]").forEach(function (b) {
    b.addEventListener("click", function () { estado.vista = b.dataset.cmpVista; actualizar(); });
  });
  raiz.querySelectorAll("[data-cmp-anios]").forEach(function (b) {
    b.addEventListener("click", function () { estado.anios = +b.dataset.cmpAnios; actualizar(); });
  });
  function aviso(t) { q("aviso").textContent = t || ""; }

  // ---------------------------------------------------------------- grafico
  function el(tipo, attrs, padre) {
    var e = document.createElementNS(NS, tipo);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (padre) padre.appendChild(e);
    return e;
  }
  function pintar(res) {
    while (svg.lastChild && svg.lastChild.tagName !== "desc") svg.removeChild(svg.lastChild);
    var meses = res.meses, series = res.series;
    if (!series.length) {
      var t = el("text", { x: ANCHO / 2, y: ALTO / 2, "text-anchor": "middle", "class": "cmp-vacio" }, svg);
      t.textContent = "Elige en la lista qué quieres comparar.";
      return;
    }
    var todos = [];
    series.forEach(function (s) { meses.forEach(function (m) { if (s.valores[m] !== undefined) todos.push(s.valores[m]); }); });
    todos.push(100);
    var lo = Math.min.apply(null, todos), hi = Math.max.apply(null, todos);
    var margen = (hi - lo) * 0.08 || 5; lo -= margen; hi += margen;
    var n = meses.length;
    function X(i) { return IZQ + i * (ANCHO - IZQ - DER) / Math.max(1, n - 1); }
    function Y(v) { return ARR + (hi - v) * (ALTO - ARR - ABA) / (hi - lo); }

    // Rejilla y ejes (recesivos)
    var paso = [1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500].filter(function (p) { return (hi - lo) / p <= 6; })[0] || 1000;
    var gr = el("g", { "class": "rejilla eje" }, svg);
    for (var v = Math.ceil(lo / paso) * paso; v < hi; v += paso) {
      el("line", { x1: IZQ, x2: ANCHO - DER, y1: Y(v), y2: Y(v) }, gr);
      el("text", { x: IZQ - 8, y: Y(v) + 4, "text-anchor": "end" }, gr).textContent = numero(v, 0);
    }
    el("line", { x1: IZQ, x2: ANCHO - DER, y1: Y(100), y2: Y(100), "class": "cmp-base" }, svg);
    var ex = el("g", { "class": "eje" }, svg);
    meses.forEach(function (m, i) {
      var etiqueta = estado.anios <= 1 ? (/-(01|04|07|10)$/.test(m) ? mesLargo(m) : null)
                   : (m.slice(5) === "01" && (estado.anios < 10 || +m.slice(0, 4) % 2 === 0) ? m.slice(0, 4) : null);
      if (etiqueta) el("text", { x: X(i), y: ALTO - 8, "text-anchor": "middle" }, ex).textContent = etiqueta;
    });

    // Lineas (los huecos se respetan: no se inventan meses sin dato)
    var finales = [];
    series.forEach(function (s) {
      var d = "", abierto = false, ultimo = null;
      meses.forEach(function (m, i) {
        var val = s.valores[m];
        if (val === undefined) { abierto = false; return; }
        d += (abierto ? "L" : "M") + X(i).toFixed(1) + "," + Y(val).toFixed(1);
        abierto = true; ultimo = { i: i, v: val };
      });
      el("path", { d: d, "class": "cmp-linea", style: "stroke: var(--serie-" + estado.colores[s.clave] + ")" }, svg);
      if (ultimo) finales.push({ s: s, y: Y(ultimo.v), x: X(ultimo.i), v: ultimo.v });
    });
    // Rotulos al final de cada linea (texto en tinta; el color va en el punto), sin solaparse
    finales.sort(function (a, b) { return a.y - b.y; });
    for (var i = 1; i < finales.length; i++) if (finales[i].y - finales[i - 1].y < 14) finales[i].y = finales[i - 1].y + 14;
    finales.forEach(function (f) {
      el("circle", { cx: f.x, cy: Y(f.v), r: 4, "class": "cmp-fin", style: "fill: var(--serie-" + estado.colores[f.s.clave] + ")" }, svg);
      var corto = f.s.corto || f.s.nombre;
      var nombre = corto.length > 15 ? corto.slice(0, 14) + "…" : corto;
      el("text", { x: ANCHO - DER + 8, y: f.y + 4, "class": "rotulo" }, svg).textContent = numero(f.v, 0) + " " + nombre;
    });

    // Capa de interaccion: cruceta y globo con todas las lineas de ese mes
    var cruz = el("line", { "class": "cruz", y1: ARR, y2: ALTO - ABA, x1: 0, x2: 0 }, svg);
    cruz.setAttribute("visibility", "hidden");
    var puntos = el("g", {}, svg);
    var captura = el("rect", { x: IZQ, y: 0, width: ANCHO - IZQ - DER, height: ALTO, fill: "transparent", "class": "captura" }, svg);
    function mostrar(evento) {
      var r = svg.getBoundingClientRect();
      var x = (evento.clientX - r.left) * ANCHO / r.width;
      var i = Math.max(0, Math.min(n - 1, Math.round((x - IZQ) / ((ANCHO - IZQ - DER) / Math.max(1, n - 1)))));
      var m = meses[i];
      cruz.setAttribute("x1", X(i)); cruz.setAttribute("x2", X(i)); cruz.setAttribute("visibility", "visible");
      while (puntos.lastChild) puntos.removeChild(puntos.lastChild);
      var filas = series.map(function (s) {
        var val = s.valores[m];
        if (val !== undefined) el("circle", { cx: X(i), cy: Y(val), r: 5, "class": "punto", style: "fill: var(--serie-" + estado.colores[s.clave] + ")" }, puntos);
        var real = s.real && s.real.mapa[m] !== undefined ? " · " + numero(s.real.mapa[m], s.real.decimales) + " " + s.real.unidad : "";
        return "<span class=\"cmp-color\" style=\"background: var(--serie-" + estado.colores[s.clave] + ")\"></span>" +
               escapar(s.nombre) + ": <strong>" + numero(val, 1) + "</strong>" + escapar(real);
      });
      globo.innerHTML = "<strong>" + mesLargo(m) + "</strong><br>" + filas.join("<br>");
      globo.hidden = false;
      var escala = r.width / ANCHO;
      globo.style.left = (X(i) * escala) + "px";
      globo.style.top = (ARR * escala) + "px";
      globo.classList.toggle("globo--izq", X(i) > ANCHO / 2);
    }
    function ocultar() {
      cruz.setAttribute("visibility", "hidden"); globo.hidden = true;
      while (puntos.lastChild) puntos.removeChild(puntos.lastChild);
    }
    captura.addEventListener("pointermove", mostrar);
    captura.addEventListener("pointerdown", mostrar);
    captura.addEventListener("pointerleave", ocultar);
  }
  function escapar(t) {
    return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c]; });
  }

  function pintarLeyenda(res) {
    var ul = q("leyenda");
    ul.innerHTML = "";
    res.series.forEach(function (s) {
      var li = document.createElement("li");
      li.innerHTML = "<span class=\"cmp-color\" style=\"background: var(--serie-" + estado.colores[s.clave] + ")\"></span>" +
                     "<span>" + escapar(s.nombre) + (s.detalle ? " <span class=\"secundario\">(" + escapar(s.detalle) + ")</span>" : "") + "</span>";
      var b = document.createElement("button");
      b.type = "button"; b.className = "cmp-quitar"; b.textContent = "×";
      b.setAttribute("aria-label", "Quitar " + s.nombre);
      b.addEventListener("click", function () {
        if (s.clave === "t:total") { estado.total = false; delete estado.colores["t:total"]; }
        else elegir(s.clave, false);
        actualizar();
      });
      li.appendChild(b);
      ul.appendChild(li);
    });
  }

  function pintarTabla(res) {
    var cont = q("tabla");
    if (!res.series.length) { cont.innerHTML = ""; return; }
    var h = "<table class=\"tabla\"><thead><tr><th>Mes</th>" +
            res.series.map(function (s) { return "<th class=\"num\">" + escapar(s.nombre) + "</th>"; }).join("") + "</tr></thead><tbody>";
    res.meses.slice().reverse().forEach(function (m) {
      h += "<tr><td>" + mesLargo(m) + "</td>" +
           res.series.map(function (s) { return "<td class=\"num\">" + numero(s.valores[m], 1) + "</td>"; }).join("") + "</tr>";
    });
    cont.innerHTML = h + "</tbody></table>";
  }

  function actualizar() {
    aviso("");
    raiz.querySelectorAll("[data-cmp-vista]").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.cmpVista === estado.vista ? "true" : "false"); });
    raiz.querySelectorAll("[data-cmp-anios]").forEach(function (b) { b.setAttribute("aria-pressed", +b.dataset.cmpAnios === estado.anios ? "true" : "false"); });
    var res = calcular();
    pintarLista();
    pintar(res);
    pintarLeyenda(res);
    pintarTabla(res);
    guardar();
  }
  actualizar();
});
