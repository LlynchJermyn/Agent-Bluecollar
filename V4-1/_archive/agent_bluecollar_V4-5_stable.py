# ----------------------------------------
# AGENT BLUECOLLAR V4.5: BROWSER-USE NATIVE EDITION
# Basis: The Perfect Extractor (Native Linux, No Spoofing)
# ----------------------------------------

import os
import sys
import asyncio
import urllib.parse
import time
import httpx
import logging
from contextlib import asynccontextmanager
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks
import uvicorn

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger(__name__)

is_headless = (os.getenv("HEADLESS") or "false").lower() == "true"

agent_lock = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_lock
    agent_lock = asyncio.Lock()
    logger.info("Startup complete: asyncio.Lock() erfolgreich initialisiert.")
    yield
    logger.info("Shutting down...")

app = FastAPI(lifespan=lifespan)

class AddressRequest(BaseModel):
    store_id: float
    address: str
    lat: float
    lon: float
    webhook_url: str
    broadband_type: str = "mobile"

async def log_akamai_cookie(context, tag, address):
    cookies = await context.cookies()
    abck = next((c['value'] for c in cookies if c['name'] == '_abck'), 'FEHLT')
    logger.info(f"🍪 [{tag} | {address[:15]}...] _abck: {abck}")

async def handle_response(response, address):
    if "/api/" in response.url and response.status in [403, 429, 401]:
        logger.warning(f"🛑 AKAMAI BLOCK (Status {response.status}) für API: {response.url} [{address[:15]}...]")

