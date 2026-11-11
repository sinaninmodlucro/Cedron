// «Tu cesta»: cuanto ha subido la cesta de cada uno segun lo que gasta en cada cosa.
// Todo se calcula aqui, en el navegador; lo escrito solo se guarda en este navegador.
(function () {
  var raiz = document.getElementById("mi-cesta");
  var nodo = document.getElementById("datos-cesta");
  if (!raiz || !nodo) return;
  var D = JSON.parse(nodo.textContent || "null");
  if (!D || !D.items || !D.meses) return;
  var CLAVE = "cedron-mi-cesta";
  var MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
               "septiembre", "octubre", "noviembre", "diciembre"];
  function q(n) { return raiz.querySelector('[data-mc="' + n + '"]'); }

  var estado = { gastos: {}, anios: 1, total: 600 };
  try {
    var g = JSON.parse(localStorage.getItem(CLAVE) || "null");
    if (g && typeof g === "object") estado = Object.assign(estado, g);
  } catch (e) {}
  function guardar() { try { localStorage.setItem(CLAVE, JSON.stringify(estado)); } catch (e) {} }

  var fmt = {};
  function numero(v, d) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    if (!fmt[d]) fmt[d] = new Intl.NumberFormat("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });
    return fmt[d].format(v).replace("-", "−");
  }
  function pct(v) { return (v > 0 ? "+" : "") + numero(v * 100, 1) + " %"; }
  function mes(m) { return MESES[parseInt(m.slice(5, 7), 10) - 1] + " de " + m.slice(0, 4); }

  // Filas: cada producto de la cesta y «otros gastos» (IPC general)
  var filas = D.items.map(function (i) { return { id: i.id, nombre: i.nombre, serie: i.serie }; });
  if (D.general && D.general.some(function (v) { return v !== null; })) {
    filas.push({ id: "otros", nombre: "Otros gastos (resto del IPC)", serie: D.general });
  }
  var cuerpo = q("filas");
  filas.forEach(function (f) {
    var tr = document.createElement("tr");
    var th = document.createElement("td");
    th.textContent = f.nombre;
    var td = document.createElement("td");
    td.className = "num";
    var inp = document.createElement("input");
    inp.type = "number"; inp.min = "0"; inp.step = "1"; inp.inputMode = "decimal";
    inp.setAttribute("aria-label", "Euros al mes en " + f.nombre);
    inp.value = estado.gastos[f.id] || "";
    inp.addEventListener("input", function () {
      var v = parseFloat(inp.value.replace(",", "."));
      if (v > 0) estado.gastos[f.id] = v; else delete estado.gastos[f.id];
      guardar(); calcular();
    });
    td.appendChild(inp);
    var tc = document.createElement("td");
    tc.className = "num cifra";
    f.celda = tc; f.input = inp;
    tr.appendChild(th); tr.appendChild(td); tr.appendChild(tc);
    cuerpo.appendChild(tr);
  });

  q("total").value = estado.total || 600;
  q("anios").value = String(estado.anios || 1);
  q("anios").addEventListener("change", function () { estado.anios = parseInt(q("anios").value, 10); guardar(); calcular(); });
  q("total").addEventListener("input", function () { estado.total = parseFloat(q("total").value) || 0; guardar(); });
  q("medio").addEventListener("click", function () {
    var total = parseFloat(q("total").value) || 0;
    var suma = D.items.reduce(function (s, i) { return s + i.peso; }, 0);
    estado.gastos = {};
    D.items.forEach(function (i) { estado.gastos[i.id] = Math.round(total * i.peso / suma); });
    filas.forEach(function (f) { f.input.value = estado.gastos[f.id] || ""; });
    guardar(); calcular();
  });
  q("borrar").addEventListener("click", function () {
    estado.gastos = {};
    filas.forEach(function (f) { f.input.value = ""; });
    guardar(); calcular();
  });

  function calcular() {
    var n = D.meses.length - 1;
    var k = n - 12 * (estado.anios || 1);
    var res = q("resultado");
    if (k < 0) { res.textContent = "No hay tantos años de datos."; return; }
    var hoy = 0, antes = 0, alguno = false;
    filas.forEach(function (f) {
      var a = f.serie[k], b = f.serie[n];
      var cambio = a && b ? b / a - 1 : null;
      f.celda.textContent = cambio === null ? "—" : pct(cambio);
      f.celda.className = "num cifra " + (cambio > 0 ? "sube" : cambio < 0 ? "baja" : "");
      var g = estado.gastos[f.id];
      if (g > 0 && cambio !== null) {
        alguno = true;
        hoy += g;
        antes += g * a / b;           // lo mismo, a los precios de entonces
      }
    });
    if (!alguno) {
      res.innerHTML = "";
      var p = document.createElement("p");
      p.className = "vacio";
      p.textContent = "Escribe algún gasto (o rellena con el reparto medio) para ver tu cesta.";
      res.appendChild(p);
      return;
    }
    var cambio = hoy / antes - 1, euros = hoy - antes;
    res.innerHTML = "";
    var p1 = document.createElement("p");
    p1.className = "mi-cesta__cifra";
    var c = document.createElement("span");
    c.className = "cifra " + (cambio > 0 ? "sube" : cambio < 0 ? "baja" : "");
    c.textContent = pct(cambio);
    p1.appendChild(document.createTextNode("Tu cesta, desde " + mes(D.meses[k]) + ": "));
    p1.appendChild(c);
    var p2 = document.createElement("p");
    p2.textContent = (euros >= 0 ? "Lo que hoy te cuesta " + numero(hoy, 0) + " € al mes te costaba " + numero(antes, 0) +
      " € entonces: " + numero(euros, 0) + " € más al mes (" + numero(euros * 12, 0) + " € al año)."
      : "Lo que hoy te cuesta " + numero(hoy, 0) + " € al mes te costaba " + numero(antes, 0) + " € entonces: " +
        numero(-euros, 0) + " € menos al mes.") + " Último dato: " + mes(D.meses[n]) + ".";
    res.appendChild(p1); res.appendChild(p2);
  }
  calcular();
})();
