"""Cifrado de la web de Cedron con contrasena.

Cada pagina HTML se cifra con AES-256-GCM. La clave se deriva de la contrasena
con PBKDF2-HMAC-SHA256 (600.000 iteraciones). El navegador la descifra con la
API WebCrypto: sin la contrasena, el contenido publicado es ilegible.

La sal es publica y fija (data/cifrado.json) para que la clave derivada siga
valiendo entre actualizaciones y no haya que escribir la contrasena cada hora.
Si se cambia la contrasena, basta con volver a escribirla en el navegador.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .store import leer, escribir

ITERACIONES = 600_000


def _sal() -> bytes:
    guardado = leer("cifrado.json") or {}
    if "sal" not in guardado:
        guardado = {"sal": base64.b64encode(os.urandom(16)).decode(), "iteraciones": ITERACIONES}
        escribir("cifrado.json", guardado)
    return base64.b64decode(guardado["sal"])


def cifrar_sitio(destino: Path, contrasena: str, plantilla: str) -> int:
    if len(contrasena) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres")
    sal = _sal()
    clave = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), sal, ITERACIONES, dklen=32)
    aes = AESGCM(clave)
    n = 0
    for pagina in sorted(destino.rglob("*.html")):
        claro = pagina.read_bytes()
        iv = os.urandom(12)
        cifrado = aes.encrypt(iv, claro, None)
        raiz = "../" * (len(pagina.relative_to(destino).parts) - 1)
        datos = json.dumps({"s": base64.b64encode(sal).decode(), "i": ITERACIONES,
                            "v": base64.b64encode(iv).decode(), "c": base64.b64encode(cifrado).decode()})
        pagina.write_text(plantilla.replace("__DATOS__", datos).replace("__RAIZ__", raiz), encoding="utf-8")
        n += 1
    return n
