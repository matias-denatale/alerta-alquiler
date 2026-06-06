#!/usr/bin/env python3
"""
🏠 Alerta de Alquileres CABA
Busca propiedades en ZonaProp, ArgProp, MercadoLibre y Roomix
y envía alertas por Telegram cuando aparecen publicaciones nuevas.

Uso:
    python rental_alert.py

Configurar config.json antes de ejecutar (ver GUIA_SETUP.md).
"""

import json
import re
import time
import logging
import hashlib
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# Archivos
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
CONFIG    = BASE_DIR / "config.json"
SEEN_FILE = BASE_DIR / "seen_listings.json"
LOG_FILE  = BASE_DIR / "rental_alert.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Filtros de búsqueda — ajustá acá si cambiás los criterios
# ─────────────────────────────────────────────────────────────────────────────
BARRIOS_OBJETIVO = {
    "boedo",
    "almagro",
    "parque patricios",
    "balvanera",
    "san cristóbal",
    "san cristobal",
    "san telmo",
    "parque chacabuco",
}

PRECIO_MAX    = 1_400_000   # ARS/mes máximo (alquiler + expensas)
AMBIENTES_MIN = 3

# Lista de avisos de scrapers para enviar por Telegram al final de cada run
_SCRAPER_WARNINGS: list[str] = []

# ─────────────────────────────────────────────────────────────────────────────
# HTTP session — simula un browser para evitar bloqueos básicos
# ─────────────────────────────────────────────────────────────────────────────
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(list(seen)), encoding="utf-8")


def listing_key(url: str) -> str:
    """Hash único por URL para detectar duplicados."""
    return hashlib.md5(url.encode()).hexdigest()


def parse_price(text: str) -> int | None:
    """'$ 1.200.000' o '1200000' → 1200000"""
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def barrio_match(name: str) -> bool:
    return (name or "").lower().strip() in BARRIOS_OBJETIVO


