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

try:
    import cloudscraper
    CSCRAPER = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    CSCRAPER.headers.update({
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    })
except ImportError:
    CSCRAPER = None  # fallback a SESSION si no está instalado

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
    "Accept-Language":           "es-AR,es;q=0.9,en;q=0.8",
    "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Encoding":           "gzip, deflate, br",
    "Connection":                "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":            "document",
    "Sec-Fetch-Mode":            "navigate",
    "Sec-Fetch-Site":            "none",
    "Sec-Fetch-User":            "?1",
    "Cache-Control":             "max-age=0",
})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def cs_get(url: str, **kwargs):
    """GET con cloudscraper si está disponible, si no usa SESSION normal."""
    if CSCRAPER is not None:
        return CSCRAPER.get(url, **kwargs)
    return SESSION.get(url, **kwargs)


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
def send_telegram_photo(token: str, chat_ids: list, caption: str, photo_url: str):
    """
    Envía una foto con caption. Usado para ML, donde el crawler de Telegram
    no puede obtener la preview porque la página requiere JS.
    Si falla (URL inválida, imagen no accesible), hace fallback a texto.
    """
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    # caption tiene límite de 1024 chars en Telegram
    caption_short = caption if len(caption) <= 1024 else caption[:1020] + "…"
    for chat_id in chat_ids:
        try:
            r = requests.post(url, json={
                "chat_id":    chat_id,
                "photo":      photo_url,
                "caption":    caption_short,
                "parse_mode": "HTML",
            }, timeout=15)
            if r.ok:
                log.info(f"✅ Telegram foto → {chat_id}")
            else:
                raise ValueError(r.text)
        except Exception as e:
            log.warning(f"Telegram foto falló ({e}), usando texto")
            send_telegram(token, [chat_id], caption)


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
                r = cs_get(url, timeout=30)
                if r.status_code == 404:
                    break
                if r.status_code == 403:
                    time.sleep(3)
                    r = cs_get(url, timeout=30)
                if r.status_code == 403:
                    log.warning(f"ArgProp [{tipo}]: bloqueado (403) — IP no permitida en este entorno")
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
def _parse_zonaprop_postings(postings: list) -> tuple[list, dict]:
    """Parsea la lista de postings de ZonaProp (JSON) y aplica los filtros."""
    listings = []
    n_usd = n_price = n_rooms = n_area = n_outdoor = n_no_url = n_exc = 0
    outdoor_kws = ("patio", "terraza", "jardín", "jardin", "balcón", "balcon")

    for post in postings:
        try:
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
                n_usd += 1; continue

            expenses_num = post.get("expenses") or 0
            if isinstance(expenses_num, dict):
                expenses_num = expenses_num.get("amount", 0) or 0
            if price_num and (price_num + expenses_num) > PRECIO_MAX:
                n_price += 1; continue

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
                n_rooms += 1; continue

            prop_type = (post.get("realEstateType", {}).get("name", "") or "").lower()
            covered   = post.get("coveredArea") or 0
            total     = post.get("totalArea") or 0
            area      = total or covered
            size      = f"{area} m²" if area else ""
            if prop_type == "departamento" and covered and covered < 80:
                n_area += 1; continue

            location = post.get("postingLocation", {}) or {}
            barrio   = (
                (location.get("neighbourhood") or {}).get("name", "")
                or (location.get("city") or {}).get("name", "")
            )

            address    = post.get("address", "") or ""
            title      = post.get("title", "") or address or f"{prop_type} en {barrio}"
            url_suffix = (
                post.get("url") or post.get("postingUrl")
                or post.get("slug") or post.get("link") or ""
            )
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
                n_no_url += 1; continue

            highlighted = post.get("highlightedFeatures") or []
            feat_labels = " ".join(f.get("label", "") for f in highlighted)
            full_text   = f"{title} {feat_labels}".lower()

            if any(kw in full_text for kw in ("cochera", "garage")):
                if not any(kw in full_text for kw in ("sin cochera", "sin garage")):
                    if any("cochera" in (f.get("label", "")).lower() for f in highlighted):
                        continue

            features = [
                kw.replace("jardin", "jardín").replace("balcon", "balcón").capitalize()
                for kw in outdoor_kws if kw in full_text
            ]
            if prop_type == "departamento" and not features:
                n_outdoor += 1; continue

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

    stats = dict(usd=n_usd, precio=n_price, ambientes=n_rooms,
                 m2=n_area, sin_outdoor=n_outdoor, sin_url=n_no_url, exc=n_exc)
    return listings, stats


