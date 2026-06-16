# Bot de Alquileres CABA — Spec de Mejoras + Handoff de Sesión

- **Fecha:** 2026-06-16
- **Estado:** ✅ Diseño aprobado por el usuario. ⏳ Pendiente: implementación.
- **Próximo paso:** ejecutar el "Plan de implementación" de abajo (idealmente con la skill `writing-plans` → `executing-plans`).

---

## TL;DR para retomar en frío

El bot scrapea alquileres en CABA y avisa por Telegram. **Corría en GitHub Actions 2×/día y funcionaba** (persistía estado, encontraba algunas propiedades), pero con **bajo volumen** (~+1/día vs 24-67 en una corrida local). **Decisión del usuario: mover la ejecución a la PC local con Windows Task Scheduler**, para maximizar cobertura (la primera corrida local agarra todo el backlog), esquivar cualquier bloqueo por IP de datacenter, y no depender de la nube. Trade-off aceptado: la PC tiene que estar prendida a la hora agendada. El resto del trabajo es limpiar código muerto, externalizar filtros a `config.json` y agregar TTL al historial.

**NO hace falta `curl-cffi`** — se probó en vivo y no mejora nada sobre el `cloudscraper` actual (ver evidencia).

---

## Contexto del proyecto

- Script único: `rental_alert.py` (~1200 líneas en el working tree).
- Scrapea **ZonaProp, ArgProp, MercadoLibre, Properati, Roomix**; filtra por barrio/precio/ambientes/m²/cochera/espacio exterior; manda alertas por Telegram (con preview de imagen).
- Filtros hardcodeados al inicio del `.py`:
  - `BARRIOS_OBJETIVO` = Boedo, Almagro, Parque Patricios, Balvanera, San Cristóbal, San Telmo, Parque Chacabuco
  - `PRECIO_MAX = 1_400_000` ARS (alquiler + expensas)
  - `AMBIENTES_MIN = 3`
- Historial anti-duplicados: `seen_listings.json` (actualmente un `set` de hashes MD5 de URLs).
- Setup documentado en `GUIA_SETUP.md`.
- **Horizonte de uso:** solo un par de meses. Presupuesto: **$0**. (El usuario tiene GitHub Student Developer Pack, pero no se necesita.)

---

## Prioridades del usuario (de la sesión de brainstorming)

- **A) Confiabilidad de scrapers / saltar bloqueos** ← prioridad principal.
- **B) Re-envíos entre runs** (que no reenvíe listings ya vistos cuando el historial se pierde).
- **C) Calidad de resultados.**
- **D) Infra / robustez del pipeline.**

---

## Investigación (evidencia, no supuestos)

### 1. Log de corrida real — `rental_alert.log`, 2026-06-06 (PC local, IP residencial)

| Scraper | Comportamiento real |
|---|---|
| **ArgProp** | ✅ El más confiable: 24-25 propiedades en *todas* las corridas. No necesita arreglo. |
| **ZonaProp** | ⚠️ Usa **cloudscraper** (NO Playwright). Intermitente: a veces trae `__PRELOADED_STATE__` con 30 postings/página; a veces devuelve HTTP 200 *sin* el marcador. Las fallas fueron **rate-limiting temporal** por hacer ~10 corridas seguidas debuggeando, no un bloqueo permanente. |
| **ML API** (`scrape_mercadolibre`) | ❌ **403 siempre**, incluso con token válido. Endpoint `/sites/MLA/search` **deprecado/restringido** por ML en 2025. Código muerto. |
| **ML Playwright** (`scrape_mercadolibre_playwright`) | ⚠️ Funciona a veces (97 props) y a veces 0 cards. Bug: `Execution context was destroyed, most likely because of a navigation` durante el scroll. |
| **Properati** | ❌ 0 resultados, siempre. |
| **Roomix** | ❌ 0 resultados, siempre. |

### 2. Probe en vivo: `curl-cffi` vs `cloudscraper` contra ZonaProp (2026-06-16)

Ejecutado contra la URL real del bot y la URL simple de debug, con `impersonate` chrome/124/120/110:

