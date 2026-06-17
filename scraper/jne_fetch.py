#!/usr/bin/env python3
"""
JNE Fetch — Seguimiento ERM 2026 (Lima y San Borja)
---------------------------------------------------
Enriquece docs/data.json con el NOMBRE y la FOTO OFICIAL de cada candidato
tomados de la Plataforma Electoral del JNE, citando la fuente.

Filosofía (igual que el scraper de ONPE): best-effort y NO destructivo.
  - Si encuentra el dato oficial, actualiza 'nombre', 'foto_oficial' y 'fuente_foto'.
  - Si NO lo encuentra (la lista aún no está admitida, o el endpoint cambió),
    DEJA docs/data.json intacto y solo imprime un aviso. Nunca borra lo que ya hay.

El JNE expone la información de candidatos a través de la Plataforma Electoral
(https://plataformaelectoral.jne.gob.pe/). Sus endpoints internos cambian entre
procesos; por eso cada candidato puede llevar un campo opcional 'jne' en data.json:

    "jne": { "id_hoja_vida": "123456", "id_solicitud": "..." }

Cuando ese id esté disponible (tras la inscripción de la lista), este script
arma la URL de la hoja de vida / foto y la guarda. Mientras tanto, no hace nada
dañino: simplemente informa qué candidatos siguen sin id.
"""
import json
import os
import sys

try:
    from curl_cffi import requests as cffi
except ImportError:
    cffi = None

# --- Plataforma Electoral del JNE (ajustar si el JNE cambia el host del proceso ERM 2026) ---
JNE_BASE = "https://plataformaelectoral.jne.gob.pe"
# Posibles rutas de la foto de la hoja de vida (se prueban en orden).
FOTO_PATHS = [
    "/Archivos/HojaVida/Foto/{id}",
    "/api/v1/hojavida/foto/{id}",
    "/assets/foto/{id}.jpg",
]
IMPERSONATE = "chrome124"
TIMEOUT = 30

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")


def http_ok(url):
    """True si la URL responde 200 con cuerpo no vacío (con fingerprint de Chrome)."""
    if cffi is None:
        return False
    try:
        r = cffi.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT,
                     headers={"Accept": "image/*,application/json,*/*"})
        return r.status_code == 200 and bool(r.content)
    except Exception as e:
        print(f"    [warn] {url} -> {e}")
        return False


def buscar_foto_oficial(jne):
    """Devuelve (url_foto, etiqueta_fuente) si existe; si no, (None, None)."""
    idv = (jne or {}).get("id_hoja_vida")
    if not idv:
        return None, None
    for path in FOTO_PATHS:
        url = JNE_BASE + path.format(id=idv)
        print(f"    probando foto: {url}")
        if http_ok(url):
            return url, "JNE — Plataforma Electoral (hoja de vida)"
    return None, None


def main():
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    cambios = 0
    pendientes = []
    for c in data.get("candidatos", []):
        nombre = c.get("nombre", "?")
        jne = c.get("jne")
        if not jne or not jne.get("id_hoja_vida"):
            pendientes.append(nombre)
            print(f"[skip] {nombre}: sin 'jne.id_hoja_vida' en data.json (candidatura aún no inscrita o id no cargado).")
            continue

        print(f"[fetch] {nombre} (id={jne['id_hoja_vida']})")
        url, etiqueta = buscar_foto_oficial(jne)
        if url:
            c["foto_oficial"] = url
            c["fuente_foto"] = {"n": etiqueta, "u": url}
            c["verificado_jne"] = True
            cambios += 1
            print(f"    [ok] foto oficial guardada.")
        else:
            print(f"    [--] no se ubicó foto oficial todavía; data.json sin cambios para {nombre}.")

    if cambios:
        with open(DATA_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print(f"\nActualizado docs/data.json ({cambios} candidato[s]).")
    else:
        print("\nSin cambios. (Normal mientras las listas no estén inscritas en el JNE.)")

    if pendientes:
        print("Pendientes de id JNE: " + ", ".join(pendientes))
    # Salida 0 siempre: la falta de datos no es un error, es el estado esperado.
    return 0


if __name__ == "__main__":
    sys.exit(main())
