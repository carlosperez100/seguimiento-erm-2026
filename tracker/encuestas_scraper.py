#!/usr/bin/env python3
"""
Tracker de encuestas TotalPoll — encuestas.com.pe
=================================================
LEE (read-only) la pantalla de RESULTADOS de cada encuesta y guarda la serie
temporal de votos en SQLite + exporta un JSON para el dashboard.

ÉTICA / ALCANCE:
  - Solo se consulta la pantalla `results` (datos públicos ya mostrados por el sitio).
  - NUNCA se emite un voto. Este script no llama a la acción de votar de TotalPoll.
  - No usa credenciales ni evade autenticación. Es equivalente a abrir la página de
    resultados y anotar los números, automatizado y periódico.

El endpoint de resultados de TotalPoll es:
  {ajax_url}?action=totalpoll&totalpoll[pollId]=<ID>&totalpoll[action]=view&totalpoll[screen]=results

Persistencia (importante para CI):
  docs/encuestas.json   -> ALMACÉN PERSISTENTE (texto, fusionable en git). Acumula el
                           historial: cada corrida lee el JSON previo, le añade el corte
                           nuevo y lo reescribe. Es lo único que se commitea.
  tracker/encuestas.db  -> base de datos SQLite reconstruida desde el JSON en cada corrida,
                           para consultas locales cómodas. Va en .gitignore (no se versiona:
                           un binario no es fusionable y rompería el rebase del workflow).

La clave estable de cada candidato es su ETIQUETA COMPLETA (nombre + partido), no solo el
nombre, para no perder ni mezclar opciones que compartan nombre (p. ej. dos 'Otro').
"""
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

# --- HTTP con fingerprint de Chrome (TotalPoll/Cloudflare a veces filtran bots) ---
import ssl
import urllib.request

try:
    from curl_cffi import requests as cffi
    _HAS_CFFI = True
except ImportError:
    _HAS_CFFI = False

try:
    import certifi
    _CA = certifi.where()
except ImportError:
    _CA = None

# Escotilla SOLO para depurar en redes corporativas con TLS roto: ENCUESTAS_INSECURE=1
_INSECURE = os.environ.get("ENCUESTAS_INSECURE") == "1"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(HERE, "polls.json")
DB_FILE = os.path.join(HERE, "encuestas.db")
JSON_OUT = os.path.join(ROOT, "docs", "encuestas.json")

PERU_TZ = timezone(timedelta(hours=-5))
IMPERSONATE = "chrome124"
TIMEOUT = 30
RETRIES = 4
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# --------------------------------------------------------------------------- #
#  HTTP
# --------------------------------------------------------------------------- #
def _get_cffi(url):
    verify = False if _INSECURE else (_CA or True)
    r = cffi.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT, verify=verify,
                 headers={"Accept": "text/html,*/*", "User-Agent": UA})
    return r.status_code, r.text


def _get_urllib(url):
    if _INSECURE:
        ctx = ssl._create_unverified_context()
    else:
        ctx = ssl.create_default_context(cafile=_CA) if _CA else ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def _get_syscurl(url):
    """Fallback: usa el `curl` del sistema (almacén TLS del SO).
    Útil en Windows con interceptación TLS corporativa, donde Python no tiene el root
    pero curl.exe (schannel) sí. En Linux usa OpenSSL + ca-certificates."""
    import subprocess
    cmd = ["curl", "-sS", "-L", "--ssl-no-revoke", "--connect-timeout", str(TIMEOUT),
           "-A", UA, url]
    if _INSECURE:
        cmd.insert(1, "-k")
    p = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT + 15)  # bytes (evita cp1252 en Windows)
    if p.returncode != 0:
        raise RuntimeError(f"curl rc={p.returncode}: {p.stderr.decode('utf-8','replace').strip()[:160]}")
    return 200, p.stdout.decode("utf-8", "replace")


def fetch(url):
    """GET con reintentos. Prueba varios transportes y cae al siguiente si falla.
    Orden: curl_cffi (fingerprint Chrome, mejor anti-bot) -> curl del sistema -> urllib."""
    getters = ([_get_cffi] if _HAS_CFFI else []) + [_get_syscurl, _get_urllib]
    last = None
    for intento in range(1, RETRIES + 1):
        for getter in getters:
            try:
                status, text = getter(url)
                if status == 200 and text and text.strip():
                    return text
                last = f"{getter.__name__}: HTTP {status}, {len(text or '')} bytes"
            except Exception as e:  # noqa: BLE001
                last = f"{getter.__name__}: {e}"
            print(f"    [intento {intento}/{RETRIES}] {last}")
        if intento < RETRIES:
            time.sleep(2 ** (intento - 1))   # backoff cortés: 1s, 2s, 4s...
    raise RuntimeError(f"No se pudo obtener {url} :: {last}")


