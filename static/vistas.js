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

// Pestanas por grupo (Energia, Ganaderia, Agricultura...): muestra un grupo cada vez.
// Sin JavaScript se ven todos. Manda la direccion (#ganaderia), luego la ultima elegida.
(function () {
  var enlaces = document.querySelectorAll(".vistas--grupos a[data-grupo]");
  if (!enlaces.length) return;
  var CLAVE = "cedron-grupo";
  var secciones = document.querySelectorAll("section[data-grupo]");

  function existe(g) { return g && document.querySelector('.vistas--grupos a[data-grupo="' + g + '"]'); }
  function aplicar(grupo) {
    enlaces.forEach(function (a) {
      if (a.dataset.grupo === grupo) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
    });
    secciones.forEach(function (s) { s.hidden = grupo !== "todas" && s.dataset.grupo !== grupo; });
  }
  function elegir(grupo, recordar) {
    aplicar(grupo);
    if (recordar) { try { localStorage.setItem(CLAVE, grupo); } catch (e) {} }
  }
  enlaces.forEach(function (a) {
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      elegir(a.dataset.grupo, true);
      try { history.replaceState(null, "", "#" + a.dataset.grupo); } catch (e) {}
    });
  });
  window.addEventListener("hashchange", function () {
    var g = location.hash.slice(1);
    if (existe(g)) elegir(g, true);
  });
  var inicial = location.hash.slice(1);
  if (!existe(inicial)) {
    inicial = null;
    try { inicial = localStorage.getItem(CLAVE); } catch (e) {}
  }
  aplicar(existe(inicial) ? inicial : enlaces[0].dataset.grupo);
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
