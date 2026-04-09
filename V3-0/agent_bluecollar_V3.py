# ----------------------------------------
# AGENT BLUECOLLAR V3: STEALTH PLAYWRIGHT EDITION
# 100% Deterministic, 0$ API Cost, Anti-Bot Bypass
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

is_headless = (os.getenv("HEADLESS") or "true").lower() == "true"
app = FastAPI()
agent_lock = asyncio.Lock()

class AddressRequest(BaseModel):
    store_id: float
    address: str
    lat: float
    lon: float
    webhook_url: str

async def process_and_send_webhook(store_id: float, address: str, lat: float, lon: float, webhook_url: str):
    encoded_address = urllib.parse.quote_plus(address)
    target_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
    
    async with agent_lock:
        print(f"\n--- [FAST SCRAPER] Starte für: {address} ---")
        start_time = time.time()
        final_payload = {}
        
        async with Stealth().use_async(async_playwright()) as p:
            try:
                browser = await p.chromium.launch(
                    headless=is_headless,
                    args=[
                        '--disable-http2',
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                    ]
                )
                
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                
                page = await context.new_page()
                
                
                print("Lade Seite...")
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
                except Exception as e:
                    print(f"⚠️ Hinweis beim Laden: {e}")
                
                print("Warte auf FCC Tabelle...")
                try:
                    # Ein Punkt (.) statt einer Raute (#), weil es eine CSS-Class ist!
                    await page.wait_for_selector(".table-mobileProviders", timeout=15000)
                    
                    markdown_table = await page.evaluate("""() => {
                        // Greife die exakte Tabelle anhand ihrer Klasse
                        const table = document.querySelector('.table-mobileProviders');
                        if (!table) return "EMPTY";
                        
                        let md = "";
                        for (let i = 0; i < table.rows.length; i++) {
                            const row = table.rows[i];
                            let rowData = [];
                            
                            for (let j = 0; j < row.cells.length; j++) {
                                let cell = row.cells[j];
                                
                                // 1. Bereinige den Text (z.B. versteckte FRN Nummern)
                                let cellText = cell.innerText.replace(/\\n/g, ' ').trim();
                                
                                // 2. BEREINIGUNG: Suche nach dem Häkchen-Icon!
                                // Wenn das Icon existiert, ist der Provider verfügbar
                                if (cell.querySelector('.fa-check')) {
                                    // Wenn auch Zahlen drin stehen (wie "7/1 35/3"), behalte sie
                                    let numbers = cellText.replace(/Click to filter map by provider/g, '').trim();
                                    cellText = numbers ? `YES (${numbers})` : "YES";
                                } else if (cellText.includes("Click to filter")) {
                                    // Falls der Text da ist, aber kein Häkchen (Fallback)
                                    cellText = "";
                                }
                                
                                rowData.push(cellText);
                            }
                            md += "| " + rowData.join(" | ") + " |\\n";
                            
                            // Markdown Trennlinie nach dem Header
                            if (i === 0) {
                                let separator = Array(row.cells.length).fill("---");
                                md += "| " + separator.join(" | ") + " |\\n";
                            }
                        }
                        return md.trim();
                    }""")
                    
                except Exception as wait_err:
                    print(f"❌ Keine Tabelle gefunden: {wait_err}")
                    markdown_table = "EMPTY"
                
                await browser.close()
                
                duration_seconds = round(time.time() - start_time, 2)
                print(f"⏱️ DAUER: {duration_seconds} Sekunden | {address}")
                
                providers_array = [] if markdown_table == "EMPTY" else [markdown_table]
                
                final_payload = {
                    "store_id": store_id,
                    "address": address,
                    "status": "success",
                    "providers": providers_array,
                    "usage": {
                        "model": "pure-playwright-stealth (No AI)",
                        "duration_seconds": duration_seconds,
                        "total_cost": 0.0, 
                    }
                }
                
            except Exception as e:
                print(f"⚠️ FEHLER bei {address}: {str(e)}")
                final_payload = {
                    "store_id": store_id, "address": address, 
                    "status": "error", "message": str(e), 
                    "providers": [], "usage": {}
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
        request.webhook_url
    )
    return {
        "status": "queued",
        "store_id": request.store_id,
        "message": "Fast Playwright Scraper started."
    }

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", 8001))
    print(f"🚀 Starte API Server auf {api_host}:{api_port} (Pure Playwright Mode)")
    uvicorn.run(app, host=api_host, port=api_port)