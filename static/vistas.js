// Selector España / Europa / Global de las materias primas de apoyo.
// Recuerda la eleccion en este navegador (si el navegador lo permite).
(function () {
  var botones = document.querySelectorAll(".vistas button[data-vista]");
  if (!botones.length) return;
  var CLAVE = "cedron-vista";

  function aplicar(vista) {
    botones.forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.vista === vista ? "true" : "false"); });
    document.querySelectorAll("tr[data-vista]").forEach(function (fila) { fila.hidden = fila.dataset.vista !== vista; });
  }
  botones.forEach(function (b) {
    b.addEventListener("click", function () {
      aplicar(b.dataset.vista);
      try { localStorage.setItem(CLAVE, b.dataset.vista); } catch (e) {}
    });
  });
  var guardada = null;
  try { guardada = localStorage.getItem(CLAVE); } catch (e) {}
  if (guardada && document.querySelector('.vistas button[data-vista="' + guardada + '"]')) aplicar(guardada);
})();

// Pestanas por grupo (Energia, Ganaderia, Agricultura...). Se pueden pulsar varias
// para ver esos grupos juntos; pulsar una ya elegida la quita (siempre queda una).
// «Todas» las muestra todas. Sin JavaScript se ven todos. Manda la direccion
// (#agricolas+fertilizantes) y, si no hay, la ultima eleccion en este navegador.
(function () {
  var enlaces = document.querySelectorAll(".vistas--grupos a[data-grupo]");
  if (!enlaces.length) return;
  var CLAVE = "cedron-grupos";
  var secciones = document.querySelectorAll("section[data-grupo]");
  var grupos = [].map.call(enlaces, function (a) { return a.dataset.grupo; })
                 .filter(function (g) { return g !== "todas"; });

  function validos(lista) { return (lista || []).filter(function (g) { return grupos.indexOf(g) >= 0; }); }
  function leerHash() {
    var h = decodeURIComponent(location.hash.slice(1));
    return h === "todas" ? grupos.slice() : validos(h.split("+"));
  }
  function aplicar(elegidos) {
    var todas = elegidos.length === grupos.length;
    enlaces.forEach(function (a) {
      var si = a.dataset.grupo === "todas" ? todas : elegidos.indexOf(a.dataset.grupo) >= 0;
      a.setAttribute("aria-pressed", si ? "true" : "false");
    });
    secciones.forEach(function (s) { s.hidden = elegidos.indexOf(s.dataset.grupo) < 0; });
  }
  var actual = [];
  function elegir(lista) {
    // se respeta el orden de las pestanas, no el de los clics
    actual = grupos.filter(function (g) { return lista.indexOf(g) >= 0; });
    aplicar(actual);
    try { localStorage.setItem(CLAVE, JSON.stringify(actual)); } catch (e) {}
    try { history.replaceState(null, "", "#" + (actual.length === grupos.length ? "todas" : actual.join("+"))); } catch (e) {}
  }
  enlaces.forEach(function (a) {
    a.setAttribute("role", "button");
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      var g = a.dataset.grupo;
      if (g === "todas") {
        elegir(actual.length === grupos.length ? [grupos[0]] : grupos.slice());
      } else if (actual.length === grupos.length) {
        elegir([g]);                                   // desde «Todas», un clic elige solo ese
      } else if (actual.indexOf(g) >= 0) {
        if (actual.length > 1) elegir(actual.filter(function (x) { return x !== g; }));
      } else {
        elegir(actual.concat([g]));
      }
    });
  });
  window.addEventListener("hashchange", function () {
    var l = leerHash();
    if (l.length) elegir(l);
  });
  var inicial = leerHash();
  if (!inicial.length) {
    try { inicial = validos(JSON.parse(localStorage.getItem(CLAVE) || "[]")); } catch (e) { inicial = []; }
  }
  actual = inicial.length ? grupos.filter(function (g) { return inicial.indexOf(g) >= 0; }) : [grupos[0]];
  aplicar(actual);
})();
// Selector de precio: origen y tienda / solo origen / solo tienda.
// Funciona con una marca en <html> que lee la hoja de estilos, asi sirve igual
// en la lista de materias y en la ficha de cada una.
(function () {
  var botones = document.querySelectorAll(".vistas button[data-precio]");
  if (!botones.length) return;
  var CLAVE = "cedron-precio";

  function aplicar(precio) {
    botones.forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.precio === precio ? "true" : "false"); });
    document.documentElement.setAttribute("data-precio", precio);
  }
  botones.forEach(function (b) {
    b.addEventListener("click", function () {
      aplicar(b.dataset.precio);
      try { localStorage.setItem(CLAVE, b.dataset.precio); } catch (e) {}
    });
  });
  var guardada = null;
  try { guardada = localStorage.getItem(CLAVE); } catch (e) {}
  if (guardada && document.querySelector('.vistas button[data-precio="' + guardada + '"]')) aplicar(guardada);
})();