def scrape_zonaprop(pages: int = 5) -> list[dict]:
    """
    ZonaProp embebe los listados en window.__PRELOADED_STATE__ en el HTML.
    Usamos un scraper limpio (sin headers extra que puedan triggear el bloqueo).
    """
    import cloudscraper as _cs
    scraper = _cs.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    listings = []
    neighborhoods_slug = (
        "boedo-almagro-parque-patricios-balvanera-"
        "san-cristobal-san-telmo-parque-chacabuco"
    )

    for page_num in range(1, pages + 1):
        page_suffix = f"-pagina-{page_num}" if page_num > 1 else ""
        url = (
            f"https://www.zonaprop.com.ar/casas-departamentos-ph-alquiler-"
            f"{neighborhoods_slug}-3-ambientes-mas"
            f"-orden-publicado-descendente{page_suffix}.html"
        )
        try:
            r = scraper.get(url, timeout=30)
            log.info(f"ZonaProp p{page_num}: HTTP {r.status_code}, {len(r.content)} bytes")

            if r.status_code in (403, 503):
                log.warning(f"ZonaProp: bloqueado (HTTP {r.status_code})")
                break
            r.raise_for_status()

            soup     = BeautifulSoup(r.text, "html.parser")
            preloaded = None
            for script in soup.find_all("script"):
                content = script.string or ""
                marker  = "window.__PRELOADED_STATE__ = "
                idx     = content.find(marker)
                if idx >= 0:
                    try:
                        preloaded, _ = json.JSONDecoder().raw_decode(content, idx + len(marker))
                    except json.JSONDecodeError as je:
                        log.warning(f"ZonaProp p{page_num}: JSON error: {je}")
                    break

            if not preloaded:
                log.warning(f"ZonaProp p{page_num}: __PRELOADED_STATE__ no encontrado ({len(r.content)} bytes)")
                break

            postings = preloaded.get("listStore", {}).get("listPostings", [])
            if not postings:
                log.info(f"ZonaProp: fin de páginas en {page_num}")
                break

            page_listings, stats = _parse_zonaprop_postings(postings)
            listings.extend(page_listings)
            log.info(
                f"ZonaProp p{page_num}: {len(postings)} raw → "
                + " ".join(f"{k}={v}" for k, v in stats.items())
            )
            time.sleep(2)

        except Exception as e:
            log.error(f"ZonaProp página {page_num}: {e}")
            break

    log.info(f"ZonaProp: {len(listings)} propiedades encontradas")
    return listings


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER: MercadoLibre — Playwright (headless browser)
# ML es React/Next.js, no scrapeable con requests.
# Playwright renderiza el JS y nos deja ver las cards reales.
# Instalación: pip install playwright && playwright install chromium
# ─────────────────────────────────────────────────────────────────────────────
def scrape_mercadolibre_playwright() -> list[dict]:
    """
    Scraper de ML con Playwright (headless Chromium).
    Busca por barrio directamente en la URL → evita parsear texto de ubicación.
    Stealth mejorado para evitar detección.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("ML: playwright no instalado. Ejecutá: pip install playwright && playwright install chromium")
        return []

    listings    = []
    seen_urls: set[str] = set()
    outdoor_kws = ("patio", "terraza", "jardín", "jardin", "balcón", "balcon")

    tipos_cfg = [
        ("departamentos", "departamento"),
        ("ph",            "ph"),
        ("casas",         "casa"),
    ]

    # URL slug → nombre canónico del barrio
    # Formato ML: /inmuebles.mercadolibre.com.ar/{tipo}/alquiler/capital-federal/{barrio}/
    barrios_cfg = [
        ("boedo",            "Boedo"),
        ("almagro",          "Almagro"),
        ("parque-patricios", "Parque Patricios"),
        ("balvanera",        "Balvanera"),
        ("san-cristobal",    "San Cristóbal"),
        ("san-telmo",        "San Telmo"),
        ("parque-chacabuco", "Parque Chacabuco"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="es-AR",
            viewport={"width": 1366, "height": 768},
            timezone_id="America/Argentina/Buenos_Aires",
        )

        # Parchear señales JS que delatan headless
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['es-AR', 'es', 'en']});
            window.chrome = { runtime: {} };
        """)

        page = context.new_page()

        try:
            from playwright_stealth import stealth_sync
            stealth_sync(page)
            log.debug("ML: stealth mode activado")
        except ImportError:
            log.debug("ML: playwright-stealth no instalado, continuando sin stealth")

        for tipo_slug, tipo_nombre in tipos_cfg:
            for barrio_slug, barrio_nombre in barrios_cfg:
                # URL pre-filtrada por barrio → no hace falta parsear ubicación
                url = (
                    f"https://inmuebles.mercadolibre.com.ar/"
                    f"{tipo_slug}/alquiler/capital-federal/{barrio_slug}/"
                )
                try:
                    page.goto(url, timeout=40_000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2_000)
                    try:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                        page.wait_for_timeout(1_500)
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(1_500)
                    except Exception:
                        pass  # página redirigida durante scroll — seguimos igual

                    try:
                        page.wait_for_selector(
                            "li.ui-search-layout__item, .poly-card",
                            timeout=12_000,
                        )
                    except Exception:
                        log.warning(f"ML [{tipo_slug}/{barrio_slug}]: timeout esperando cards")
                        continue

                    html  = page.content()
                    soup  = BeautifulSoup(html, "html.parser")
                    cards = soup.select("li.ui-search-layout__item, .poly-card")
                    log.info(f"ML [{tipo_slug}/{barrio_slug}]: {len(cards)} cards")

                    for card in cards:
                        try:
                            title_el = card.select_one(
                                ".poly-component__title, .ui-search-item__title, h2, h3"
                            )
                            title = title_el.get_text(strip=True) if title_el else ""

                            # Precio
                            price_el   = card.select_one(
                                ".andes-money-amount__fraction, [class*='price__fraction']"
                            )
                            price_text = price_el.get_text(strip=True).replace(".", "") if price_el else ""
                            price_num  = parse_price(price_text)

                            curr_el  = card.select_one(
                                ".andes-money-amount__currency-symbol, [class*='price__symbol']"
                            )
                            curr_txt = (curr_el.get_text(strip=True) if curr_el else "").upper()
                            if curr_txt and curr_txt not in ("$", "ARS", ""):
                                continue
                            if price_num and price_num > PRECIO_MAX:
                                continue

                            # Link — URL real sin tracking params
                            link_el   = card.select_one("a[href]")
                            raw_href  = link_el["href"] if link_el else ""
                            link      = raw_href.split("?")[0].split("#")[0]
                            # Clave de deduplicación: MLA ID estable entre runs
                            mla_m     = re.search(r"MLA[_-](\d+)", raw_href)
                            dedup_key = f"ML:{mla_m.group(1)}" if mla_m else link
                            if not link or dedup_key in seen_urls:
                                continue

                            # Texto completo de la card para filtros de ambientes y superficie
                            card_text = card.get_text(separator=" ", strip=True).lower()

                            # Bloquear monoambientes explícitamente
                            if "monoambiente" in card_text or "mono ambiente" in card_text:
                                continue

                            # Ambientes mínimos
                            rooms = 0
                            m = re.search(r"(\d+)\s*amb(?:iente)?s?", card_text)
                            if m:
                                rooms = int(m.group(1))
                            if rooms and rooms < AMBIENTES_MIN:
                                continue

                            # Superficie mínima para departamentos
                            area = 0
                            m = re.search(r"(\d+)\s*m²", card_text)
                            if m:
                                area = int(m.group(1))
                            if tipo_nombre == "departamento" and area and area < 80:
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

                            # Imagen — ML usa mlstatic.com, accesible directamente
                            img_el  = card.select_one(
                                "img[src*='mlstatic'], img[data-src*='mlstatic'], "
                                ".poly-card__portada img, .ui-search-result-image__element"
                            )
                            img_url = ""
                            if img_el:
                                img_url = img_el.get("src") or img_el.get("data-src") or ""

                            seen_urls.add(dedup_key)
                            listings.append({
                                "title":        title,
                                "price":        price_text,
                                "rooms":        str(rooms) if rooms else "",
                                "size":         f"{area} m²" if area else "",
                                "neighborhood": barrio_nombre,
                                "type":         tipo_nombre,
                                "features":     features,
                                "url":          link,
                                "image_url":    img_url,
                                "dedup_key":    dedup_key,
                                "source":       "MercadoLibre",
                            })

                        except Exception:
                            continue

                    time.sleep(1.5)

                except Exception as e:
                    log.error(f"ML [{tipo_slug}/{barrio_slug}]: {e}")

        browser.close()

    log.info(f"MercadoLibre (Playwright): {len(listings)} propiedades encontradas")
    return listings