async def process_and_send_webhook(store_id: float, address: str, lat: float, lon: float, webhook_url: str, broadband_type: str):
    broadband_type = broadband_type.lower()
    encoded_address = urllib.parse.quote_plus(address)
    
    logger.info(f"🚀 Job {store_id} gestartet. Typ: {broadband_type.upper()} | Adresse: {address}")
    
    async with agent_lock:
        start_time = time.time()
        final_payload = {}
        
        async with Stealth().use_async(async_playwright()) as p:
            try:
                logger.info(f"[{store_id}] Starte nativen Playwright Chromium...")
                
                # Wir entfernen channel="chrome" und nutzen das native Chromium
                browser = await p.chromium.launch(
                    headless=is_headless,
                    args=[
                        '--disable-http2',
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--mute-audio'
                    ]
                )
                
                # KEIN gefälschter Mac/Windows User-Agent! Playwright nutzt automatisch den Linux UA.
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    is_mobile=False,
                    has_touch=False,
                    locale='en-US'
                )
                
                # KEIN add_init_script mehr! WebGL und Platform bleiben unangetastet (Native Linux).
                
                page = await context.new_page()
                page.on("response", lambda response: asyncio.create_task(handle_response(response, address)))
                
                if broadband_type == "fixed":
                    logger.info(f"[{store_id}] --- [PHASE 1] Starte FIXED Broadband via Homepage-Suche ---")
                    home_url = "https://broadbandmap.fcc.gov/home?version=jun2025"
                    
                    try:
                        await page.goto(home_url, wait_until="domcontentloaded", timeout=40000)
                        
                        # DIAGNOSE: Logge den NATIVEN Linux-Fingerprint
                        fp = await page.evaluate("""() => {
                            const gl = document.createElement('canvas').getContext('webgl');
                            const debugInfo = gl ? gl.getExtension('WEBGL_debug_renderer_info') : null;
                            return {
                                ua: navigator.userAgent,
                                platform: navigator.platform,
                                webgl: debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : 'none'
                            };
                        }""")
                        logger.info(f"[{store_id}] 🕵️ [NATIVE FINGERPRINT]: Platform: {fp['platform']} | GPU: {fp['webgl']}")
                        
                        await page.mouse.move(500, 500)
                        await page.wait_for_timeout(1000)
                        await page.mouse.wheel(0, 200)
                        
                        await log_akamai_cookie(context, "Nach Seitenaufbau", address)
                        
                        await page.wait_for_selector("#addrSearch", state="visible", timeout=15000)
                        logger.info(f"[{store_id}] ⌨️ Tippe Adresse ein...")
                        
                        await page.locator("#addrSearch").click(force=True)
                        await page.evaluate('document.querySelector("#addrSearch").value = ""')
                        await page.locator("#addrSearch").press_sequentially(address, delay=60)
                        
                        dropdown_item = page.locator(".search-results button, .search-results .dropdown-item").first
                        logger.info(f"[{store_id}] ⏳ Warte auf Dropdown...")
                        await dropdown_item.wait_for(state="visible", timeout=25000)
                        
                        await log_akamai_cookie(context, "Vor Dropdown-Klick", address)
                        
                        await dropdown_item.hover()
                        await page.wait_for_timeout(800)
                        
                        logger.info(f"[{store_id}] 🖱️ Klicke auf Ergebnis...")
                        try:
                            async with page.expect_navigation(timeout=30000):
                                await dropdown_item.click(force=True)
                        except Exception:
                            logger.warning(f"[{store_id}] Navigation verzögert. Fallback aktiv.")
                        
                        logger.info(f"[{store_id}] 🔗 Aktuelle URL nach Klick: {page.url}")
                        
                        try:
                            await page.locator("a.nav-link:has-text('Fixed Broadband')").click(timeout=5000)
                        except:
                            pass 
                            
                    except Exception as nav_err:
                        logger.error(f"[{store_id}] ⚠️ Navigation fehlgeschlagen: {nav_err}")
                
                else:
                    target_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
                    logger.info(f"[{store_id}] --- [PHASE 1] Starte MOBILE Broadband direkt ---")
                    try:
                        await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
                        await page.mouse.move(300, 300)
                        await page.wait_for_timeout(1000)
                    except Exception as e:
                        pass
                
                # ==========================================
                # ANGULAR POLLING
                # ==========================================
                logger.info(f"[{store_id}] ⏳ Warte auf FCC Tabellen-Rendering...")
                await page.wait_for_timeout(3000) 
                
                await log_akamai_cookie(context, "Während Daten-Polling", address)
                
                try:
                    if broadband_type == "fixed":
                        await page.wait_for_function("""
                            () => {
                                const tables = document.querySelectorAll('table');
                                for (let t of tables) {
                                    if (t.innerText.includes('Technology') && t.innerText.includes('Provider') && t.rows.length > 1) {
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """, timeout=35000, polling=1000)
                    else:
                        await page.wait_for_function("""
                            () => {
                                const tables = document.querySelectorAll('table');
                                for (let t of tables) {
                                    if (t.innerText.includes('Provider') && (t.innerText.includes('5G-NR') || t.innerText.includes('4G LTE')) && t.rows.length > 1) {
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """, timeout=30000, polling=1000)
                    
                    logger.info(f"[{store_id}] ✅ Tabelle ({broadband_type.upper()}) erfolgreich gerendert! Starte Extraktion...")
                    
                    markdown_table = await page.evaluate("""(type) => {
                        let finalOutput = "";
                        if (type === "fixed") {
                            const statusParagraphs = Array.from(document.querySelectorAll('*'));
                            for (let p of statusParagraphs) {
                                if (p.innerText && p.innerText.trim().startsWith('Status:')) {
                                    finalOutput += "**Location Info:** " + p.innerText.replace(/\\n/g, ' ').trim() + "\\n\\n";
                                    break;
                                }
                            }
                        }

                        const tables = Array.from(document.querySelectorAll('table'));
                        if (tables.length === 0) return "EMPTY";
                        
                        let target = tables.reduce((prev, current) => (prev.rows.length > current.rows.length) ? prev : current);
                        if (!target || target.rows.length <= 1) return "EMPTY";
                        
                        let md = "";
                        let colsCount = target.rows[0].cells.length;
                        
                        for (let i = 0; i < target.rows.length; i++) {
                            const row = target.rows[i];
                            let rowData = [];
                            
                            if (row.cells.length === 1 && row.cells[0].innerText.trim().length > 0) {
                                let businessText = row.cells[0].innerText.replace(/\\n/g, ' ').trim();
                                rowData.push("**" + businessText + "**");
                                for (let k = 1; k < colsCount; k++) rowData.push("---");
                                md += "| " + rowData.join(" | ") + " |\\n";
                                continue;
                            }
                            
                            for (let j = 0; j < row.cells.length; j++) {
                                let cell = row.cells[j];
                                let cellText = cell.innerText.replace(/\\n/g, ' ').replace(/\\s+/g, ' ').trim();
                                
                                if (j === 0 && cellText.includes("Holding Company")) {
                                    cellText = cellText.split("Holding Company")[0].trim();
                                }
                                
                                if (type === "mobile") {
                                    if (cell.querySelector('.fa-check')) {
                                        let numbers = cellText.replace(/Click to filter map by provider/ig, '').trim();
                                        cellText = numbers ? `YES (${numbers})` : "YES";
                                    } else if (cellText.includes("Click to filter")) {
                                        cellText = "";
                                    }
                                } else if (type === "fixed") {
                                    if (i === 0) {
                                        if (cellText.includes("Down")) cellText = "Down (Mbps)";
                                        if (cellText.includes("Up")) cellText = "Up (Mbps)";
                                    }
                                }
                                rowData.push(cellText);
                            }
                            md += "| " + rowData.join(" | ") + " |\\n";
                            
                            if (i === 0) {
                                let separator = Array(colsCount).fill("---");
                                md += "| " + separator.join(" | ") + " |\\n";
                            }
                        }
                        return finalOutput + md.trim();
                    }""", broadband_type)
                    
                except Exception as wait_err:
                    logger.warning(f"[{store_id}] ❌ Keine Datentabelle gefunden (Timeout).")
                    markdown_table = "EMPTY"
                
                await browser.close()
                
                duration_seconds = round(time.time() - start_time, 2)
                logger.info(f"[{store_id}] ⏱️ DAUER: {duration_seconds} Sekunden")
                
                providers_array = [] if markdown_table == "EMPTY" else [markdown_table]
                
                final_payload = {
                    "store_id": store_id,
                    "address": address,
                    "status": "success",
                    "broadband_type": broadband_type,
                    "providers": providers_array,
                    "usage": {
                        "model": f"browser-use-native ({broadband_type.upper()})",
                        "duration_seconds": duration_seconds
                    }
                }
                
            except Exception as e:
                logger.error(f"[{store_id}] ⚠️ FEHLER bei Skript-Ausführung: {str(e)}")
                final_payload = {
                    "store_id": store_id, "address": address, 
                    "status": "error", "broadband_type": broadband_type, 
                    "message": str(e), "providers": [], "usage": {}
                }

        try:
            logger.info(f"[{store_id}] 📤 Sende Ergebnis an Webhook...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(webhook_url, json=final_payload)
                response.raise_for_status()
                logger.info(f"[{store_id}] ✅ Webhook erfolgreich übermittelt!")
        except Exception as webhook_err:
            logger.error(f"[{store_id}] ❌ FEHLER beim Webhook-Versand: {str(webhook_err)}")

@app.post("/api/v1/fcc_agent_bluecollar")
async def main(request: AddressRequest, background_tasks: BackgroundTasks):
    logger.info(f"📥 Request erhalten: Store {request.store_id} ({request.broadband_type})")
    background_tasks.add_task(
        process_and_send_webhook, 
        request.store_id, 
        request.address, 
        request.lat, 
        request.lon,
        request.webhook_url,
        request.broadband_type
    )
    return {"status": "queued", "store_id": request.store_id}

if __name__ == "__main__":
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", 8001))
    logger.info(f"🚀 Starte API Server auf {api_host}:{api_port} (V4.5 - Browser-Use Native Edition)")
    uvicorn.run("agent_bluecollar_V4-5:app", host=api_host, port=api_port, log_level="info")