```
=== URL búsqueda (la del bot) ===
  [curl-cffi chrome   ] HTTP 200, 1397893 bytes → OK marcador presente, 30 postings
  [curl-cffi chrome124] HTTP 200, 1397893 bytes → OK marcador presente, 30 postings
  [cloudscraper       ] HTTP 200, 1397893 bytes → OK marcador presente, 30 postings
=== URL simple (debug) ===
  [curl-cffi chrome   ] HTTP 200, 1240973 bytes → OK marcador presente, 21 postings
  [cloudscraper       ] HTTP 200, 1240973 bytes → OK marcador presente, 21 postings
```

**Conclusión:** mismos bytes exactos, mismos resultados. `curl-cffi` **no aporta ventaja** sobre el `cloudscraper` actual desde IP residencial. ZonaProp funciona bien cuando no se lo bombardea.

> Nota técnica (confirmada por búsqueda web): `curl-cffi` resuelve solo el **fingerprint TLS/JA3**, NO los challenges de JavaScript de Cloudflare ni la **reputación de IP**. Por eso no arregla el bloqueo de Actions.

### 3. Forense de GitHub Actions (git history — CORREGIDO)

> ⚠️ Mi análisis inicial dijo "Actions corrió 1 sola vez y está ciego". **Era falso** — estaba mirando el clon local que estaba 20 commits atrás del remoto. Al traer `origin/main` apareció la verdad:

- Actions **viene corriendo confiable 2×/día desde el 2026-06-06 hasta el 2026-06-15** (20+ auto-commits `[skip ci]`).
- **Persiste el estado**: cada run commitea `seen_listings.json` de vuelta y lo recupera en el siguiente. → Prioridad B (re-envíos) **ya estaba resuelta en Actions**, contrario a lo que dije antes.
- Crecimiento de entradas: 93 (06-06) → 94 → 97 (06-08) → 104 (06-12) → 104 (06-15). **+11 en 9 días (~1/día).** Una corrida local sola encontró 24-67.

**Conclusión honesta (ambigua):** Actions funciona pero con bajo volumen. No se pudo determinar si el goteo es por **bloqueo parcial** (ArgProp 403 / ZonaProp) o porque con filtros tan ajustados **genuinamente aparecen ~1-2 listings nuevos/día** una vez agotado el backlog. Para zanjarlo haría falta: (a) los logs por-fuente de los runs de Actions (GitHub web / `gh run view --log`), o (b) una corrida local de prueba contando nuevos vs los ~104 ya vistos. **El usuario eligió migrar a local igual** — válido: la primera corrida local agarra el backlog completo y elimina la duda del bloqueo de raíz.

---

## Decisiones clave aprobadas

1. **Ejecutar local con Windows Task Scheduler, 2×/día.** Reemplaza GitHub Actions como vía principal. Motivo: maximizar cobertura (la primera corrida local agarra todo el backlog) y esquivar cualquier posible bloqueo por IP de datacenter (prioridad A). Nota: la persistencia de `seen_listings.json` (prioridad B) ya funcionaba en Actions; local también la mantiene. Trade-off aceptado: la PC tiene que estar prendida a la hora agendada (es una desktop; agendar ~9:00 y ~19:00).
2. **No usar `curl-cffi`.** El probe demostró que no mejora nada. Mantener `cloudscraper`.
3. **Borrar el workflow de GitHub Actions** (`.github/workflows/busqueda_diaria.yml`). ← hecho en este handoff.
4. **Borrar código muerto:** `scrape_mercadolibre()` (API) + `get_ml_token()`, `scrape_properati()`, `scrape_roomix()`.

---

## Diseño aprobado (8 puntos)

