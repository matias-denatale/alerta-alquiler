# README — Poner el bot Alerta Alquiler a correr 3x/día (PC de trabajo)

> **Para el agente que reciba esto:** Matías quiere dejar operativo su bot de alertas
> de alquiler en ESTA PC (Windows), que se dispare **3 veces al día (09:00, 14:00 y
> 19:00)** y le mande las publicaciones nuevas por Telegram. Abajo está todo el paso
> a paso. El repo ya existe; los cambios de filtros ya fueron aplicados por Matías en
> otra máquina, pero incluimos los valores para verificar.

## Contexto del proyecto
Bot en Python que scrapea ZonaProp, ArgProp, MercadoLibre (con Playwright), Properati
y Roomix, filtra por criterios y avisa por Telegram lo nuevo (lleva historial en
`seen_listings.json`).

**Criterios de búsqueda (deben estar así en `rental_alert.py`):**
- `PRECIO_MAX = 1_500_000` / `PRECIO_MIN = 700_000` (alquiler + expensas)
- `AMBIENTES_MIN = 2`
- `M2_MIN_DEPTO = 70` (departamentos) / `M2_MIN = 50` (PH y casas) — si no se puede confirmar el área, se descarta (`area_ok()`)
- Departamentos además requieren patio/terraza/balcón
- Barrios: Boedo, Almagro, Parque Patricios, Balvanera, San Cristóbal, San Telmo, Parque Chacabuco

## Requisitos previos
- Windows 10/11
- Python 3.10+ instalado y en el PATH (https://www.python.org/downloads/ → marcar "Add Python to PATH")
- El token de Telegram y los 2 chat_ids (de Matías y su novia). Si no los tiene a mano,
  se regeneran con `@BotFather` y `get_chat_id.py` (ver GUIA_SETUP.md del repo).

## Paso 1 — Clonar el repo
```powershell
cd $HOME\Documents
git clone https://github.com/matias-denatale/alerta-alquiler.git
cd alerta-alquiler
```
> Si Matías ya commiteó los archivos actualizados, el repo ya trae los filtros correctos
> y los scripts `setup_windows.bat`, `run_bot.bat` e `instalar_tarea_3x_dia.ps1`.
> Si NO están, copiar a esta carpeta los archivos que Matías trae aparte
> (`rental_alert.py`, `setup_windows.bat`, `run_bot.bat`, `instalar_tarea_3x_dia.ps1`)
> y verificar los 3 valores de filtros de arriba.

## Paso 2 — Setup del entorno (una vez)
Ejecutar `setup_windows.bat` (doble clic) o:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

## Paso 3 — Configurar Telegram
```powershell
copy config.json.example config.json
```
Editar `config.json` y completar:
```json
{
  "telegram_token": "EL_TOKEN_DE_BOTFATHER",
  "telegram_chat_ids": ["CHAT_ID_MATI", "CHAT_ID_PILI"]
}
```
(Los campos de MercadoLibre son opcionales; se pueden dejar como están.)

## Paso 4 — Probar
```powershell
.\run_bot.bat
```
Debería correr y, si hay novedades, mandarlas al Telegram de ambos. La 1ª corrida manda
todo lo que encuentra; las siguientes, solo lo nuevo.

## Paso 5 — Programar las 3 corridas diarias
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\instalar_tarea_3x_dia.ps1
```
Esto registra la tarea de Windows **AlertaAlquilerCABA** que corre a las **09:00, 14:00
y 19:00**. Para probarla al toque:
```powershell
Start-ScheduledTask -TaskName AlertaAlquilerCABA
```
Para ver/editar/borrar: abrir el **Programador de tareas** de Windows.

## Notas importantes
- **Bloqueos**: ZonaProp/ArgProp/ML a veces devuelven 403 (anti-scraping). Desde una PC
  con IP residencial anda bastante bien; el bot sigue con los otros portales y avisa por
  Telegram si uno quedó bloqueado. Si un portal falla siempre, avisarle a Matías.
- **La PC tiene que estar prendida** a esos horarios. La tarea está configurada con
  `-StartWhenAvailable`, así que si estuvo apagada, corre al prenderla.
- **Historial**: no borrar `seen_listings.json`, es lo que evita mandar repetidos.
- Si es una PC de trabajo con restricciones (firewall corporativo, sin permisos de
  admin, sin poder instalar Python), avisarle a Matías: puede que convenga correrlo en
  la PC personal o en otra máquina.

## Checklist rápido para el agente
- [ ] Python 3.10+ disponible
- [ ] Repo clonado y filtros verificados (700.000-1.500.000 / 2 amb / 70 m² depto, 50 m² PH-casa)
- [ ] venv + requirements + `playwright install chromium`
- [ ] `config.json` con token y 2 chat_ids
- [ ] `run_bot.bat` probado y llegó el mensaje a Telegram
- [ ] Tarea `AlertaAlquilerCABA` creada (09/14/19 hs) y probada con `Start-ScheduledTask`

---

# PARTE B — Tarea programada del "plan de contacto" (Claude) en esta PC

> Además del bot, Matías quiere que en esta misma PC (que está prendida 24/7) corra
> la **tarea diaria de las 6 am** que arma el plan de a qué inmobiliarias contactar,
> leyendo una base de Notion. Esto NO es un script de Python: corre dentro de la app
> de Claude (Cowork).

## Requisitos
1. **App de Claude (desktop) instalada** en esta PC e iniciada sesión con la cuenta de Matías.
2. **Conector de Notion autorizado** en Claude, con permiso de **lectura y escritura**
   (Configuración → Conectores). Es el mismo Notion donde está la base
   "Inmobiliarias CABA — Seguimiento alquiler".

## Cómo crear la tarea
En una sesión de Cowork en esta PC, pedirle al agente que cree una tarea programada con
estos datos exactos:

- **taskId:** `contacto-inmobiliarias-diario`
- **Schedule (cron, hora local):** `0 6 * * 1-5`  (lunes a viernes, 6 am)
- **Descripción:** Plan diario de inmobiliarias a contactar, usando la base de Notion.
- **Prompt (pegar tal cual):**

```
Sos el asistente de Matías para su búsqueda de alquiler en CABA (ingreso 1 de septiembre de 2026). Cada mañana laboral armás el plan de a qué inmobiliarias contactar hoy, repartido entre Matías y su novia Pili, que se turnan para llamar.

FUENTE DE DATOS (Notion):
Base "Inmobiliarias CABA — Seguimiento alquiler", data source ID: 6140f5cf-7297-47ee-b3de-ad79a3bfad45.
Usá la herramienta de Notion para consultar/leer esa base (notion-fetch con la id collection://6140f5cf-7297-47ee-b3de-ad79a3bfad45 para ver el esquema, y notion-query-data-sources para filtrar).

OBJETIVO GENERAL:
Llegar al 2026-08-01 habiendo hecho un primer contacto (Estado ya no "No contactada") con TODAS las inmobiliarias que hoy figuran como "No contactada". Cada corrida hay que recalcular el ritmo: cuántas quedan pendientes de primer contacto y cuántos días hábiles (lu-vi) quedan hasta el 2026-08-01, incluyendo hoy.

QUÉ HACER:
1. Leé todas las fichas. Cada una tiene: Inmobiliaria, Barrio, Direccion, Telefono, WhatsApp, Web / Email, Prioridad, Estado, Quien contacto, Ultima fecha contacto, Proximo contacto, Notas.
2. Separá dos grupos:
   a) PRIMER CONTACTO: Estado = "No contactada".
   b) RECONTACTO: "Proximo contacto" es hoy o anterior a hoy, Estado distinto de "Descartada".
