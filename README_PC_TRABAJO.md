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
- `PRECIO_MAX = 1_500_000`  (alquiler + expensas)
- `AMBIENTES_MIN = 2`
- Departamentos: solo si superan **70 m²** (los `< 70` en el código) y tienen patio/terraza/balcón
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
- [ ] Repo clonado y filtros verificados (1.500.000 / 2 amb / 70 m²)
- [ ] venv + requirements + `playwright install chromium`
- [ ] `config.json` con token y 2 chat_ids
- [ ] `run_bot.bat` probado y llegó el mensaje a Telegram
- [ ] Tarea `AlertaAlquilerCABA` creada (09/14/19 hs) y probada con `Start-ScheduledTask`
