#!/usr/bin/env python3
"""
Ejecutá este script UNA SOLA VEZ para obtener los chat IDs de Telegram.

Pasos previos:
  1. Creá un bot con @BotFather en Telegram → obtené el TOKEN
  2. Vos y tu novia escribanle un mensaje al bot (o /start)
  3. Poné el token en config.json (telegram_token) o pasalo por variable de entorno TELEGRAM_TOKEN
  4. Ejecutá: python get_chat_id.py
"""

import json
import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN and os.path.exists("config.json"):
    with open("config.json", encoding="utf-8") as f:
        TOKEN = json.load(f).get("telegram_token")
if not TOKEN:
    TOKEN = input("Pegá el token de Telegram (BotFather): ").strip()

url  = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
resp = requests.get(url, timeout=10)

if not resp.ok:
    print(f"❌ Error: {resp.status_code} — ¿El token es correcto?")
    raise SystemExit(1)

data    = resp.json()
updates = data.get("result", [])

if not updates:
    print("⚠️  Sin mensajes aún.")
    print("   Asegurate de que vos y tu novia le hayan escrito al bot primero.")
    raise SystemExit(0)

seen_ids = set()
print("\n✅ Chat IDs encontrados:\n")
for update in updates:
    msg  = update.get("message", {})
    chat = msg.get("chat", {})
    cid  = chat.get("id")
    name = chat.get("first_name", "?") + " " + chat.get("last_name", "")
    if cid and cid not in seen_ids:
        seen_ids.add(cid)
        print(f'  👤 {name.strip():20s} → chat_id: "{cid}"')

print("\nCopiá esos IDs en config.json → telegram_chat_ids\n")
