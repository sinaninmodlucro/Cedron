"""Traduccion automatica al espanol de los titulares de las noticias (11-nov-2026).

Se traduce en la propia automatizacion, sin internet ni claves: un modelo de traduccion
abierto (seccion `traduccion` de config.yaml) que se baja una vez de Hugging Face, fijado a
una version concreta y comprobado con su huella SHA-256, y se ejecuta con CTranslate2.
Asi no hay limites de consultas (llegan unos 400 titulares en ingles al dia, ~30.000
caracteres: mas de lo que dan gratis DeepL o Google) ni condiciones de terceros.

Cada titular se traduce una sola vez: las traducciones se guardan en
data/traducciones.json ({titular original: {"es": traduccion, "visto": fecha}}) y se
olvidan las que no se ven en `dias_memoria` dias.

Si el traductor no esta disponible (por ejemplo, en Windows sin las librerias de Microsoft),
las noticias se publican sin traducir y el fallo queda en «Estado de los datos».
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path

import requests

from .store import escribir, iso, leer

log = logging.getLogger("cedron.traduccion")

ARCHIVO = "traducciones.json"

# Palabras muy frecuentes en espanol: sirven para no traducir titulares que ya lo estan
# cuando la fuente no dice el idioma (NewsData a veces no lo da).
_ES = {"el", "la", "los", "las", "del", "de", "en", "por", "para", "con", "que", "una", "un", "se",
       "sus", "su", "al", "y", "más", "tras", "sube", "baja", "precio", "precios", "años", "según"}
_EN = {"the", "of", "to", "in", "for", "on", "as", "and", "with", "from", "at", "by", "after",
       "prices", "price", "rise", "falls", "rises", "fall", "amid", "over", "says", "us", "its"}


def idioma_probable(titulo: str) -> str:
    """'es', 'en' o '' segun las palabras mas frecuentes de cada idioma."""
    p = re.findall(r"[a-záéíóúñü]+", titulo.lower())
    es, en = sum(w in _ES for w in p), sum(w in _EN for w in p)
    if re.search(r"[ñáéíóú¿¡]", titulo.lower()):
        es += 2
    return "es" if es > en else "en" if en > es else ""


def hay_que_traducir(n: dict) -> bool:
    idioma = (n.get("idioma") or "").lower()
    if idioma:
        return idioma != "es"
    return idioma_probable(n.get("titulo") or "") == "en"


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
def carpeta_modelos() -> Path:
    base = os.environ.get("CEDRON_MODELOS")
    return Path(base) if base else Path.home() / ".cache" / "cedron" / "modelos"


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def preparar_modelo(mcfg: dict) -> Path:
    """Baja (si falta) el modelo fijado en config.yaml y comprueba cada archivo. Devuelve su carpeta."""
    destino = carpeta_modelos() / mcfg["repo"].replace("/", "__") / mcfg["revision"]
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, huella in mcfg["archivos"].items():
        ruta = destino / nombre
        if ruta.exists() and _sha256(ruta) == huella:
            continue
        url = f"https://huggingface.co/{mcfg['repo']}/resolve/{mcfg['revision']}/{nombre}"
        log.info("Bajando %s", url)
        temporal = ruta.with_suffix(ruta.suffix + ".parcial")
        with requests.get(url, stream=True, timeout=(15, 300)) as r:
            r.raise_for_status()
            with open(temporal, "wb") as f:
                for trozo in r.iter_content(1 << 20):
                    f.write(trozo)
        if _sha256(temporal) != huella:
            temporal.unlink(missing_ok=True)
            raise RuntimeError(f"la huella de {nombre} no coincide: archivo descartado")
        temporal.replace(ruta)
    return destino


class Traductor:
    """Traductor ingles -> espanol con CTranslate2 (MADLAD-400; vale tambien para OPUS-MT)."""

    def __init__(self, mcfg: dict):
        import ctranslate2
        import sentencepiece as spm
        carpeta = preparar_modelo(mcfg)
        self.modelo = ctranslate2.Translator(str(carpeta), device="cpu", compute_type="int8",
                                             intra_threads=int(mcfg.get("hilos") or 0))
        self.origen = spm.SentencePieceProcessor(model_file=str(carpeta / mcfg["vocab_origen"]))
        self.destino = spm.SentencePieceProcessor(model_file=str(carpeta / mcfg["vocab_destino"]))
        self.prefijo = mcfg.get("prefijo") or ""        # MADLAD: «<2es> » = traducir al espanol
        self.haz = int(mcfg.get("haz", 2))

    def traducir(self, textos: list[str], lote: int = 8, segundos: float | None = None) -> list[str]:
        """Traduce en lotes; si se pasa `segundos`, para al agotarse ese tiempo (devuelve menos)."""
        import time
        inicio, salida = time.monotonic(), []
        for i in range(0, len(textos), lote):
            if segundos is not None and time.monotonic() - inicio > segundos:
                break
            parte = textos[i:i + lote]
            # La marca de fin de frase es imprescindible: sin ella el modelo repite palabras
            fichas = [self.origen.encode(self.prefijo + t, out_type=str) + ["</s>"] for t in parte]
            res = self.modelo.translate_batch(fichas, beam_size=self.haz, max_batch_size=lote,
                                              max_decoding_length=2 * max(len(f) for f in fichas) + 10)
            salida += [limpiar(self.destino.decode_pieces(r.hypotheses[0])) for r in res]
        return salida


def limpiar(texto: str) -> str:
    texto = re.sub(r"\$ (\d)", r"$\1", texto.strip())       # «$ 92» -> «$92»
    return re.sub(r"\s+", " ", texto)


def parece_buena(original: str, traduccion: str) -> bool:
    """Descarta salidas rotas: vacias, mucho mas largas que el original o con palabras repetidas."""
    if not traduccion:
        return False
    if len(traduccion) > 2.2 * len(original) + 20:
        return False
    palabras = traduccion.lower().split()
    return not any(palabras[i] == palabras[i + 1] == palabras[i + 2] for i in range(len(palabras) - 2))


# ---------------------------------------------------------------------------
# Uso desde el motor y la web
# ---------------------------------------------------------------------------
def completar(noticias: list[dict], memoria: dict | None = None) -> int:
    """Pone «titulo_es» a las noticias que ya tienen traduccion guardada. Devuelve cuantas faltan."""
    if memoria is None:
        memoria = leer(ARCHIVO, {}) or {}
    faltan = 0
    for n in noticias:
        if n.get("titulo_es") or not hay_que_traducir(n):
            continue
        t = (memoria.get(n["titulo"]) or {}).get("es")
        if t:
            n["titulo_es"] = t
        else:
            faltan += 1
    return faltan


def traducir_noticias(noticias: list[dict], cfg: dict) -> int:
    """Traduce los titulares nuevos (en el sitio) y guarda la memoria. Devuelve cuantos tradujo.

    Lanza RuntimeError si el traductor no se puede usar (el motor lo apunta en el estado).
    """
    tcfg = cfg.get("traduccion") or {}
    memoria = leer(ARCHIVO, {}) or {}
    hoy = iso()[:10]
    pendientes = []
    # primero las mas nuevas: asi lo ultimo que llega sale ya traducido
    for n in sorted(noticias, key=lambda n: n.get("fecha") or "", reverse=True):
        if not hay_que_traducir(n):
            continue
        guardada = memoria.get(n["titulo"])
        if guardada:
            guardada["visto"] = hoy
            n["titulo_es"] = guardada["es"]
        elif n["titulo"] not in pendientes:
            pendientes.append(n["titulo"])
    pendientes = pendientes[: int(tcfg.get("max_por_ejecucion", 60))]
    hechas = 0
    if pendientes:
        try:
            traductor = Traductor(tcfg["modelo"])
            traducciones = traductor.traducir(pendientes, segundos=float(tcfg.get("segundos_max", 240)))
        except Exception as e:      # librerias ausentes, descarga fallida, modelo roto...
            raise RuntimeError(f"traductor no disponible: {e}") from e
        for original, es in zip(pendientes, traducciones):
            if parece_buena(original, es):
                memoria[original] = {"es": es, "visto": hoy}
                hechas += 1
        completar(noticias, memoria)
    # se olvidan las traducciones que llevan tiempo sin verse
    from datetime import date, timedelta
    corte = (date.fromisoformat(hoy) - timedelta(days=int(tcfg.get("dias_memoria", 60)))).isoformat()
    memoria = {k: v for k, v in memoria.items() if v.get("visto", hoy) >= corte}
    escribir(ARCHIVO, memoria)
    return hechas
