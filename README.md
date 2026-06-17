# Seguimiento ERM 2026 — Lima & San Borja

Tablero **interno** de análisis estratégico (FODA) por candidato a alcalde, para las
**Elecciones Regionales y Municipales 2026** (votación: **4 de octubre de 2026**).

- **Lima:** Luis "Lucho" Rubio Idrogo (Renovación Popular)
- **San Borja:** Carlos Merino *(por verificar en el JNE)*

El **nombre y la foto** de cada candidato provienen de fuentes **oficiales (JNE / Estado peruano)**,
y cada dato del FODA lleva su **fuente citada**. La herramienta no scrapea resultados en vivo
(la elección aún no ocurre): es seguimiento estratégico.

> ⚠️ **Uso interno.** Las secciones de *Debilidades* y *Amenazas* recogen reportes, encuestas y
> críticas **ya publicadas** en prensa o en fuentes oficiales, **citando la fuente**. No son
> afirmaciones del autor del tablero ni hechos comprobados por este. Verificar siempre la fuente.

Tiene **dos módulos**:
1. **Ficha & FODA** (`docs/index.html`) — análisis estratégico por candidato (lo de arriba).
2. **Tracker de encuestas online** (`docs/encuestas.html`) — guarda y grafica cómo evolucionan
   los votos de la encuesta abierta de encuestas.com.pe, **hora a hora** (ver más abajo).

## Estructura

```
docs/index.html       → tablero FODA (lee data.json)
docs/data.json        → fuente de la verdad del FODA: candidatos y fuentes (EDITABLE)
docs/encuestas.html   → tablero de evolución de encuestas online (lee encuestas.json)
docs/encuestas.json   → ALMACÉN PERSISTENTE de la serie temporal (texto, se versiona)
scraper/jne_fetch.py  → trae nombre/foto oficial desde la Plataforma Electoral del JNE
tracker/encuestas_scraper.py → LEE (read-only) los resultados de encuestas.com.pe y los guarda
tracker/encuestas.db  → SQLite reconstruida desde el JSON (consultas locales; en .gitignore)
tracker/polls.json    → qué encuestas trackear (Lima 22042, San Borja 22198)
tracker/test_parser.py → test offline del parser contra un fixture
.github/workflows/actualizar.yml → fetch JNE 1×/día
.github/workflows/encuestas.yml  → tracker de encuestas 1×/hora
```

## Módulo 2 — Tracker de encuestas online (encuestas.com.pe)

encuestas.com.pe usa el plugin **TotalPoll**. Su pantalla de **resultados es pública** y se
consulta así (no requiere votar):

```
https://encuestas.com.pe/wp-admin/admin-ajax.php?action=totalpoll&totalpoll[pollId]=<ID>&totalpoll[action]=view&totalpoll[screen]=results
```

`tracker/encuestas_scraper.py` lee esa pantalla para cada encuesta de `polls.json`, parsea
nombre/partido/votos/porcentaje y **añade un corte con fecha-hora**. La clave de cada candidato
es su **etiqueta completa (nombre + partido)**, estable, para no mezclar opciones con el mismo
nombre.

**Persistencia:** el almacén que se versiona es **`docs/encuestas.json`** (texto, fusionable):
cada corrida lee el JSON previo, le agrega el corte nuevo y lo reescribe. La **base SQLite**
(`tracker/encuestas.db`) se **reconstruye desde ese JSON** en cada corrida para consultas
locales cómodas, y **no se versiona** (un binario no es fusionable y rompería el `rebase` del
workflow). El workflow `encuestas.yml` corre **cada hora**, commitea solo el JSON, y hace
`git pull --rebase` antes de `push`; comparte `concurrency: commit-main` con `actualizar.yml`
para que nunca dos workflows empujen a `main` a la vez.

> ⚖️ **Ética y alcance — IMPORTANTE.**
> - Solo se **lee** la pantalla de resultados (datos públicos que el sitio ya muestra).
>   **Nunca se emite un voto**: el scraper no llama a la acción de votar de TotalPoll.
> - **No se vota automáticamente por nadie.** Inflar una encuesta (ballot stuffing) sería
>   manipulación; este proyecto no lo hace ni debe hacerlo.
> - La encuesta de encuestas.com.pe es un **sondeo online auto-seleccionado, NO probabilístico**:
>   vota quien quiere y una campaña puede movilizar votos. **No es representativa** ni es una
>   proyección electoral. Úsese solo como señal de actividad/momentum en esa plataforma.

