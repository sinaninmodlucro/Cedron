// Cruceta y globo informativo del grafico de precio (raton, tactil y teclado).
document.querySelectorAll(".grafico svg[data-puntos]").forEach(function (svg) {
  var puntos = JSON.parse(svg.dataset.puntos);
  var marco = svg.parentElement;
  var globo = marco.querySelector(".globo");
  var cruz = svg.querySelector(".cruz");
  var punto = svg.querySelector(".punto");
  var captura = svg.querySelector(".captura");
  var actual = puntos.length - 1;

  function mostrar(i) {
    actual = Math.max(0, Math.min(puntos.length - 1, i));
    var p = puntos[actual];
    cruz.setAttribute("x1", p.x); cruz.setAttribute("x2", p.x);
    punto.setAttribute("cx", p.x); punto.setAttribute("cy", p.y);
    cruz.hidden = punto.hidden = globo.hidden = false;
    var escala = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
    globo.style.left = (p.x * escala) + "px";
    globo.style.top = (p.y * escala) + "px";
    globo.innerHTML = "<strong>" + p.mes + "</strong><br>Precio: " + p.precio + " $<br>Media: " + p.media + " $";
  }
  function ocultar() { cruz.hidden = punto.hidden = globo.hidden = true; }
  function indice(evento) {
    var r = svg.getBoundingClientRect();
    var x = (evento.clientX - r.left) * svg.viewBox.baseVal.width / r.width;
    var mejor = 0;
    puntos.forEach(function (p, i) { if (Math.abs(p.x - x) < Math.abs(puntos[mejor].x - x)) mejor = i; });
    return mejor;
  }
  captura.addEventListener("pointermove", function (e) { mostrar(indice(e)); });
  captura.addEventListener("pointerdown", function (e) { mostrar(indice(e)); });
  captura.addEventListener("pointerleave", ocultar);

  svg.setAttribute("tabindex", "0");
  svg.addEventListener("focus", function () { mostrar(actual); });
  svg.addEventListener("blur", ocultar);
  svg.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") { mostrar(actual - 1); e.preventDefault(); }
    if (e.key === "ArrowRight") { mostrar(actual + 1); e.preventDefault(); }
  });
});
