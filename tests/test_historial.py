"""Proteccion de los historiales de previsiones (11-nov-2026).

Son lo unico de Cedron que no se puede reconstruir: si un cambio borra o reescribe una
prevision ya apuntada, estas pruebas fallan y la automatizacion se detiene (y GitHub avisa
por correo). Comparan los archivos actuales con las versiones anteriores guardadas en git.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cedron import store
from cedron.store import HISTORIALES, HistorialError, problemas_historial

RAIZ = Path(__file__).resolve().parent.parent


def _git(*args) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


class Reglas(unittest.TestCase):
    BASE = {"id": "oro", "plazo": 3, "desde": "2026-10", "vence": "2027-01", "previsto": 1.0,
            "base": 100.0, "habitual": 0.5, "apuntada": "2026-11-10", "real": None}

    def test_sin_cambios(self):
        self.assertEqual(problemas_historial([self.BASE], [dict(self.BASE)], "2026-11-11"), [])

    def test_anadir_y_rellenar_real(self):
        nuevo = [{**self.BASE, "real": 2.0}, {**self.BASE, "plazo": 12, "vence": "2027-10"}]
        self.assertEqual(problemas_historial([self.BASE], nuevo, "2026-11-11"), [])

    def test_borrar(self):
        self.assertTrue(problemas_historial([self.BASE], [], "2026-11-11"))

    def test_reescribir_despues(self):
        self.assertTrue(problemas_historial([self.BASE], [{**self.BASE, "previsto": 9.0}], "2026-11-11"))

    def test_corregir_el_mismo_dia(self):
        self.assertEqual(problemas_historial([self.BASE], [{**self.BASE, "previsto": 9.0}], "2026-11-10"), [])

    def test_real_no_cambia(self):
        viejo = {**self.BASE, "real": 2.0}
        self.assertTrue(problemas_historial([viejo], [{**viejo, "real": 3.0}], "2026-11-10"))

    def test_escribir_se_niega(self):
        from cedron import store                  # otra prueba recarga el modulo: se toma el actual
        with tempfile.TemporaryDirectory() as t:
            antes = store.DATA
            store.DATA = Path(t)
            try:
                store.escribir("metales_previsiones.json", [self.BASE])
                with self.assertRaises(store.HistorialError):
                    store.escribir("metales_previsiones.json", [])
                self.assertEqual(json.loads((Path(t) / "metales_previsiones.json").read_text("utf-8"))[0]["id"], "oro")
            finally:
                store.DATA = antes


class HistorialesGuardados(unittest.TestCase):
    """Los archivos de data/ frente a las versiones anteriores de git."""

    def test_no_se_pierde_nada(self):
        if os.environ.get("CEDRON_DATA"):
            self.skipTest("datos de ejemplo")
        refs = os.environ.get("CEDRON_REFERENCIAS", "HEAD HEAD~1 origin/main").split()
        comprobadas = 0
        for nombre in HISTORIALES:
            ruta = RAIZ / "data" / nombre
            actual = json.loads(ruta.read_text("utf-8")) if ruta.exists() else []
            for ref in refs:
                texto = _git("show", f"{ref}:data/{nombre}")
                if texto is None:
                    continue                      # la referencia no existe aqui (p. ej. sin historia)
                comprobadas += 1
                fallos = problemas_historial(json.loads(texto), actual)
                self.assertEqual(fallos, [], f"{nombre} frente a {ref}: {fallos[:10]}")
        if comprobadas == 0 and _git("rev-parse", "HEAD") is not None:
            self.fail("no se pudo leer ninguna versión anterior de los historiales")


if __name__ == "__main__":
    unittest.main()