def format_listing(listing: dict) -> str:
    emoji_map = {"ph": "🏡", "casa": "🏠", "departamento": "🏢"}
    emoji = emoji_map.get((listing.get("type") or "").lower(), "🏠")

    lines = [f"{emoji} <b>{listing['title']}</b>"]
    if listing.get("price"):
        lines.append(f"💰 Alquiler: {listing['price']}")
    if listing.get("expenses"):
        lines.append(f"📦 Expensas: {listing['expenses']}")
    if listing.get("rooms"):
        lines.append(f"🚪 {listing['rooms']} ambientes")
    if listing.get("bedrooms"):
        lines.append(f"🛏 {listing['bedrooms']} dormitorios")
    if listing.get("size"):
        lines.append(f"📐 {listing['size']}")
    if listing.get("neighborhood"):
        lines.append(f"📍 {listing['neighborhood']}")
    if listing.get("features"):
        lines.append(f"✨ {', '.join(listing['features'])}")

    lines.append(f"\n🔗 <a href=\"{listing['url']}\">Ver publicación →</a>")
    lines.append(f"📡 {listing.get('source', '?')} · {datetime.now().strftime('%d/%m %H:%M')}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────
def send_telegram(token: str, chat_ids: list, text: str, preview_url: str = ""):
    """
    Envía un mensaje por Telegram.
    Si se pasa preview_url, fuerza la previsualización de esa URL específica
    (muestra la foto de la propiedad, título, descripción — como cuando mandás
    un link a mano en Telegram).
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in chat_ids:
        try:
            payload = {
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": "HTML",
            }
            if preview_url:
                # Bot API 7.0+: especifica exactamente qué URL previsualizar
                payload["link_preview_options"] = {
                    "url":                preview_url,
                    "prefer_large_media": True,   # foto grande arriba del mensaje
                }
            else:
                payload["disable_web_page_preview"] = True

            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
            log.info(f"✅ Telegram → {chat_id}")
        except Exception as e:
            log.error(f"❌ Telegram error → {chat_id}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER: ArgProp
# Referencia: github.com/LeoArtaza/Scraper-Argenprop
# ─────────────────────────────────────────────────────────────────────────────
def scrape_argenprop(pages: int = 20) -> list[dict]:
    """
    Scraper para argenprop.com.
    Busca toda la Capital Federal por tipo y filtra por barrio en Python.
    20 páginas × 3 tipos × ~20 cards = ~1200 listings procesados.
    """
    listings = []
    tipos = ["departamento", "ph", "casa"]

    for tipo in tipos:
        for page in range(1, pages + 1):
            url = (
                f"https://www.argenprop.com/{tipo}-alquiler-localidad-capital-federal"
                f"-orden-masnuevos-pagina-{page}"
            )
            try:
                r = SESSION.get(url, timeout=30)
                if r.status_code == 404:
                    break
                r.raise_for_status()

                soup = BeautifulSoup(r.text, "html.parser")
                # Las cards usan exactamente la clase "listing__item" (no subclases)
                cards = soup.find_all(
                    "div", class_=lambda x: x == "listing__item" if x else False
                )

                if not cards:
                    break  # sin más páginas

                for card in cards:
                    try:
                        # ── Precio ────────────────────────────────────────────
                        price_el    = card.find(class_="card__price")
                        currency_el = card.find(class_="card__currency")
                        currency    = (currency_el.text.strip() if currency_el else "").upper()

                        # Solo ARS; saltear USD u otras monedas
                        if currency and currency not in ("$", "ARS", ""):
                            continue

                        price_text = price_el.text.strip() if price_el else ""
                        price_num  = parse_price(price_text)

                        if price_num and price_num > PRECIO_MAX:
                            continue  # ya supera el límite sin expensas

                        # ── Expensas ──────────────────────────────────────────
                        exp_el   = card.find(class_="card__expenses")
                        expenses = exp_el.text.strip() if exp_el else ""
                        exp_num  = parse_price(expenses)

                        if price_num and exp_num and (price_num + exp_num) > PRECIO_MAX:
                            continue

                        # ── Barrio ────────────────────────────────────────────
                        loc_el       = card.find(class_="card__title--primary")
                        location_txt = (loc_el.text.strip() if loc_el else "").lower()
                        barrio = next(
                            (b for b in BARRIOS_OBJETIVO if b in location_txt), ""
                        )
                        if not barrio:
                            continue

                        # ── Título y dirección ────────────────────────────────
                        title_el = card.find(class_="card__title")
                        title    = title_el.text.strip() if title_el else ""
                        addr_el  = card.find(class_="card__address")
                        address  = addr_el.text.strip() if addr_el else ""

                        # ── Superficie y dormitorios ──────────────────────────
                        sup_el = card.find(class_="icono-superficie_cubierta")
                        size   = sup_el.find_parent().find("span").text.strip() if sup_el else ""
                        # Filtrar departamentos < 80 m²
                        size_num = parse_price(size)
                        if tipo == "departamento" and size_num and size_num < 80:
                            continue

                        dorm_el  = card.find(class_="icono-cantidad_dormitorios")
                        bedrooms = dorm_el.find_parent().find("span").text.strip() if dorm_el else ""

                        # ── Texto completo para buscar features ───────────────
                        desc_el   = card.find(class_="card__info")
                        desc      = desc_el.text.lower() if desc_el else ""
                        full_text = f"{title} {desc} {address}".lower()

                        # Saltar si tiene cochera/garage (salvo que diga "sin cochera")
                        if any(kw in full_text for kw in ("cochera", "garage")):
                            if not any(kw in full_text for kw in ("sin cochera", "sin garage")):
                                continue

                        outdoor_kws = ("patio", "terraza", "jardín", "jardin", "balcón", "balcon")
                        features = []
                        for kw in outdoor_kws:
                            if kw in full_text:
                                features.append(
                                    kw.replace("jardin", "jardín").replace("balcon", "balcón").capitalize()
                                )

                        # Departamentos requieren patio O terraza
                        if tipo == "departamento" and not features:
                            continue

                        # ── Link ──────────────────────────────────────────────
                        link_el = card.find("a", href=True)
                        href    = link_el["href"] if link_el else ""
                        link    = f"https://www.argenprop.com{href}" if href.startswith("/") else href
                        if not link:
                            continue

                        listings.append({
                            "title":        title or address or f"{tipo.upper()} en {barrio}",
                            "price":        price_text,
                            "expenses":     expenses,
                            "rooms":        None,
                            "bedrooms":     bedrooms,
                            "size":         f"{size} m²" if size else "",
                            "neighborhood": barrio.title().replace("San Cristobal", "San Cristóbal"),
                            "type":         tipo,
                            "features":     list(set(features)),
                            "url":          link,
                            "source":       "ArgProp",
                        })

                    except Exception as e:
                        log.debug(f"ArgProp card error: {e}")

                time.sleep(1)

            except Exception as e:
                log.error(f"ArgProp [{tipo}] p{page}: {e}")
                break

    log.info(f"ArgProp: {len(listings)} propiedades encontradas")
    return listings


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER: ZonaProp
# ─────────────────────────────────────────────────────────────────────────────
def scrape_zonaprop(pages: int = 3) -> list[dict]:
    """
    ZonaProp embebe los datos de los listados en window.__PRELOADED_STATE__
    dentro de un <script> en el HTML. Parsear ese JSON es más robusto que
    scraping de elementos HTML.

    NOTA: ZonaProp usa Cloudflare. Si el sitio devuelve error 403/503, el
    script lo loguea y sigue con el resto de sitios. No es un error fatal.
    """
    listings = []

    neighborhoods_slug = (
        "boedo-almagro-parque-patricios-balvanera-"
        "san-cristobal-san-telmo-parque-chacabuco"
    )

    for page in range(1, pages + 1):
        page_suffix = f"-pagina-{page}" if page > 1 else ""
        url = (
            f"https://www.zonaprop.com.ar/casas-departamentos-ph-alquiler-"
            f"{neighborhoods_slug}-3-ambientes-mas"
            f"-orden-publicado-descendente{page_suffix}.html"
        )

        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code in (403, 503):
                msg = f"⚠️ ZonaProp bloqueado por Cloudflare (HTTP {r.status_code}) — se saltó esta búsqueda."
                log.warning(msg)
                _SCRAPER_WARNINGS.append(msg)
                break
            r.raise_for_status()

            soup      = BeautifulSoup(r.text, "html.parser")
            preloaded = None

            for script in soup.find_all("script"):
                content = script.string or ""
                if "__PRELOADED_STATE__" not in content:
                    continue
                # raw_decode para exactamente donde termina el JSON,
                # sin importar qué haya después (evita "Extra data" error)
                marker = "window.__PRELOADED_STATE__ = "
                idx = content.find(marker)
                if idx >= 0:
                    json_start = idx + len(marker)
                    try:
                        preloaded, _ = json.JSONDecoder().raw_decode(content, json_start)
                    except json.JSONDecodeError as je:
                        log.warning(f"ZonaProp: no se pudo parsear JSON en página {page}: {je}")
                break

            if not preloaded:
                log.warning(f"ZonaProp: no se encontró __PRELOADED_STATE__ en página {page}")
                break

            postings = preloaded.get("listStore", {}).get("listPostings", [])
            if not postings:
                log.info(f"ZonaProp: fin de páginas en {page}")
                break

            # Debug: entender por qué se filtran los listados
            n_usd = n_price = n_rooms = n_area = n_outdoor = n_no_url = n_exc = 0

            for post in postings:
                try:
                    # ── Precio ────────────────────────────────────────────────
                    # priceOperationTypes es una LISTA (plural), no dict (singular)
                    price_ops = post.get("priceOperationTypes") or []
                    price_num, currency = 0, "ARS"
                    for op in price_ops:
                        if not isinstance(op, dict):
                            continue
                        for p in (op.get("prices") or []):
                            if not isinstance(p, dict):
                                continue
                            price_num = p.get("amount") or p.get("price") or 0
                            currency  = p.get("currency", "ARS") or "ARS"
                            break
                        if price_num:
                            break

                    if currency not in ("ARS", "$"):
                        n_usd += 1
                        continue

                    expenses_num = post.get("expenses") or 0
                    if isinstance(expenses_num, dict):
                        expenses_num = expenses_num.get("amount", 0) or 0

                    if price_num and (price_num + expenses_num) > PRECIO_MAX:
                        n_price += 1
                        continue

                    # ── Ambientes (en mainFeatures o generalFeatures) ──────────
                    rooms = 0
                    for feat_group in ("mainFeatures", "generalFeatures", "features"):
                        for feat in (post.get(feat_group) or []):
                            if not isinstance(feat, dict):
                                continue
                            label = (feat.get("label") or feat.get("type") or "").lower()
                            if "ambiente" in label or "dormitorio" in label:
                                val = feat.get("value") or feat.get("text") or ""
                                try:
                                    rooms = int(str(val).split()[0])
                                except Exception:
                                    pass
                                break
                        if rooms:
                            break
                    if rooms and rooms < AMBIENTES_MIN:
                        n_rooms += 1
                        continue

                    # ── Tipo de propiedad ─────────────────────────────────────
                    prop_type = (
                        post.get("realEstateType", {}).get("name", "") or ""
                    ).lower()

                    # ── Superficie ────────────────────────────────────────────
                    covered = post.get("coveredArea") or 0
                    total   = post.get("totalArea") or 0
                    area    = total or covered
                    size    = f"{area} m²" if area else ""

                    # Departamentos: mínimo 80 m²
                    if prop_type == "departamento" and covered and covered < 80:
                        n_area += 1
                        continue

                    # ── Barrio ────────────────────────────────────────────────
                    location = post.get("postingLocation", {}) or {}
                    barrio   = (
                        (location.get("neighbourhood") or {}).get("name", "")
                        or (location.get("city") or {}).get("name", "")
                    )

                    # ── Título y URL ──────────────────────────────────────────
                    address = post.get("address", "") or ""
                    title   = post.get("title", "") or address or f"{prop_type} en {barrio}"

                    # ZonaProp usa distintos keys según la versión del JSON
                    url_suffix = (
                        post.get("url")
                        or post.get("postingUrl")
                        or post.get("slug")
                        or post.get("link")
                        or ""
                    )
                    # Fallback: construir desde postingId
                    if not url_suffix:
                        pid = post.get("postingId") or post.get("id") or ""
                        if pid:
                            url_suffix = f"/propiedades/{pid}.html"

                    full_url = (
                        f"https://www.zonaprop.com.ar{url_suffix}"
                        if url_suffix and url_suffix.startswith("/")
                        else url_suffix or ""
                    )
                    if not full_url:
                        n_no_url += 1
                        continue

                    # ── Features ──────────────────────────────────────────────
                    highlighted = post.get("highlightedFeatures") or []
                    feat_labels = " ".join(f.get("label", "") for f in highlighted)
                    full_text   = f"{title} {feat_labels}".lower()

                    # Sin cochera
                    if any(kw in full_text for kw in ("cochera", "garage")):
                        if not any(kw in full_text for kw in ("sin cochera", "sin garage")):
                            if any(
                                "cochera" in (f.get("label", "")).lower()
                                for f in highlighted
                            ):
                                continue

                    outdoor_kws = ("patio", "terraza", "jardín", "jardin", "balcón", "balcon")
                    features = []
                    for kw in outdoor_kws:
                        if kw in full_text:
                            features.append(
                                kw.replace("jardin", "jardín").replace("balcon", "balcón").capitalize()
                            )

                    # Departamentos requieren patio O terraza
                    if prop_type == "departamento" and not features:
                        n_outdoor += 1
                        continue

                    listings.append({
                        "title":        title,
                        "price":        f"$ {price_num:,}".replace(",", ".") if price_num else "",
                        "expenses":     f"$ {expenses_num:,}".replace(",", ".") if expenses_num else "",
                        "rooms":        str(rooms) if rooms else "",
                        "size":         size,
                        "neighborhood": barrio,
                        "type":         prop_type,
                        "features":     list(set(features)),
                        "url":          full_url,
                        "source":       "ZonaProp",
                    })

                except Exception as e:
                    log.warning(f"ZonaProp posting error: {e}")
                    n_exc += 1

            log.info(
                f"ZonaProp p{page}: {len(postings)} raw → "
                f"USD={n_usd} precio={n_price} ambientes={n_rooms} m²={n_area} "
                f"sin-outdoor={n_outdoor} sin-url={n_no_url} excep={n_exc}"
            )
            time.sleep(2)

        except Exception as e:
            log.error(f"ZonaProp página {page}: {e}")
            break

    log.info(f"ZonaProp: {len(listings)} propiedades encontradas")
    return listings


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER: MercadoLibre
# El sitio de ML es client-side rendered (React/Next.js) → requests no ve
# las cards. Usamos la API pública JSON de ML directamente.
# Endpoint: api.mercadolibre.com/sites/MLA/search
# ─────────────────────────────────────────────────────────────────────────────
def scrape_mercadolibre() -> list[dict]:
    """
    Usa la API pública de MercadoLibre (JSON) para buscar inmuebles en CABA.
    Hace una búsqueda de texto por barrio + tipo para encontrar alquileres,
    luego filtra precio, cochera y espacios exteriores en Python.
    """
    listings  = []
    seen_urls: set[str] = set()
    outdoor_kws = ("patio", "terraza", "jardín", "jardin", "balcón", "balcon")

    # Barrios únicos (cristóbal y cristobal son el mismo, dejamos el con tilde)
    barrios   = sorted(BARRIOS_OBJETIVO - {"san cristobal"})
    tipos_cfg = [
        ("departamentos", "departamento"),
        ("ph",            "ph"),
        ("casas",         "casa"),
    ]

    for tipo_slug, tipo_nombre in tipos_cfg:
        for barrio in barrios:
            # listado.mercadolibre.com.ar es la versión server-rendered de ML Argentina
            # (más scrappeable que inmuebles.mercadolibre.com.ar que es Next.js/React)
            barrio_slug = barrio.replace(" ", "-").replace("ó", "o").replace("é", "e")
            url = (
                f"https://listado.mercadolibre.com.ar/inmuebles/"
                f"{tipo_slug}/alquiler/{barrio_slug}-capital-federal/"
            )
            try:
                r = SESSION.get(url, timeout=20)
                if not r.ok:
                    log.warning(f"ML [{tipo_slug}/{barrio}]: HTTP {r.status_code}")
                    time.sleep(0.5)
                    continue

                soup  = BeautifulSoup(r.text, "html.parser")

                # Detectar si la página es JS-rendered (sin contenido real)
                cards = soup.select(
                    "li.ui-search-layout__item, "
                    ".andes-card, "
                    "[class*='ui-search-result']"
                )
                if not cards:
                    # Intentar JSON embebido en __NEXT_DATA__ como fallback
                    script_el = soup.find("script", id="__NEXT_DATA__")
                    if script_el:
                        try:
                            nd    = json.loads(script_el.string or "")
                            items = (
                                nd.get("props", {}).get("pageProps", {})
                                  .get("initialState", {})
                                  .get("results", [])
                            )
                            for item in items:
                                price    = item.get("price") or 0
                                currency = item.get("currency_id", "ARS")
                                title    = item.get("title", "")
                                link     = item.get("permalink", "")
                                if not link or link in seen_urls:
                                    continue
                                if currency != "ARS" or price > PRECIO_MAX:
                                    continue
                                title_lower = title.lower()
                                if any(kw in title_lower for kw in ("cochera", "garage")) and \
                                   not any(kw in title_lower for kw in ("sin cochera", "sin garage")):
                                    continue
                                features = [
                                    kw.replace("jardin", "jardín").replace("balcon", "balcón").capitalize()
                                    for kw in outdoor_kws if kw in title_lower
                                ]
                                if tipo_nombre == "departamento" and not features:
                                    continue
                                seen_urls.add(link)
                                listings.append({
                                    "title":        title,
                                    "price":        f"$ {int(price):,}".replace(",", "."),
                                    "neighborhood": barrio.title().replace("San Cristobal", "San Cristóbal"),
                                    "type":         tipo_nombre,
                                    "features":     features,
                                    "url":          link,
                                    "source":       "MercadoLibre",
                                })
                                seen_urls.add(link)
                        except Exception as e:
                            log.debug(f"ML __NEXT_DATA__ [{tipo_slug}/{barrio}]: {e}")
                    else:
                        log.warning(f"ML [{tipo_slug}/{barrio}]: página sin cards ni __NEXT_DATA__ (JS-rendered?)")
                    time.sleep(0.5)
                    continue

                for card in cards:
                    try:
                        title_el = card.select_one(
                            ".poly-component__title, .ui-search-item__title, "
                            "[class*='title-redesign'], h2, h3"
                        )
                        title = title_el.get_text(strip=True) if title_el else ""

                        price_el = card.select_one(
                            ".andes-money-amount__fraction, "
                            "[class*='price__fraction'], [class*='price-tag-fraction']"
                        )
                        price_text = price_el.get_text(strip=True).replace(".", "") if price_el else ""
                        price_num  = parse_price(price_text)

                        # Moneda — si el elemento de moneda dice USD, saltear
                        curr_el  = card.select_one(
                            ".andes-money-amount__currency-symbol, "
                            "[class*='price__symbol'], [class*='price-tag-symbol']"
                        )
                        curr_txt = (curr_el.get_text(strip=True) if curr_el else "").upper()
                        if curr_txt and curr_txt not in ("$", "ARS", ""):
                            continue

                        if price_num and price_num > PRECIO_MAX:
                            continue

                        link_el = card.select_one("a[href]")
                        link    = (link_el["href"] if link_el else "").split("?")[0]
                        if not link or link in seen_urls:
                            continue

                        title_lower = title.lower()
                        if any(kw in title_lower for kw in ("cochera", "garage")) and \
                           not any(kw in title_lower for kw in ("sin cochera", "sin garage")):
                            continue

                        features = [
                            kw.replace("jardin", "jardín").replace("balcon", "balcón").capitalize()
                            for kw in outdoor_kws if kw in title_lower
                        ]
                        if tipo_nombre == "departamento" and not features:
                            continue

                        seen_urls.add(link)
                        listings.append({
                            "title":        title or f"{tipo_nombre} en {barrio.title()}",
                            "price":        price_text,
                            "neighborhood": barrio.title().replace("San Cristobal", "San Cristóbal"),
                            "type":         tipo_nombre,
                            "features":     features,
                            "url":          link,
                            "source":       "MercadoLibre",
                        })
                    except Exception:
                        continue

                log.debug(f"ML [{tipo_slug}/{barrio}]: {len(cards)} cards encontradas")

            except Exception as e:
                log.error(f"MercadoLibre [{tipo_slug}/{barrio}]: {e}")

            time.sleep(0.5)

    log.info(f"MercadoLibre: {len(listings)} propiedades encontradas")
    return listings


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER: Roomix
# ─────────────────────────────────────────────────────────────────────────────
def scrape_roomix() -> list[dict]:
    """
    Roomix.ai es una plataforma nueva. El scraper intenta extraer cards
    de propiedades. Si la estructura del HTML cambia, puede necesitar ajuste.
    """
    listings = []
    try:
        r = SESSION.get("https://roomix.ai/", timeout=20)
        r.raise_for_status()

        soup  = BeautifulSoup(r.text, "html.parser")
        # Buscar elementos que parezcan cards de propiedad
        cards = soup.select("[class*='property'], [class*='listing'], [class*='card']")

        for card in cards[:30]:
            try:
                title_el = card.select_one("h2, h3, [class*='title']")
                price_el = card.select_one("[class*='price']")
                link_el  = card.select_one("a[href]")

                title = title_el.get_text(strip=True) if title_el else ""
                price = price_el.get_text(strip=True) if price_el else ""
                href  = link_el["href"] if link_el else ""

                if not href or not title:
                    continue

                # Verificar que mencione algún barrio objetivo
                if not any(b in title.lower() for b in BARRIOS_OBJETIVO):
                    continue

                link = href if href.startswith("http") else f"https://roomix.ai{href}"

                listings.append({
                    "title":  title,
                    "price":  price,
                    "url":    link,
                    "source": "Roomix",
                })
            except Exception:
                continue

    except Exception as e:
        log.error(f"Roomix: {e}")

    log.info(f"Roomix: {len(listings)} propiedades encontradas")
    return listings


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("🏠 Iniciando búsqueda de alquileres")
    log.info(f"Precio máximo: $ {PRECIO_MAX:,}".replace(",", ".") + " ARS")
    log.info(f"Ambientes mínimos: {AMBIENTES_MIN}")
    log.info("=" * 55)

    # Cargar configuración
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.error("❌ No encontré config.json. Copiá config.json.example y completá tus datos.")
        return

    token    = config.get("telegram_token", "")
    chat_ids = config.get("telegram_chat_ids", [])

    if not token or not chat_ids:
        log.error("❌ Falta telegram_token o telegram_chat_ids en config.json")
        return

    # Historial de listados ya enviados
    seen = load_seen()
    log.info(f"Listados ya vistos: {len(seen)}")

    # Ejecutar todos los scrapers
    scrapers = [
        ("MercadoLibre", scrape_mercadolibre),
        ("ArgProp",      scrape_argenprop),
        ("ZonaProp",     scrape_zonaprop),
        ("Roomix",       scrape_roomix),
    ]

    all_listings = []
    for name, fn in scrapers:
        log.info(f"▶ Buscando en {name}...")
        try:
            results = fn()
            all_listings.extend(results)
        except Exception as e:
            log.error(f"Error fatal en {name}: {e}")

    # Filtrar los que ya se enviaron
    new_listings = []
    for listing in all_listings:
        key = listing_key(listing["url"])
        if key not in seen:
            new_listings.append(listing)
            seen.add(key)

    log.info(f"✅ Nuevas propiedades: {len(new_listings)} de {len(all_listings)} encontradas")

    if new_listings:
        n = len(new_listings)
        summary = (
            f"🔍 <b>{n} nueva{'s' if n > 1 else ''} propiedad{'es' if n > 1 else ''}</b>\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            f"📍 Boedo · Almagro · Balvanera · San Cristóbal · San Telmo · Parque Patricios · Parque Chacabuco"
        )
        send_telegram(token, chat_ids, summary)
        time.sleep(1)

        for listing in new_listings:
            send_telegram(token, chat_ids, format_listing(listing), preview_url=listing.get("url", ""))
            time.sleep(0.8)
    else:
        log.info("Sin novedades hoy.")

    # Enviar avisos de scrapers (ej: ZonaProp bloqueado por Cloudflare)
    if _SCRAPER_WARNINGS:
        warn_msg = "🤖 <b>Aviso del bot de alquileres:</b>\n\n" + "\n".join(_SCRAPER_WARNINGS)
        send_telegram(token, chat_ids, warn_msg)

    save_seen(seen)
    log.info("✅ Búsqueda finalizada.\n")


if __name__ == "__main__":
    main()