### Correrlo en local
```bash
pip install -r tracker/requirements.txt
python tracker/encuestas_scraper.py          # captura un corte ahora
python tracker/test_parser.py                # valida el parser (offline)
cd docs && python -m http.server 8000        # abre http://localhost:8000/encuestas.html
```
El scraper prueba tres transportes (curl_cffi con fingerprint Chrome → curl del sistema → urllib),
así funciona tanto en GitHub Actions como en Windows con interceptación TLS corporativa.
Para añadir o quitar encuestas, edita `tracker/polls.json` (cada una con su `id` de TotalPoll).

## Cómo se usa

### 1. Ver el tablero localmente
```bash
cd docs
python -m http.server 8000
# abre http://localhost:8000
```
(Abrirlo con doble clic falla por seguridad del navegador al leer `data.json`; usa el servidor local.)

### 2. Editar el contenido
Todo el contenido vive en **`docs/data.json`**. Para añadir un punto fuerte/débil:

```json
{ "t": "Texto del punto.", "f": { "n": "Nombre de la fuente", "u": "https://enlace-a-la-fuente" } }
```

- `fortalezas` / `oportunidades` / `debilidades` / `amenazas`: listas de puntos. **Siempre con `f` (fuente).**
- `foto_oficial`: pega aquí la URL de la foto **oficial del JNE** cuando la lista se inscriba.
  Si está vacía, el tablero muestra las iniciales del candidato.
- `verificado_jne`: ponlo en `true` cuando confirmes la candidatura en el JNE.

### 3. Publicar en GitHub Pages (gratis)
1. Crea un repo en https://github.com/new (p. ej. `seguimiento-erm-2026`).
2. Sube esta carpeta (puedes usar `SUBIR_A_GITHUB.sh`).
3. Repo → **Settings → Pages** → Branch `main`, carpeta `/docs` → **Save**.
4. En 1–2 min estará en `https://TU_USUARIO.github.io/seguimiento-erm-2026/`.

> ⚠️ **Privacidad — léelo antes de publicar.** GitHub Pages **gratis exige repo público**.
> Si haces público este repo, **todo el historial commiteado por los bots queda público**:
> cada corte horario de `docs/encuestas.json` y cada cambio de `docs/data.json` (seguimiento
> electoral interno). Si el contenido es sensible, **mantén el repo privado** y abre los
> tableros solo en local (`python -m http.server` en `docs/`), o usa hosting propio. Pages
> sobre repos privados solo está en planes de pago. Recuerda que un repo que fue público
> puede haber quedado indexado/clonado aunque luego lo vuelvas privado.

### 4. Traer la foto oficial del JNE automáticamente
Cuando el JNE admita la lista, cada candidato tendrá un id de hoja de vida en la
Plataforma Electoral. Agrégalo en `data.json`:

```json
"jne": { "id_hoja_vida": "EL_ID_DEL_JNE" }
```

El workflow `actualizar.yml` corre `scraper/jne_fetch.py` una vez al día, busca la foto
oficial y la guarda **sin tocar lo demás**. Si aún no hay datos, no cambia nada (es lo esperado).

## Fuentes principales

- JNE — Plataforma Electoral: https://plataformaelectoral.jne.gob.pe/
- Infogob (JNE) — San Borja: https://infogob.jne.gob.pe/
- Estado peruano (gob.pe) — SISOL: https://www.gob.pe/institucion/sisol
- Cobertura de prensa citada dentro del propio tablero (sección *Fuentes / Referencias*).

## Notas de responsabilidad

- No se inventan hechos ni afirmaciones sobre personas. Lo que no está verificado se marca como tal.
- "Carlos Merino" (San Borja) figura **sin registro oficial localizado** al 17/06/2026: su ficha
  queda marcada *No verificado en JNE* y su FODA, vacío, para completar con información verificada.