3. Calculá la meta de HOY para primer contacto = techo(cantidad de "No contactada" que quedan / días hábiles restantes hasta el 2026-08-01). Piso de 12 en total (6 y 6) mientras haya al menos 12 "No contactada" pendientes; si quedan menos de 12, repartilas todas hoy. Los recontactos vencidos van aparte, no compiten por ese cupo — sumalos a la lista del día y repartilos también entre los dos.
4. Priorizá Prioridad "Alta" dentro de cada grupo y rotá barrios para no cargar siempre el mismo.
5. Dividí la lista de hoy en dos mitades lo más parejas posible (aprox. 6 y 6), alternando por prioridad/barrio para que a ambos les toque una mezcla similar: Grupo Matías y Grupo Pili.
6. Presentá DOS bloques bien separados:

   BLOQUE 1 (para Matías):
   📞 Tu plan de hoy — [fecha]
   Para cada inmobiliaria: nombre — Barrio — Teléfono / WhatsApp — Web/Email — (nota previa si la hay).

   BLOQUE 2 (reporte para Pili — texto plano, listo para copiar y pegar tal cual en WhatsApp, sin necesitar edición):
   📞 Plan de hoy para vos, Pili — [fecha]
   Para cada inmobiliaria: nombre — Barrio — Teléfono / WhatsApp — Web/Email — (nota previa si la hay).

   Al final de AMBOS bloques, recordá el objetivo: PH/casa/depto con patio o terraza, min 2 amb (depto >70 m²), hasta $1.500.000/mes, ingreso 1/9. Y el tip: preguntar siempre "¿tienen algo por entrar que todavía no publicaron?".

7. Después de los dos bloques, agregá una línea de seguimiento de ritmo: cuántas "No contactada" quedan sin cubrir después de hoy, y si el ritmo actual alcanza para terminar antes del 2026-08-01 (si no alcanza, avisá que hay que subir la cantidad diaria).
8. Cerrá diciéndole a Matías que, cuando los dos terminen de llamar, te avise a quiénes contactaron y qué les dijeron, y que vos actualizás la base: poné Estado="Contactada" (o el que corresponda), "Ultima fecha contacto"=hoy, "Quien contacto"=Mati/Novia/Los dos, "Proximo contacto"=hoy+7 días (si quedó en "nada por ahora"), y agregá la respuesta en Notas.

Si no encontrás nada pendiente (todo contactado y sin recontactos vencidos), decíselo y felicitalo, y sugerí revisar las que están "En seguimiento".

Escribí en español rioplatense, tono cercano y directo.
```

## Importante
- Después de crearla, tocar **"Run now"** una vez para pre-aprobar los permisos de Notion,
  así las corridas automáticas no se frenan pidiendo permiso.
- **Evitar duplicados:** si esta tarea queda corriendo en la PC laboral, hay que
  **desactivar o borrar** la misma tarea en la PC personal de Matías (donde se creó
  primero), para que no corran las dos y no dupliquen las actualizaciones en Notion.
