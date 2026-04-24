# ----------------------------------------
# AGENT BLUECOLLAR V4.4: THE PERFECT EXTRACTOR
# Struktur-angepasstes Scraping für Mobile UND Fixed Broadband Tabellen
# ----------------------------------------

import os
import sys
import asyncio
import urllib.parse
import time
import httpx
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks
import uvicorn

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

load_dotenv()

# Konfiguration
is_headless = (os.getenv("HEADLESS") or "true").lower() == "true"
app = FastAPI()
agent_lock = asyncio.Lock()

class AddressRequest(BaseModel):
    store_id: float
    address: str
    lat: float
    lon: float
    webhook_url: str
    broadband_type: str = "mobile"

async def process_and_send_webhook(store_id: float, address: str, lat: float, lon: float, webhook_url: str, broadband_type: str):
    broadband_type = broadband_type.lower()
    encoded_address = urllib.parse.quote_plus(address)
    
    async with agent_lock:
        start_time = time.time()
        final_payload = {}
        
        async with Stealth().use_async(async_playwright()) as p:
            try:
                browser = await p.chromium.launch(
                    channel="chrome", 
                    headless=is_headless,
                    args=[
                        '--disable-http2',
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                    ]
                )
                
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
                    viewport={'width': 1920, 'height': 1080},
                    is_mobile=False,
                    has_touch=False
                )
                
                page = await context.new_page()
                
                # ==========================================
                # NAVIGATIONSLOGIK
                # ==========================================
                if broadband_type == "fixed":
                    print(f"\n--- [FAST SCRAPER] Starte FIXED Broadband via Homepage-Suche für: {address} ---")
                    home_url = "https://broadbandmap.fcc.gov/home?version=jun2025"
                    print(f"🔗 DEBUG URL (Start): {home_url}")
                    
                    try:
                        await page.goto(home_url, wait_until="domcontentloaded", timeout=40000)
                        await page.wait_for_selector("#addrSearch", timeout=15000)
                        
                        await page.locator("#addrSearch").type(address, delay=50)
                        
                        dropdown_item = page.locator(".search-results button, .search-results .dropdown-item").first
                        await dropdown_item.wait_for(state="visible", timeout=15000)
                        await dropdown_item.click()
                        
                        await page.wait_for_url("**/location-summary/**", timeout=20000)
                        
                        try:
                            await page.locator("a.nav-link:has-text('Fixed Broadband')").click(timeout=5000)
                        except:
                            pass 
                            
                    except Exception as nav_err:
                        print(f"⚠️ Navigation fehlgeschlagen: {nav_err}")
                
                else:
                    target_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
                    print(f"\n--- [FAST SCRAPER] Starte MOBILE Broadband direkt für: {address} ---")
                    print(f"🔗 DEBUG URL: {target_url}")
                    try:
                        await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
                    except Exception as e:
                        print(f"⚠️ Hinweis beim Laden (Ignoriert): {e}")
                
                # ==========================================
                # ANGULAR POLLING (Warten auf echte Daten)
                # ==========================================
                print("Warte auf FCC API Daten (Polling-Modus)...")
                await page.wait_for_timeout(4000) 
                
                try:
                    if broadband_type == "fixed":
                        await page.wait_for_function("""
                            () => {
                                const tables = document.querySelectorAll('table');
                                for (let t of tables) {
                                    if (t.innerText.includes('Technology') && t.innerText.includes('Provider')) {
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """, timeout=25000)
                    else:
                        await page.wait_for_function("""
                            () => {
                                const tables = document.querySelectorAll('table');
                                for (let t of tables) {
                                    if (t.innerText.includes('Provider') && (t.innerText.includes('5G-NR') || t.innerText.includes('4G LTE'))) {
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """, timeout=20000)
                    
                    print(f"Tabelle ({broadband_type.upper()}) erfolgreich erkannt! Starte strukturierte Extraktion...")
                    
                    # ==========================================
                    # DIE INTELLIGENTE EXTRAKTION (FIXED vs MOBILE)
                    # ==========================================
                    markdown_table = await page.evaluate("""(type) => {
                        const tables = document.querySelectorAll('table');
                        let target = null;
                        
                        for (let t of tables) {
                            if (t.innerText.includes('Provider')) {
                                target = t;
                                break;
                            }
                        }
                        if (!target) return "EMPTY";
                        
                        let md = "";
                        let colsCount = target.rows[0].cells.length;
                        
                        for (let i = 0; i < target.rows.length; i++) {
                            const row = target.rows[i];
                            let rowData = [];
                            
                            // Sonderfall: Trenner-Zeilen (z.B. "Business-only Service" bei Fixed)
                            if (row.cells.length === 1 && row.cells[0].colSpan > 1) {
                                let businessText = row.cells[0].innerText.replace(/\\n/g, ' ').trim();
                                rowData.push("**" + businessText + "**");
                                // Fülle die restlichen Spalten auf, damit die Markdown-Tabelle nicht kaputt geht
                                for (let k = 1; k < colsCount; k++) rowData.push("---");
                                md += "| " + rowData.join(" | ") + " |\\n";
                                continue;
                            }
                            
                            for (let j = 0; j < row.cells.length; j++) {
                                let cell = row.cells[j];
                                // Text greifen und doppelte Leerzeichen/Zeilenumbrüche entfernen
                                let cellText = cell.innerText.replace(/\\n/g, ' ').replace(/\\s+/g, ' ').trim();
                                
                                // GEMEINSAME BEREINIGUNG: 'Holding Company' Müll aus Spalte 0 (Provider) entfernen
                                if (j === 0 && cellText.includes("Holding Company")) {
                                    cellText = cellText.split("Holding Company")[0].trim();
                                }
                                
                                // SPEZIFISCHE BEREINIGUNG: MOBILE (Häkchen-Logik)
                                if (type === "mobile") {
                                    if (cell.querySelector('.fa-check')) {
                                        let numbers = cellText.replace(/Click to filter map by provider/ig, '').trim();
                                        cellText = numbers ? `YES (${numbers})` : "YES";
                                    } else if (cellText.includes("Click to filter")) {
                                        cellText = "";
                                    }
                                } 
                                // SPEZIFISCHE BEREINIGUNG: FIXED (Geschwindigkeiten & Technologie)
                                else if (type === "fixed") {
                                    // Header formatieren, falls "Down" und "(Mbps)" zusammenkleben
                                    if (i === 0) {
                                        if (cellText.includes("Down")) cellText = "Down (Mbps)";
                                        if (cellText.includes("Up")) cellText = "Up (Mbps)";
                                    }
                                    // Bei Fixed bleibt der Rest (Zahlen und Technologie-Strings wie "GSO Satellite") pur!
                                }
                                
                                rowData.push(cellText);
                            }
                            md += "| " + rowData.join(" | ") + " |\\n";
                            
                            // Markdown Trennlinie nach dem Header einfügen
                            if (i === 0) {
                                let separator = Array(colsCount).fill("---");
                                md += "| " + separator.join(" | ") + " |\\n";
                            }
                        }
                        return md.trim();
                    }""", broadband_type)
                    
                except Exception as wait_err:
                    print(f"❌ Keine Tabelle gefunden (Timeout): {wait_err}")
                    markdown_table = "EMPTY"
                
                await browser.close()
                
                duration_seconds = round(time.time() - start_time, 2)
                print(f"⏱️ DAUER: {duration_seconds} Sekunden | {address}")
                
                providers_array = [] if markdown_table == "EMPTY" else [markdown_table]
                
                final_payload = {
                    "store_id": store_id,
                    "address": address,
                    "status": "success",
                    "broadband_type": broadband_type,
                    "providers": providers_array,
                    "usage": {
                        "model": f"pure-playwright-stealth ({broadband_type.upper()})",
                        "duration_seconds": duration_seconds,
                        "total_cost": 0.0, 
                        "api_latency_bypassed": True
                    }
                }
                
            except Exception as e:
                print(f"⚠️ FEHLER bei {address}: {str(e)}")
                final_payload = {
                    "store_id": store_id, "address": address, 
                    "status": "error", "broadband_type": broadband_type, 
                    "message": str(e), "providers": [], "usage": {}
                }

        try:
            print(f"📤 Sende Ergebnis an Webhook...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(webhook_url, json=final_payload)
                response.raise_for_status()
                print(f"✅ Webhook erfolgreich übermittelt!")
        except Exception as webhook_err:
            print(f"❌ FEHLER beim Webhook-Versand: {str(webhook_err)}")

@app.post("/api/v1/fcc_agent_bluecollar")
async def main(request: AddressRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        process_and_send_webhook, 
        request.store_id, 
        request.address, 
        request.lat, 
        request.lon,
        request.webhook_url,
        request.broadband_type
    )
    return {
        "status": "queued",
        "store_id": request.store_id,
        "type": request.broadband_type,
        "message": f"Fast Scraper ({request.broadband_type.upper()}) started."
    }

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", 8001))
    print(f"🚀 Starte API Server auf {api_host}:{api_port} (V4.4 - The Perfect Extractor)")
    uvicorn.run(app, host=api_host, port=api_port)