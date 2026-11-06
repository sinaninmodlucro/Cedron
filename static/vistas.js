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
