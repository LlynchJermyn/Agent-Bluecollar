# ----------------------------------------
# AGENT BLUECOLLAR V4.2: THE ULTIMATE FCC SCRAPER
# Dual-Mode (Fixed & Mobile) | Angular-Proof | Safari Stealth | No LLM Costs
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

# Das Datenmodell für den eingehenden n8n Request
class AddressRequest(BaseModel):
    store_id: float
    address: str
    lat: float
    lon: float
    webhook_url: str
    broadband_type: str = "mobile"  # Erwartet "fixed" oder "mobile" (Standard: mobile)

async def process_and_send_webhook(store_id: float, address: str, lat: float, lon: float, webhook_url: str, broadband_type: str):
    broadband_type = broadband_type.lower()
    encoded_address = urllib.parse.quote_plus(address)
    
    # --- DYNAMISCHE URL GENERIERUNG ---
    if broadband_type == "fixed":
        # NEU: Habe &br=r&speed=100_20 hinzugefügt, wie in deinem Beispiel!
        target_url = f"https://broadbandmap.fcc.gov/location-summary/fixed?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&br=r&speed=100_20&tech=1_2_3_6_7"
        print(f"\n--- [FAST SCRAPER] Starte FIXED Broadband für: {address} ---")
        print(f"🔗 DEBUG URL: {target_url}")
    else:
        target_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
        print(f"\n--- [FAST SCRAPER] Starte MOBILE Broadband für: {address} ---")
        print(f"🔗 DEBUG URL: {target_url}")
    
    # Warteschlangen-Schloss: Jede Adresse wird sauber nacheinander verarbeitet
    async with agent_lock:
        start_time = time.time()
        final_payload = {}
        
        # Den Browser mit Tarnkappe (Stealth) starten
        async with Stealth().use_async(async_playwright()) as p:
            try:
                browser = await p.chromium.launch(
                    channel="chrome", # Zwingend: Echten Chrome nutzen, um Signal 11 Crash zu vermeiden
                    headless=is_headless,
                    args=[
                        '--disable-http2',
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                    ]
                )
                
                # DER SAFARI-MAC SPOOFER: Wir tarnen uns als Apple Safari Browser!
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
                    viewport={'width': 1920, 'height': 1080},
                    is_mobile=False,
                    has_touch=False
                )
                
                page = await context.new_page()
                
                print(f"Lade Seite ({broadband_type.upper()})...")
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
                except Exception as e:
                    print(f"⚠️ Hinweis beim Laden (Ignoriert): {e}")
                
                print("Warte auf FCC API Daten...")
                await page.wait_for_timeout(4000) # Kurze Grundladezeit
                
                try:
                    # --- DER ANGULAR-PROOF POLLING MECHANISMUS ---
                    # Wir injizieren JS, das die Seite so lange scannt, bis die Tabelle wirklich fertig gebaut ist.
                    if broadband_type == "fixed":
                        await page.wait_for_function("""
                            () => {
                                const tables = document.querySelectorAll('table');
                                for (let t of tables) {
                                    // FIXED Tabelle muss 'Technology' beinhalten
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
                                    // MOBILE Tabelle muss '5G-NR' oder '4G LTE' beinhalten
                                    if (t.innerText.includes('Provider') && (t.innerText.includes('5G-NR') || t.innerText.includes('4G LTE'))) {
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """, timeout=20000)
                    
                    print("Tabelle erfolgreich auf dem Bildschirm erkannt! Starte Extraktion...")
                    
                    # --- DUAL-MODE JAVASCRIPT EXTRAKTOR ---
                    # Hier wird die Variable 'broadband_type' an das Skript übergeben
                    markdown_table = await page.evaluate("""(type) => {
                        const tables = document.querySelectorAll('table');
                        let target = null;
                        
                        // Richtige Tabelle greifen
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
                            
                            // Sonderfall: Trenner-Zeilen (wie "Business-only Service")
                            if (row.cells.length === 1 && row.cells[0].colSpan > 1) {
                                rowData.push("**" + row.cells[0].innerText.trim() + "**");
                                for (let k = 1; k < colsCount; k++) rowData.push("");
                                md += "| " + rowData.join(" | ") + " |\\n";
                                continue;
                            }
                            
                            for (let j = 0; j < row.cells.length; j++) {
                                let cell = row.cells[j];
                                let cellText = cell.innerText.replace(/\\n/g, ' ').trim();
                                
                                // GEMEINSAME BEREINIGUNG: 'Holding Company' und 'FRN' Müll entfernen (Spalte 0)
                                if (j === 0 && cellText.includes("Holding Company")) {
                                    cellText = cellText.split("Holding Company")[0].trim();
                                }
                                
                                // SPEZIFISCHE BEREINIGUNG: MOBILE (Häkchen-Logik)
                                if (type === "mobile") {
                                    if (cell.querySelector('.fa-check')) {
                                        let numbers = cellText.replace(/Click to filter map by provider/g, '').trim();
                                        cellText = numbers ? `YES (${numbers})` : "YES";
                                    } else if (cellText.includes("Click to filter")) {
                                        cellText = "";
                                    }
                                } 
                                // SPEZIFISCHE BEREINIGUNG: FIXED (Zahlen bleiben unangetastet)
                                else if (type === "fixed") {
                                    // Bei Fixed gibt es keine Icons zu bereinigen, die Zahlen (Down/Up) bleiben pur.
                                }
                                
                                rowData.push(cellText);
                            }
                            md += "| " + rowData.join(" | ") + " |\\n";
                            
                            // Markdown Trennlinie nach dem Header
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

        # --- WEBHOOK VERSAND AN n8n ---
        try:
            print(f"📤 Sende Ergebnis an Webhook...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(webhook_url, json=final_payload)
                response.raise_for_status()
                print(f"✅ Webhook erfolgreich übermittelt!")
        except Exception as webhook_err:
            print(f"❌ FEHLER beim Webhook-Versand: {str(webhook_err)}")

# --- FASTAPI ENDPOINT ---
@app.post("/api/v1/fcc_agent_bluecollar")
async def main(request: AddressRequest, background_tasks: BackgroundTasks):
    # Job in den Hintergrund legen, damit n8n sofort eine 200 OK Antwort bekommt
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
    print(f"🚀 Starte API Server auf {api_host}:{api_port} (Universal Stealth Mode V4.2)")
    uvicorn.run(app, host=api_host, port=api_port)