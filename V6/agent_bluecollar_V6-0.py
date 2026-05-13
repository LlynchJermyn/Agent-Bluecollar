# ---------------------------------------------------------
# AGENT BLUECOLLAR V6.0: PARALLEL & DIRECT-LINK EDITION
# Strategie: Native Linux, Globales Staggering, Klare Phasen-Logs
# Fix: Fixed-Broadband nutzt nun den blitzschnellen Direktzugriff via URL
# ---------------------------------------------------------

import os
import sys
import asyncio
import urllib.parse
import time
import httpx
import logging
import fcntl
from contextlib import asynccontextmanager
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks
import uvicorn

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- VARIABLEN AUS .ENV (STRICT MODE - OHNE FALLBACKS) ---
is_headless = os.environ["HEADLESS"].lower() == "true"
GLOBAL_STAGGER_SECONDS = float(os.environ["GLOBAL_STAGGER_SECONDS"])
TYPING_DELAY_MS = int(os.environ["TYPING_DELAY_MS"])
HOVER_DELAY_MS = int(os.environ["HOVER_DELAY_MS"])
PAGE_TIMEOUT_MS = int(os.environ["PAGE_TIMEOUT_MS"])
POLLING_TIMEOUT_MS = int(os.environ["POLLING_TIMEOUT_MS"])
POLLING_INTERVAL_MS = int(os.environ["POLLING_INTERVAL_MS"])
SHARED_LOCK_FILE = os.environ["SHARED_LOCK_FILE"]

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger(__name__)

agent_lock = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_lock
    agent_lock = asyncio.Lock()
    logger.info("Startup: asyncio.Lock() initialisiert.")
    yield

app = FastAPI(lifespan=lifespan)

class AddressRequest(BaseModel):
    store_id: float
    address: str
    lat: float
    lon: float
    webhook_url: str
    broadband_type: str = "mobile"

# --- CROSS-CONTAINER STAGGERING ---
async def wait_for_global_stagger(store_id: float):
    if GLOBAL_STAGGER_SECONDS <= 0: return

    def _sync_lock():
        os.makedirs(os.path.dirname(SHARED_LOCK_FILE), exist_ok=True)
        with open(SHARED_LOCK_FILE, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX) 
            f.seek(0)
            content = f.read().strip()
            last_start = float(content) if content else 0.0
            
            now = time.time()
            elapsed = now - last_start
            wait_time = 0.0
            
            if elapsed < GLOBAL_STAGGER_SECONDS:
                wait_time = GLOBAL_STAGGER_SECONDS - elapsed
                
            f.seek(0)
            f.truncate()
            f.write(str(now + wait_time))
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
            return wait_time

    wait_time = await asyncio.to_thread(_sync_lock)
    if wait_time > 0:
        logger.info(f"[{store_id}] ⏳ Globales Staggering greift: Warte {wait_time:.2f} Sekunden...")
        await asyncio.sleep(wait_time)