def results_url(ajax_url, poll_id):
    params = {
        "action": "totalpoll",
        "totalpoll[pollId]": str(poll_id),
        "totalpoll[action]": "view",
        "totalpoll[screen]": "results",
    }
    return f"{ajax_url}?{urlencode(params)}"


# --------------------------------------------------------------------------- #
#  Parser de la pantalla de resultados de TotalPoll
# --------------------------------------------------------------------------- #
_RE_QUESTION = re.compile(r'totalpoll-question-content["\']?\s*>(.*?)<div[^>]*totalpoll-question-choices\b', re.S)
_RE_ITEM = re.compile(r'totalpoll-question-choices-item-container.*?'
                      r'(?=totalpoll-question-choices-item-container|totalpoll-buttons|</form>)', re.S)
_RE_LABEL = re.compile(r'totalpoll-question-choices-item-label["\']?\s*>\s*<span[^>]*>(.*?)</span>', re.S)
_RE_PCT = re.compile(r'totalpoll-question-choices-item-votes-bar["\']?\s*style\s*=\s*["\']width:\s*([\d.]+)%', re.S)
_RE_VOTES = re.compile(r'totalpoll-question-choices-item-votes-text[^>]*>(.*?)</div>', re.S)
_RE_IMG = re.compile(r'totalpoll-question-choices-item-content\b.*?<img[^>]+src=["\']([^"\']+)["\']', re.S)
_RE_TAGS = re.compile(r'<[^>]*>')
_SPLIT_PARTY = re.compile(r'\s*[-–—]\s*')


def _clean(s):
    import html as _html
    s = _RE_TAGS.sub(" ", s or "")
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_results(htmltext):
    """Devuelve {'pregunta': str, 'total': int, 'candidatos': [ {...} ]}."""
    q = _RE_QUESTION.search(htmltext)
    pregunta = _clean(q.group(1)) if q else ""

    candidatos = []
    for m in _RE_ITEM.finditer(htmltext):
        block = m.group(0)
        lab = _RE_LABEL.search(block)
        if not lab:
            continue
        etiqueta = _clean(lab.group(1))
        if not etiqueta:
            continue
        partes = _SPLIT_PARTY.split(etiqueta, maxsplit=1)
        nombre = partes[0].strip()
        partido = partes[1].strip() if len(partes) > 1 else ""

        votos = 0
        vt = _RE_VOTES.search(block)
        if vt:
            digits = re.sub(r"[^\d]", "", _clean(vt.group(1)))
            votos = int(digits) if digits else 0

        pct_sitio = None
        pm = _RE_PCT.search(block)
        if pm:
            try:
                pct_sitio = float(pm.group(1))
            except ValueError:
                pct_sitio = None

        img = None
        im = _RE_IMG.search(block)
        if im:
            img = im.group(1)

        candidatos.append({
            "nombre": nombre, "partido": partido, "etiqueta": etiqueta,
            "votos": votos, "pct_sitio": pct_sitio, "img": img,
        })

    total = sum(c["votos"] for c in candidatos)
    # Recalcula porcentaje desde los votos (consistente con el total observado).
    for c in candidatos:
        c["pct"] = round(c["votos"] * 100.0 / total, 2) if total else 0.0
    candidatos.sort(key=lambda c: c["votos"], reverse=True)
    return {"pregunta": pregunta, "total": total, "candidatos": candidatos}


# --------------------------------------------------------------------------- #
#  Almacén persistente: docs/encuestas.json (texto, fusionable)
# --------------------------------------------------------------------------- #
FUENTE = {"n": "encuestas.com.pe (encuesta online TotalPoll, no probabilística)",
          "u": "https://encuestas.com.pe/"}


def load_state():
    """Carga el JSON persistente previo (o un estado vacío)."""
    if os.path.exists(JSON_OUT):
        try:
            st = json.load(open(JSON_OUT, encoding="utf-8"))
            st.setdefault("polls", [])
            return st
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] docs/encuestas.json ilegible ({e}); se empieza de cero.")
    return {"polls": []}


def poll_state(state, poll_cfg):
    """Devuelve (creando si hace falta) el bloque de estado de un poll."""
    for p in state["polls"]:
        if p.get("id") == poll_cfg["id"]:
            return p
    p = {"id": poll_cfg["id"], "nombres": {}, "historial": [], "candidatos": [], "total": 0}
    state["polls"].append(p)
    return p


