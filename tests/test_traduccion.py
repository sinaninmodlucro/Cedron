"""Traduccion de titulares (11-nov-2026). Sin el modelo real: un traductor de prueba."""
import unittest
from unittest import mock

from cedron import traduccion

CFG = {"traduccion": {"activo": True, "max_por_ejecucion": 10, "dias_memoria": 60, "modelo": {}}}


class TraductorFalso:
    llamadas = []

    def __init__(self, mcfg):
        pass

    def traducir(self, textos, segundos=None):
        TraductorFalso.llamadas.append(list(textos))
        return ["ES: " + t if "roto" not in t else "x x x x" for t in textos]


class Traduccion(unittest.TestCase):
    def setUp(self):
        self.datos = {}
        TraductorFalso.llamadas = []
        self.parches = [mock.patch.object(traduccion, "leer", lambda n, d=None: self.datos.get(n, d)),
                        mock.patch.object(traduccion, "escribir", lambda n, c: self.datos.__setitem__(n, c)),
                        mock.patch.object(traduccion, "Traductor", TraductorFalso)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()

    def test_idioma(self):
        self.assertEqual(traduccion.idioma_probable("Oil prices rise as Iran peace optimism fades"), "en")
        self.assertEqual(traduccion.idioma_probable("El petróleo baja de 90 dólares por primera vez"), "es")
        self.assertTrue(traduccion.hay_que_traducir({"titulo": "Gold falls", "idioma": "en"}))
        self.assertFalse(traduccion.hay_que_traducir({"titulo": "Gold falls", "idioma": "es"}))

    def test_traduce_una_sola_vez(self):
        ns = [{"titulo": "Gold falls", "idioma": "en", "fecha": "2026-11-11T10:00:00Z"},
              {"titulo": "Gold falls", "idioma": "en", "fecha": "2026-11-11T09:00:00Z"},
              {"titulo": "El oro baja", "idioma": "es", "fecha": "2026-11-11T08:00:00Z"}]
        self.assertEqual(traduccion.traducir_noticias(ns, CFG), 1)
        self.assertEqual([n.get("titulo_es") for n in ns], ["ES: Gold falls", "ES: Gold falls", None])
        # la siguiente vez sale de la memoria, sin volver a traducir
        otra = [{"titulo": "Gold falls", "idioma": "en"}]
        self.assertEqual(traduccion.traducir_noticias(otra, CFG), 0)
        self.assertEqual(otra[0]["titulo_es"], "ES: Gold falls")
        self.assertEqual(len(TraductorFalso.llamadas), 1)

    def test_descarta_salidas_rotas(self):
        ns = [{"titulo": "Something roto here", "idioma": "en"}]
        traduccion.traducir_noticias(ns, CFG)
        self.assertNotIn("titulo_es", ns[0])
        self.assertFalse(traduccion.parece_buena("Gold falls", "oro oro oro cae"))
        self.assertFalse(traduccion.parece_buena("Gold falls", "El oro cae " * 10))
        self.assertTrue(traduccion.parece_buena("Gold falls", "El oro cae"))

    def test_olvida_lo_antiguo(self):
        self.datos[traduccion.ARCHIVO] = {"Viejo": {"es": "Viejo", "visto": "2020-01-01"}}
        traduccion.traducir_noticias([], CFG)
        self.assertEqual(self.datos[traduccion.ARCHIVO], {})

    def test_sin_traductor_lanza_error_claro(self):
        def roto(mcfg):
            raise ImportError("no hay ctranslate2")
        with mock.patch.object(traduccion, "Traductor", roto):
            with self.assertRaises(RuntimeError):
                traduccion.traducir_noticias([{"titulo": "Gold falls", "idioma": "en"}], CFG)

    def test_huella_incorrecta(self):
        import hashlib
        import tempfile
        from pathlib import Path
        contenido = b"hola"
        respuesta = mock.MagicMock()
        respuesta.__enter__.return_value = respuesta
        respuesta.iter_content.return_value = [contenido]
        with tempfile.TemporaryDirectory() as t, mock.patch.dict("os.environ", {"CEDRON_MODELOS": t}), \
                mock.patch.object(traduccion.requests, "get", return_value=respuesta):
            bien = {"repo": "a/b", "revision": "r1", "archivos": {"x.bin": hashlib.sha256(contenido).hexdigest()}}
            self.assertTrue((traduccion.preparar_modelo(bien) / "x.bin").exists())
            mal = {"repo": "a/b", "revision": "r2", "archivos": {"x.bin": "0" * 64}}
            with self.assertRaises(RuntimeError):
                traduccion.preparar_modelo(mal)
            self.assertFalse((Path(t) / "a__b" / "r2" / "x.bin").exists())


if __name__ == "__main__":
    unittest.main()