1. **Ejecución** → Windows Task Scheduler, 2×/día, corriendo `python rental_alert.py` desde la carpeta del repo.
2. **curl-cffi** → no se agrega. Desinstalar si quedó del probe.
3. **ZonaProp** → mantener cloudscraper + **retry con backoff exponencial** (p. ej. 3s, 9s, 27s) cuando falte `__PRELOADED_STATE__` o haya 403/503, para no auto-bloquearse. No necesita Playwright.
4. **MercadoLibre** → borrar `scrape_mercadolibre()` + `get_ml_token()`. Quedarse con Playwright y **arreglar el bug de scroll** (`Execution context destroyed`): no hacer `page.evaluate` de scroll mientras hay una navegación pendiente; envolver en try o esperar `wait_for_load_state`.
5. **Properati + Roomix** → eliminar (0 resultados siempre, solo suman latencia y ruido).
6. **config.json** → mover los filtros (`barrios`, `precio_max`, `ambientes_min`, `m2_min`) desde el `.py`. Cargar en `main()` y propagarlos.
7. **seen_listings.json** → migrar de `set` a `dict {hash: iso_timestamp}` y **podar entradas > 45 días**. Mantener compat: si al cargar es una lista (formato viejo), convertir.
8. **GitHub Actions** → **eliminado.**

---

## Plan de implementación (para la próxima sesión)

> Sugerencia: arrancar con `writing-plans` para detallar esto en un plan ejecutable, luego `executing-plans`. Usar TDD donde aplique.

1. **Limpieza de código muerto**
   - Borrar `scrape_mercadolibre()` y `get_ml_token()`.
   - Borrar `scrape_properati()` y `scrape_roomix()`.
   - Actualizar la lista `scrapers` en `main()` → quedan: MercadoLibre (Playwright), ArgProp, ZonaProp.
   - Quitar imports/constantes que queden sin uso.
2. **Fix ML Playwright** — resolver `Execution context was destroyed` en el bloque de scroll (líneas ~641-647 del working tree). No scrollear durante navegación; o reintentar la card-wait.
3. **ZonaProp retry/backoff** — en `scrape_zonaprop()`, ante falta de marcador o 403/503, reintentar con backoff exponencial en vez de cortar de una. Bajar la frecuencia de requests.
4. **Externalizar filtros a `config.json`** — agregar claves `precio_max`, `ambientes_min`, `m2_min`, `barrios`. Leerlas en `main()`. Actualizar `config.json.example` y `GUIA_SETUP.md`.
5. **TTL en `seen_listings.json`** — `load_seen()`/`save_seen()` con dict `{hash: timestamp_iso}`, poda > 45 días, retrocompatibilidad con el formato lista.
6. **Windows Task Scheduler** — documentar en `GUIA_SETUP.md` el comando `schtasks` o los pasos GUI para correr 2×/día. Verificar que Playwright/Chromium estén instalados en la PC destino (`playwright install chromium`).
7. **Actualizar `GUIA_SETUP.md`** — Task Scheduler como método principal; quitar/marcar como histórica la sección de GitHub Actions; actualizar la tabla de confiabilidad por fuente con los hallazgos reales.

---

## Estado del repo al pausar (2026-06-16)

- **WIP de `rental_alert.py` commiteado como checkpoint** (eran ~937 líneas sin commitear vs HEAD; ahora preservadas y pusheadas). También `requirements.txt`, `config.json.example`, `seen_listings.json`.
- `.github/workflows/busqueda_diaria.yml` → **borrado**.
- `probe_zonaprop.py` → era un script de diagnóstico temporal; **borrado** (su resultado quedó arriba). `debug_zonaprop.py` queda (es del usuario).
- `config.json` → **NO** está en git (gitignored). En la otra compu hay que recrearlo desde `config.json.example` con el token y chat IDs reales.
- `.claude/` y `skills-lock.json` → tooling local, sin commitear a propósito.

---

## Cómo retomar en otra computadora

1. `git clone https://github.com/matias-denatale/alerta-alquiler.git`
2. `pip install -r requirements.txt` y `playwright install chromium`
3. Recrear `config.json` desde `config.json.example` (token de Telegram + chat IDs reales).
4. Abrir este doc (`docs/superpowers/specs/2026-06-16-bot-alquileres-mejoras-design.md`) y seguir el "Plan de implementación".
5. (Opcional) Verificar que ZonaProp sigue OK con una corrida de prueba antes de tocar nada.
