# 🏠 Guía de Setup — Alerta de Alquileres CABA

## Requisitos

- Python 3.10 o superior
- Cuenta de Telegram (vos y tu novia)

---

## Paso 1 — Instalar dependencias

```bash
pip install -r requirements.txt
```

---

## Paso 2 — Crear el bot de Telegram

1. Abrí Telegram y buscá **`@BotFather`**
2. Escribí `/newbot`
3. Elegí un nombre para el bot (ej: `Alerta Depto`)
4. Elegí un username que termine en `bot` (ej: `alerta_depto_mati_bot`)
5. BotFather te va a dar un **token** como este:
   ```
   123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
   ```
6. **Guardalo**, lo necesitás en el siguiente paso.

---

## Paso 3 — Obtener los Chat IDs

1. Buscá tu bot por username en Telegram y tocá **Start** (o escribí `/start`)
2. Que tu novia haga lo mismo desde su cuenta
3. Completá tu token en `get_chat_id.py` y ejecutalo:

```bash
python get_chat_id.py
```

Va a mostrar algo así:
```
  👤 Matías              → chat_id: "111222333"
  👤 [nombre novia]      → chat_id: "444555666"
```

---

## Paso 4 — Crear config.json

Copiá el archivo de ejemplo:

```bash
# En Mac/Linux:
cp config.json.example config.json

# En Windows:
copy config.json.example config.json
```

Editá `config.json` y completá con tu token y los chat IDs:

```json
{
    "telegram_token": "123456789:TU_TOKEN_REAL",
    "telegram_chat_ids": [
        "111222333",
        "444555666"
    ]
}
```

---

## Paso 5 — Probar

```bash
python rental_alert.py
```

Si todo funciona, van a recibir notificaciones en Telegram.
El script también crea `rental_alert.log` con el detalle de cada ejecución.

---

## Paso 6 — Automatizar (ejecutar todos los días)

### Opción A: Mac / Linux — Cron

1. Abrí el editor de cron:
   ```bash
   crontab -e
   ```

2. Agregá esta línea para ejecutarlo a las 9am y 6pm todos los días:
   ```
   0 9,18 * * * /usr/bin/python3 /ruta/completa/rental_alert.py >> /ruta/completa/cron.log 2>&1
   ```

   Para saber las rutas:
   ```bash
   which python3          # ruta de Python
   pwd                    # ruta actual (ejecutá desde la carpeta del script)
   ```

### Opción B: Windows — Programador de tareas

1. Buscá "Programador de tareas" en el menú inicio
2. → "Crear tarea básica"
3. Nombre: `Alerta Alquileres`
4. Desencadenador: **Diariamente**, a las 09:00
5. Acción: **Iniciar un programa**
   - Programa: `python` (o la ruta completa: `C:\Python312\python.exe`)
   - Argumentos: `rental_alert.py`
   - Iniciar en: la carpeta donde guardaste el script (ej: `C:\Users\Mati\alerta_alquiler\`)
6. Repetir la tarea para que corra también a las 18:00 (en la pestaña "Condiciones/Configuración")

### Opción C: GitHub Actions — sin necesidad de tener la PC prendida ✅

Esta es la opción más robusta si querés que corra aunque tu computadora esté apagada.

1. Creá un repositorio en GitHub (puede ser privado)
2. Subí todos los archivos excepto `config.json` (¡nunca subas el token!)
3. En GitHub → Settings → Secrets and variables → Actions, creá estos secrets:
   - `TELEGRAM_TOKEN` → tu token
   - `TELEGRAM_CHAT_IDS` → `["111222333","444555666"]`

4. Creá el archivo `.github/workflows/busqueda_diaria.yml` con este contenido:

```yaml
name: Búsqueda diaria de alquileres

on:
  schedule:
    # 12:00 UTC = 09:00 AR (UTC-3) | 21:00 UTC = 18:00 AR
    - cron: '0 12,21 * * *'
  workflow_dispatch:  # permite correrlo manualmente desde GitHub

jobs:
  buscar:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Instalar dependencias
        run: pip install -r requirements.txt

      - name: Crear config.json desde secrets
        run: |
          echo '{
            "telegram_token": "${{ secrets.TELEGRAM_TOKEN }}",
            "telegram_chat_ids": ${{ secrets.TELEGRAM_CHAT_IDS }}
          }' > config.json

      - name: Ejecutar búsqueda
        run: python rental_alert.py
```

**Nota sobre duplicados con GitHub Actions:** el archivo `seen_listings.json` no persiste entre runs en GitHub Actions, así que cada día puede re-enviar listados ya vistos. Opciones:
- Ignorarlo si no molesta recibir repeticiones ocasionales.
- Usar GitHub Actions artifacts para persistir el archivo entre runs (más complejo).

---

## Notas sobre cada sitio

| Sitio | Método | Confiabilidad |
|---|---|---|
| **MercadoLibre** | API oficial pública | ⭐⭐⭐⭐⭐ Muy alta |
| **ArgProp** | HTML scraping (BS4) | ⭐⭐⭐⭐ Alta |
| **ZonaProp** | JSON embebido (`__PRELOADED_STATE__`) | ⭐⭐⭐ Media (puede ser bloqueado por Cloudflare) |
| **Roomix** | HTML scraping básico | ⭐⭐ Baja (plataforma nueva, estructura puede cambiar) |

Si ZonaProp empieza a fallar consistentemente, podés deshabilitar ese scraper comentando la línea en el `main()` de `rental_alert.py`.

---

## Ajustar los filtros

Todos los filtros están al inicio de `rental_alert.py`, fáciles de cambiar:

```python
BARRIOS_OBJETIVO = {"boedo", "almagro", ...}  # agregar/quitar barrios
PRECIO_MAX    = 1_500_000   # máximo en ARS (alquiler + expensas)
PRECIO_MIN    = 700_000     # mínimo en ARS, descarta publicaciones de baja calidad
AMBIENTES_MIN = 2           # mínimo de ambientes
M2_MIN_DEPTO  = 70          # piso de m² para departamentos
M2_MIN        = 50          # piso de m² para PH y casas
```
