# 🏠 Alerta Alquiler CABA — Puesta en marcha en Windows (6 veces al día)

Estos archivos reemplazan/complementan tu repo `alerta-alquiler`. Los filtros ya
quedaron alineados a tus criterios actuales:

- **Precio máximo:** $1.500.000 (alquiler + expensas)
- **Ambientes mínimos:** 2
- **Departamentos:** solo si tienen **más de 70 m²** y patio/terraza/balcón
- **Barrios:** Boedo · Almagro · Parque Patricios · Balvanera · San Cristóbal · San Telmo · Parque Chacabuco
- PH y Casa entran sin exigencia de m² (además del filtro de precio y ambientes)

---

## Paso 0 — Poné estos archivos en la carpeta del repo
Copiá `rental_alert.py` (ya modificado) dentro de tu carpeta `alerta-alquiler`,
pisando el anterior. Copiá también `run_bot.bat`, `setup_windows.bat` e
`instalar_tarea_6x_dia.ps1` en esa misma carpeta.

## Paso 1 — Setup (una sola vez)
Doble clic en **`setup_windows.bat`**. Crea el entorno virtual, instala las
dependencias e instala Chromium para el scraper de MercadoLibre.
> Necesitás Python 3.10+ instalado (https://www.python.org/downloads/ — marcá
> "Add Python to PATH" al instalar).

## Paso 2 — Configurar Telegram
Si todavía no lo hiciste, seguí `GUIA_SETUP.md` del repo:
1. Creá el bot con **@BotFather** → te da el **token**.
2. Vos y tu novia le mandan `/start` al bot.
3. Completá el token en `get_chat_id.py`, corré `python get_chat_id.py` y copiá
   los dos `chat_id`.
4. Editá **`config.json`** con el token y los dos chat_ids.

## Paso 3 — Probar
Doble clic en **`run_bot.bat`**. Debería correr y, si hay novedades, mandarlas al
Telegram de los dos. La primera corrida manda todo lo que encuentra; las
siguientes solo lo nuevo (lleva historial en `seen_listings.json`).

## Paso 4 — Programar las 6 corridas diarias
1. Abrí PowerShell **en la carpeta del repo** (Shift + clic derecho → "Abrir
   ventana de PowerShell aquí").
2. Corré:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\instalar_tarea_6x_dia.ps1
   ```
3. Queda una tarea llamada **AlertaAlquilerCABA** que corre a las **08:00, 12:00,
   16:00, 18:00, 20:00 y 22:00**. Podés cambiar los horarios editando el `.ps1` (líneas `-At`).

Para probar la tarea ya mismo:
```powershell
Start-ScheduledTask -TaskName AlertaAlquilerCABA
```
Para verla o borrarla: abrí el **Programador de tareas** de Windows.

---

## ⚠️ Nota importante sobre fiabilidad
ZonaProp, ArgProp y MercadoLibre bloquean bastante el scraping automático. Desde
tu propia PC (IP residencial) funciona mucho mejor que desde un servidor, pero
igual puede haber corridas donde algún portal devuelva "bloqueado (403)". El bot
está preparado para eso: sigue con los demás portales y te avisa por Telegram si
uno quedó bloqueado. Si ves que un portal falla seguido, avisame y lo ajustamos.

## 💡 Recomendación clave
El scraper te avisa de lo que **ya se publicó**. Pero como vos mismo notaste, las
buenas se van el mismo día y muchas inmobiliarias arman lista de espera antes de
publicar. Por eso la otra pata —contactar inmobiliarias de forma recurrente— es
la que más chances te da. Ver la planilla de inmobiliarias que va aparte.