def get_ml_token(client_id: str, client_secret: str) -> str:
    """Obtiene un access token de ML usando client_credentials (sin login de usuario)."""
    try:
        r = requests.post(
            "https://api.mercadolibre.com/oauth/token",
            data={
                "grant_type":    "client_credentials",
                "client_id":     client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
        if not r.ok:
            log.warning(f"ML token: HTTP {r.status_code} — {r.text[:150]}")
            return ""
        token = r.json().get("access_token", "")
        log.info("ML: token de app obtenido ✅")
        return token
    except Exception as e:
        log.error(f"ML token: {e}")
        return ""


def scrape_mercadolibre(access_token: str = "") -> list[dict]:
    """
    Usa la API oficial de ML con token de app para buscar inmuebles en CABA.
    Filtra por operación (alquiler), barrio, precio, cochera y outdoor.
    Si no hay token configurado, se saltea ML.
    """
    if not access_token:
        log.info("MercadoLibre: sin credenciales configuradas, se saltea.")
        return []

    listings    = []
    seen_urls: set[str] = set()
    outdoor_kws = ("patio", "terraza", "jardín", "jardin", "balcón", "balcon")
    API_URL     = "https://api.mercadolibre.com/sites/MLA/search"
    headers     = {"Authorization": f"Bearer {access_token}"}
    barrios     = sorted(BARRIOS_OBJETIVO - {"san cristobal"})

    for barrio in barrios:
        offset = 0
        while offset < 100:   # máx 2 páginas de 50
            try:
                params = {
                    "category": "MLA1459",          # Inmuebles Argentina
                    "q":        f"{barrio} capital federal",
                    "limit":    50,
                    "offset":   offset,
                }
                r = SESSION.get(API_URL, params=params, headers=headers, timeout=20)
                if not r.ok:
                    log.warning(f"ML API [{barrio}]: HTTP {r.status_code}")
                    break

                data  = r.json()
                items = data.get("results", [])
                if not items:
                    break

                log.debug(f"ML [{barrio}] offset={offset}: {len(items)} items (total {data.get('paging',{}).get('total','?')})")

                for item in items:
                    try:
                        price    = item.get("price") or 0
                        currency = item.get("currency_id", "ARS")
                        title    = item.get("title", "")
                        link     = item.get("permalink", "")

                        if not link or link in seen_urls:
                            continue
                        if currency != "ARS" or price > PRECIO_MAX:
                            continue

                        # Filtrar por operación: solo alquiler
                        attrs     = {a["id"]: (a.get("value_name") or "") for a in (item.get("attributes") or [])}
                        operation = attrs.get("OPERATION", "").lower()
                        if operation and "alquiler" not in operation:
                            continue

                        # Ambientes
                        rooms_val = attrs.get("ROOMS") or attrs.get("BEDROOMS") or ""
                        try:
                            rooms = int(str(rooms_val).split()[0])
                        except Exception:
                            rooms = 0
                        if rooms and rooms < AMBIENTES_MIN:
                            continue

                        # Superficie (deptos: mín 80 m²)
                        area_val = attrs.get("COVERED_AREA") or attrs.get("TOTAL_AREA") or ""
                        try:
                            area = int(str(area_val).split()[0])
                        except Exception:
                            area = 0

                        prop_type_attr = attrs.get("PROPERTY_TYPE", "").lower()
                        if "ph" in prop_type_attr:
                            tipo = "ph"
                        elif "casa" in prop_type_attr:
                            tipo = "casa"
                        else:
                            tipo = "departamento"

                        if tipo == "departamento" and area and area < 80:
                            continue

                        title_lower = title.lower()
                        if any(kw in title_lower for kw in ("cochera", "garage")) and \
                           not any(kw in title_lower for kw in ("sin cochera", "sin garage")):
                            continue

                        features = [
                            kw.replace("jardin", "jardín").replace("balcon", "balcón").capitalize()
                            for kw in outdoor_kws if kw in title_lower
                        ]
                        if tipo == "departamento" and not features:
                            continue

                        seen_urls.add(link)
                        listings.append({
                            "title":        title,
                            "price":        f"$ {int(price):,}".replace(",", "."),
                            "rooms":        str(rooms) if rooms else "",
                            "size":         f"{area} m²" if area else "",
                            "neighborhood": barrio.title().replace("San Cristobal", "San Cristóbal"),
                            "type":         tipo,
                            "features":     features,
                            "url":          link,
                            "source":       "MercadoLibre",
                        })
                    except Exception:
                        continue

                offset += 50
                time.sleep(0.5)

            except Exception as e:
                log.error(f"ML API [{barrio}]: {e}")
                break

    log.info(f"MercadoLibre: {len(listings)} propiedades encontradas")
    return listings


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER: Properati
# ─────────────────────────────────────────────────────────────────────────────
def scrape_properati() -> list[dict]:
    """
    Properati es otro portal grande de inmuebles argentinos.
    Busca por barrio + tipo usando cloudscraper para evitar bloqueos.
    """
    listings    = []
    seen_urls: set[str] = set()
    outdoor_kws = ("patio", "terraza", "jardín", "jardin", "balcón", "balcon")
    barrios     = sorted(BARRIOS_OBJETIVO - {"san cristobal"})
    tipos_cfg   = [
        ("departamento", "departamento"),
        ("ph",           "ph"),
        ("casa",         "casa"),
    ]

    for tipo_query, tipo_nombre in tipos_cfg:
        for barrio in barrios:
            barrio_slug = (
                barrio.replace(" ", "-")
                      .replace("ó", "o").replace("á", "a")
                      .replace("é", "e").replace("í", "i")
            )
            url = (
                f"https://www.properati.com.ar/s/"
                f"{barrio_slug}-capital-federal/{tipo_query}/alquiler/"
            )
            try:
                r = cs_get(url, timeout=20)
                if not r.ok:
                    log.debug(f"Properati [{tipo_query}/{barrio}]: HTTP {r.status_code}")
                    time.sleep(0.5)
                    continue

                soup = BeautifulSoup(r.text, "html.parser")

                # Properati embebe los datos en window.__PRELOADED_STATE__ o similar
                preloaded = None
                for script in soup.find_all("script"):
                    content = script.string or ""
                    for marker in ("window.__PRELOADED_STATE__ = ", "window.__STATE__ = "):
                        idx = content.find(marker)
                        if idx >= 0:
                            try:
                                preloaded, _ = json.JSONDecoder().raw_decode(content, idx + len(marker))
                            except Exception:
                                pass
                            break
                    if preloaded:
                        break

                items = []
                if preloaded:
                    # Intentar distintas rutas según la versión del JSON
                    items = (
                        preloaded.get("listings", {}).get("listings", [])
                        or preloaded.get("search", {}).get("listings", [])
                        or preloaded.get("results", [])
                        or []
                    )

                for item in items:
                    try:
                        price    = (item.get("price") or {}).get("total") or item.get("price_total") or 0
                        currency = (item.get("price") or {}).get("currency", "ARS") or "ARS"
                        title    = item.get("title", "") or item.get("address", "")
                        link_raw = item.get("url") or item.get("permalink") or ""
                        link     = link_raw if link_raw.startswith("http") else f"https://www.properati.com.ar{link_raw}"

                        if not link or link in seen_urls:
                            continue
                        if currency != "ARS" or (price and price > PRECIO_MAX):
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
                            "price":        f"$ {int(price):,}".replace(",", ".") if price else "",
                            "neighborhood": barrio.title().replace("San Cristobal", "San Cristóbal"),
                            "type":         tipo_nombre,
                            "features":     features,
                            "url":          link,
                            "source":       "Properati",
                        })
                    except Exception:
                        continue

                if not items:
                    # Fallback: parsear cards HTML
                    cards = soup.select(
                        "[class*='listing-card'], [class*='property-card'], "
                        "[class*='PostingCard'], article"
                    )
                    for card in cards[:30]:
                        try:
                            title_el = card.select_one("h2, h3, [class*='title'], [class*='address']")
                            price_el = card.select_one("[class*='price'], [class*='Price']")
                            link_el  = card.select_one("a[href]")

                            title    = title_el.get_text(strip=True) if title_el else ""
                            price_t  = price_el.get_text(strip=True) if price_el else ""
                            href     = link_el["href"] if link_el else ""
                            link     = href if href.startswith("http") else f"https://www.properati.com.ar{href}"

                            if not link or not title or link in seen_urls:
                                continue
                            price_num = parse_price(price_t)
                            if price_num and price_num > PRECIO_MAX:
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
                                "price":        price_t,
                                "neighborhood": barrio.title().replace("San Cristobal", "San Cristóbal"),
                                "type":         tipo_nombre,
                                "features":     features,
                                "url":          link,
                                "source":       "Properati",
                            })
                        except Exception:
                            continue

            except Exception as e:
                log.error(f"Properati [{tipo_query}/{barrio}]: {e}")

            time.sleep(0.8)

    log.info(f"Properati: {len(listings)} propiedades encontradas")
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

    # Token de ML (opcional — si no está configurado, se saltea ML)
    ml_token = ""
    ml_id     = config.get("ml_client_id", "")
    ml_secret = config.get("ml_client_secret", "")
    if ml_id and ml_secret:
        ml_token = get_ml_token(ml_id, ml_secret)

    # Historial de listados ya enviados
    seen = load_seen()
    log.info(f"Listados ya vistos: {len(seen)}")

    # Ejecutar todos los scrapers
    scrapers = [
        ("MercadoLibre", lambda: scrape_mercadolibre_playwright() or scrape_mercadolibre(ml_token)),
        ("ArgProp",      scrape_argenprop),
        ("ZonaProp",     scrape_zonaprop),
        ("Properati",    scrape_properati),
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
        key = listing_key(listing.get("dedup_key") or listing["url"])
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
            img_url = listing.get("image_url", "")
            if img_url:
                send_telegram_photo(token, chat_ids, format_listing(listing), img_url)
            else:
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