# --- CORE LOGIK ---
async def process_and_send_webhook(store_id: float, address: str, lat: float, lon: float, webhook_url: str, broadband_type: str):
    broadband_type = broadband_type.lower()
    encoded_address = urllib.parse.quote_plus(address)
    resolved_url = "N/A"
    
    await wait_for_global_stagger(store_id)
    
    async with agent_lock:
        start_time = time.time()
        final_payload = {}
        
        async with Stealth().use_async(async_playwright()) as p:
            try:
                logger.info(f"[{store_id}] 🚀 Starte nativen Chromium...")
                browser = await p.chromium.launch(
                    headless=is_headless,
                    args=['--disable-http2', '--no-sandbox', '--disable-dev-shm-usage', '--mute-audio']
                )
                context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
                page = await context.new_page()
                
                # ==========================================
                # PHASE 1: NAVIGATION & SUCHE (V6.0 Direkt-Links)
                # ==========================================
                logger.info(f"[{store_id}] 📍 === PHASE 1: DIREKT-LINK NAVIGATION ===")
                if broadband_type == "fixed":
                    logger.info(f"[{store_id}] 🏠 Nutze FIXED Direktzugriff")
                    resolved_url = f"https://broadbandmap.fcc.gov/location-summary/fixed?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00"
                    await page.goto(resolved_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                else:
                    logger.info(f"[{store_id}] 📱 Nutze MOBILE Direktzugriff")
                    resolved_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
                    await page.goto(resolved_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)

                # ==========================================
                # PHASE 1.5: MAP KLICK (Koordinaten-Trigger)
                # ==========================================
                logger.info(f"[{store_id}] 🗺️ === PHASE 1.5: MAP KLICK AUF KOORDINATEN ===")
                try:
                    # Suche das Map-Canvas
                    map_canvas = page.locator("canvas").first
                    await map_canvas.wait_for(state="visible", timeout=15000)
                    
                    # Warte, bis die Karte zu 100% zentriert und geladen ist
                    await page.wait_for_timeout(3000)
                    
                    # Klicke genau ins Zentrum des Canvas (dort liegen unsere zentrierten lat/lon Koordinaten)
                    await map_canvas.click(force=True)
                    logger.info(f"[{store_id}] 🎯 Map-Klick im Zentrum erfolgreich ausgeführt.")
                    
                    # Kurze Pause für Angular, um den Klick zu verarbeiten und die Tabelle nachzuladen
                    await page.wait_for_timeout(1500)
                except Exception as map_err:
                    logger.warning(f"[{store_id}] ⚠️ Konnte Map-Klick nicht ausführen (übersprungen): {map_err}")

                # ==========================================
                # PHASE 2: DATEN-EXTRAKTION & FAST-FAIL
                # ==========================================
                logger.info(f"[{store_id}] 📊 === PHASE 2: DATEN-EXTRAKTION (Warte max {POLLING_TIMEOUT_MS/1000}s) ===")
                try:
                    if broadband_type == "mobile":
                        try:
                            outdoor_tab = page.locator('button[role="tab"]:has-text("Outdoor Stationary")')
                            await outdoor_tab.wait_for(state="visible", timeout=15000)
                            await outdoor_tab.click(force=True)
                            await page.wait_for_timeout(500)
                        except:
                            logger.info(f"[{store_id}] ⚠️ Konnte 'Outdoor Stationary' Tab nicht klicken. Vertraue auf Default.")
                    
                    await page.wait_for_function("""
                        () => {
                            const tables = document.querySelectorAll('table');
                            const hasTable = Array.from(tables).some(t => t.rows && t.rows.length > 1);
                            
                            const bodyText = document.body.innerText || "";
                            const noData = bodyText.includes('0 Providers') || 
                                           bodyText.includes('No data available') ||
                                           bodyText.includes('No location data.') || 
                                           bodyText.includes('No results');
                                           
                            return hasTable || noData;
                        }
                    """, timeout=POLLING_TIMEOUT_MS, polling=POLLING_INTERVAL_MS)
                    
                    markdown_table = await page.evaluate("""(type) => {
                        try {
                            let finalOutput = "";
                            const bodyText = document.body.innerText || "";
                            
                            // 1. LOCATION INFO
                            const locationMatch = bodyText.match(/[^\\n]*Unit Count:[^\\n]*/i);
                            if (locationMatch) {
                                let cleanLoc = locationMatch[0].replace(/\\s+/g, ' ').trim();
                                finalOutput += "**Location Info:** " + cleanLoc + "\\n\\n";
                            }

                            // 2. PRÄZISE TABELLENSUCHE (Unverändert von V5)
                            const tables = Array.from(document.querySelectorAll('table'));
                            let target = null;
                            let dynamicTitle = "";

                            if (type === "fixed") {
                                if (tables.length > 0) {
                                    target = tables.reduce((prev, curr) => (prev.rows.length > curr.rows.length) ? prev : curr, {rows: []});
                                }
                                dynamicTitle = "Broadband Availability"; 
                            } else {
                                let activeTab = document.querySelector('.nav-link.active, [aria-selected="true"]');
                                if (activeTab && activeTab.innerText.includes("In Vehicle")) {
                                   return finalOutput ? finalOutput + "*Falscher Mobile-Tab geladen (In Vehicle statt Outdoor)*" : "EMPTY";
                                }
                                
                                target = tables.find(t => t.innerText && (t.innerText.includes("5G-NR") || t.innerText.includes("4G LTE")));
                                dynamicTitle = "Mobile Availability (Outdoor Stationary)";
                                
                                if (!target && tables.length > 0) {
                                    target = tables.reduce((prev, curr) => (prev.rows.length > curr.rows.length) ? prev : curr, {rows: []});
                                }
                            }

                            if (!target || !target.rows || target.rows.length <= 1) {
                                return finalOutput ? finalOutput + "*Keine passende Provider-Tabelle gefunden*" : "EMPTY";
                            }
                            
                            // 3. ÜBERSCHRIFT EINFÜGEN
                            finalOutput += "### " + dynamicTitle + "\\n\\n";

                            // 4. MARKDOWN TABELLE BAUEN
                            let md = "";
                            let colsCount = target.rows[0].cells.length;
                            
                            for (let i = 0; i < target.rows.length; i++) {
                                if (target.rows[i].cells.length === 1) {
                                    let singleText = target.rows[i].cells[0].innerText.replace(/\\n/g, ' ').trim();
                                    md += "| **" + singleText + "** |" + " |".repeat(colsCount - 1) + "\\n";
                                    continue;
                                }
                                
                                let rowData = Array.from(target.rows[i].cells).map(c => {
                                    let text = c.innerText.replace(/\\n/g, ' ').trim();
                                    return text.replace(/Click to filter map by provider/gi, '').trim();
                                });
                                
                                if (rowData.length > 0 && rowData[0].includes("Holding Company")) {
                                    rowData[0] = rowData[0].split("Holding Company")[0].trim();
                                }
                                
                                md += "| " + rowData.join(" | ") + " |\\n";
                                
                                if (i === 0) {
                                    md += "| " + Array(colsCount).fill("---").join(" | ") + " |\\n";
                                }
                            }
                            return finalOutput + md.trim();
                        } catch (fatalError) {
                            return "EMPTY";
                        }
                    }""", broadband_type)
                    
                    logger.info(f"[{store_id}] ✅ Extraktion der Daten beendet.")
                except Exception as e:
                    logger.warning(f"[{store_id}] ⚠️ Timeout oder leere Adresse erreicht.")
                    markdown_table = "EMPTY"
                
                await browser.close()
                duration = round(time.time() - start_time, 2)
                
                final_payload = {
                    "store_id": store_id,
                    "address": address,
                    "resolved_url": resolved_url,
                    "status": "success",
                    "broadband_type": broadband_type,
                    "providers": [] if markdown_table == "EMPTY" else [markdown_table],
                    "usage": {"duration_seconds": duration, "model": "v6.0-parallel-directlink"}
                }
                
            except Exception as e:
                logger.error(f"[{store_id}] FEHLER: {e}")
                final_payload = {
                    "store_id": store_id, 
                    "broadband_type": broadband_type, 
                    "resolved_url": resolved_url, 
                    "status": "error", 
                    "message": str(e)
                }

        # ==========================================
        # WEBHOOK VERSAND & ERGEBNIS-LOGGING
        # ==========================================
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(webhook_url, json=final_payload)
                
                if final_payload.get("status") == "success" and len(final_payload.get("providers", [])) > 0:
                    logger.info(f"[{store_id}] ✅ Provider-Daten übermittelt")
                else:
                    logger.info(f"[{store_id}] ❌ Fehlermeldung senden: keine Provider Daten für Store-ID {store_id}")
                    
        except Exception as web_err:
            logger.error(f"[{store_id}] ❌ Webhook Fehler: {web_err}")

@app.post("/api/v1/fcc_agent_bluecollar")
async def main(request: AddressRequest, background_tasks: BackgroundTasks):
    logger.info(f"📥 Request für Store {request.store_id} in Queue aufgenommen.")
    background_tasks.add_task(process_and_send_webhook, request.store_id, request.address, request.lat, request.lon, request.webhook_url, request.broadband_type)
    return {"status": "queued", "store_id": request.store_id}

if __name__ == "__main__":
    api_port = int(os.environ["API_PORT"])
    uvicorn.run(app, host="0.0.0.0", port=api_port, log_level="info")