def append_corte(ps, poll_cfg, parsed, ts_utc, ts_peru):
    """Añade un corte al historial del poll. Clave estable = etiqueta completa.
    Devuelve cuántas opciones se descartaron por clave duplicada dentro del corte."""
    ps["municipio"] = poll_cfg.get("municipio")
    ps["etiqueta"] = poll_cfg.get("etiqueta")
    ps["pagina"] = poll_cfg.get("pagina")
    ps["destacar"] = poll_cfg.get("destacar", [])
    ps["pregunta"] = parsed["pregunta"] or ps.get("pregunta", "")

    por = {}
    descartados = 0
    for c in parsed["candidatos"]:
        key = c["etiqueta"]                      # nombre + partido (estable)
        if key in por:                           # clave repetida en el mismo corte
            descartados += 1
            continue
        por[key] = {"votos": c["votos"], "pct": c["pct"]}
        ps["nombres"][key] = {"nombre": c["nombre"], "partido": c["partido"]}

    # Reemplaza el corte si ya existía ese ts (re-ejecución); luego ordena.
    ps["historial"] = [h for h in ps["historial"] if h.get("ts") != ts_utc]
    ps["historial"].append({"ts": ts_utc, "ts_peru": ts_peru,
                            "total": parsed["total"], "por_candidato": por})
    ps["historial"].sort(key=lambda h: h["ts"])

    ps["total"] = parsed["total"]
    ps["candidatos"] = sorted(
        [{"key": k, "nombre": ps["nombres"][k]["nombre"],
          "partido": ps["nombres"][k]["partido"], "votos": v["votos"], "pct": v["pct"]}
         for k, v in por.items()],
        key=lambda x: x["votos"], reverse=True)
    return descartados


def write_state(state, cfg):
    """Ordena los polls según cfg y escribe el JSON persistente."""
    orden = {p["id"]: i for i, p in enumerate(cfg["polls"])}
    state["polls"].sort(key=lambda p: orden.get(p["id"], 999))
    state["actualizado"] = datetime.now(PERU_TZ).strftime("%d/%m/%Y %H:%M") + " (hora Perú)"
    state["fuente"] = FUENTE
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
#  SQLite local (reconstruida desde el JSON; va en .gitignore)
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS mediciones (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc      TEXT NOT NULL,
    ts_peru     TEXT,
    poll_id     INTEGER NOT NULL,
    municipio   TEXT,
    poll_etiqueta TEXT,
    pregunta    TEXT,
    cand_label  TEXT NOT NULL,
    candidato   TEXT,
    partido     TEXT,
    votos       INTEGER NOT NULL,
    pct         REAL,
    total_poll  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_poll_ts ON mediciones(poll_id, ts_utc);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_corte ON mediciones(poll_id, ts_utc, cand_label);
"""


def rebuild_sqlite(state):
    """Reconstruye la BD SQLite desde el estado JSON (historial completo)."""
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    conn = sqlite3.connect(DB_FILE)
    conn.executescript(SCHEMA)
    rows = []
    for p in state["polls"]:
        nombres = p.get("nombres", {})
        for h in p.get("historial", []):
            for key, v in h["por_candidato"].items():
                nm = nombres.get(key, {"nombre": key, "partido": ""})
                rows.append((h["ts"], h.get("ts_peru", ""), p["id"], p.get("municipio"),
                             p.get("etiqueta"), p.get("pregunta"), key, nm["nombre"],
                             nm["partido"], v["votos"], v["pct"], h.get("total")))
    conn.executemany(
        "INSERT OR IGNORE INTO mediciones "
        "(ts_utc,ts_peru,poll_id,municipio,poll_etiqueta,pregunta,cand_label,candidato,partido,votos,pct,total_poll) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return len(rows)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    ahora = datetime.now(timezone.utc)
    ts_utc = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_peru = ahora.astimezone(PERU_TZ).strftime("%d/%m/%Y %H:%M")

    state = load_state()        # historial previo (persistido en git)
    ok = 0
    for i, poll in enumerate(cfg["polls"]):
        pid = poll["id"]
        print(f"[poll {pid}] {poll.get('etiqueta','')} ({poll.get('municipio','')})")
        try:
            html_res = fetch(results_url(cfg["ajax_url"], pid))
            parsed = parse_results(html_res)
            if not parsed["candidatos"]:
                print("    [--] sin candidatos parseados (¿cambió el HTML? ¿poll cerrado?). Se conserva el historial previo.")
                continue
            ps = poll_state(state, poll)
            descartados = append_corte(ps, poll, parsed, ts_utc, ts_peru)
            top = parsed["candidatos"][0]
            aviso = f" | ⚠ {descartados} opción(es) con clave duplicada descartadas" if descartados else ""
            print(f"    [ok] '{parsed['pregunta'][:55]}...' | {len(parsed['candidatos'])} cand. | "
                  f"total={parsed['total']} | lider: {top['nombre']} {top['votos']} ({top['pct']}%) | "
                  f"cortes={len(ps['historial'])}{aviso}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"    [ERROR] {e} (se conserva el historial previo de este poll)")
        if i < len(cfg["polls"]) - 1:
            time.sleep(1.5)     # pausa cortés entre polls

    write_state(state, cfg)
    n = rebuild_sqlite(state)
    print(f"\nListo. Polls capturados esta corrida: {ok}/{len(cfg['polls'])}. "
          f"JSON: {JSON_OUT} | SQLite (local): {DB_FILE} ({n} filas)")
    # No fallar el workflow por un poll caído; 0 capturas sí es error.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
