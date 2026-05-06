# ----------------------------------------
# AGENT BLUECOLLAR V4.5: DEBUG & PARALLEL EDITION
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
    logger.info("Startup complete: asyncio.Lock() initialisiert.")
    yield

app = FastAPI(lifespan=lifespan)

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
    resolved_url = "N/A" # Initialwert für Debugging
    
    async with agent_lock:
        start_time = time.time()
        final_payload = {}
        
        async with Stealth().use_async(async_playwright()) as p:
            try:
                browser = await p.chromium.launch(
                    headless=is_headless,
                    args=['--no-sandbox', '--disable-dev-shm-usage', '--mute-audio']
                )
                context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
                page = await context.new_page()
                
                if broadband_type == "fixed":
                    await page.goto("https://broadbandmap.fcc.gov/home?version=jun2025", wait_until="domcontentloaded", timeout=40000)
                    await page.wait_for_selector("#addrSearch", state="visible", timeout=15000)
                    await page.locator("#addrSearch").press_sequentially(address, delay=40)
                    
                    dropdown = page.locator(".search-results button, .search-results .dropdown-item").first
                    await dropdown.wait_for(state="visible", timeout=20000)
                    await dropdown.hover()
                    await page.wait_for_timeout(400)
                    
                    async with page.expect_navigation(timeout=30000):
                        await dropdown.click(force=True)
                    
                    # Redirect-URL für Debugging sichern
                    resolved_url = page.url
                    logger.info(f"[{store_id}] 🔗 Resolved URL: {resolved_url}")
                    
                    try:
                        await page.locator("a.nav-link:has-text('Fixed Broadband')").click(timeout=5000)
                    except: pass 
                
                else:
                    resolved_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
                    await page.goto(resolved_url, wait_until="domcontentloaded", timeout=40000)

                # Polling mit Fast-Fail und reduziertem Timeout
                try:
                    await page.wait_for_function("""
                        () => {
                            const hasTable = Array.from(document.querySelectorAll('table')).some(t => t.rows.length > 1 && t.innerText.includes('Provider'));
                            const noData = document.body.innerText.includes('Not Served') || document.body.innerText.includes('0 Providers') || document.body.innerText.includes('No data available');
                            return hasTable || noData;
                        }
                    """, timeout=15000, polling=500) # Timeout auf 15s reduziert
                    
                    markdown_table = await page.evaluate("""(type) => {
                        const tables = Array.from(document.querySelectorAll('table'));
                        let target = tables.reduce((prev, curr) => (prev.rows.length > curr.rows.length) ? prev : curr, {rows: []});
                        if (!target || target.rows.length <= 1) return "EMPTY";
                        
                        let md = "";
                        for (let i = 0; i < target.rows.length; i++) {
                            let rowData = Array.from(target.rows[i].cells).map(c => c.innerText.replace(/\\n/g, ' ').trim());
                            md += "| " + rowData.join(" | ") + " |\\n";
                            if (i === 0) md += "| " + Array(target.rows[0].cells.length).fill("---").join(" | ") + " |\\n";
                        }
                        return md;
                    }""", broadband_type)
                except:
                    markdown_table = "EMPTY"
                
                await browser.close()
                duration = round(time.time() - start_time, 2)
                
                final_payload = {
                    "store_id": store_id,
                    "address": address,
                    "resolved_url": resolved_url, # NEU: Für Debugging im Webhook
                    "status": "success",
                    "broadband_type": broadband_type,
                    "providers": [] if markdown_table == "EMPTY" else [markdown_table],
                    "usage": {"duration_seconds": duration}
                }
                
            except Exception as e:
                final_payload = {"store_id": store_id, "resolved_url": resolved_url, "broadband_type": broadband_type, "status": "error", "message": str(e)}

        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(webhook_url, json=final_payload)

@app.post("/api/v1/fcc_agent_bluecollar")
async def main(request: AddressRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(process_and_send_webhook, request.store_id, request.address, request.lat, request.lon, request.webhook_url, request.broadband_type)
    return {"status": "queued", "store_id": request.store_id}

if __name__ == "__main__":
    uvicorn.run("agent_bluecollar_V4-5:app", host="0.0.0.0", port=int(os.getenv("API_PORT", 8001)))