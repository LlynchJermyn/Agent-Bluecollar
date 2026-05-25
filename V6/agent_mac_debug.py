import sys
import time
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import uvicorn
from playwright.sync_api import sync_playwright

app = FastAPI()

class AddressRequest(BaseModel):
    store_id: float
    address: str
    lat: float
    lon: float
    webhook_url: str
    broadband_type: str = "mobile"

def run_scraper(store_id, address, lat, lon, webhook_url, broadband_type):
    with sync_playwright() as p:
        # HEADLESS=False ist hier der Schlüssel für deine GUI
        browser = p.chromium.launch(headless=False, args=['--start-maximized'])
        page = browser.new_page()
        
        # URL laden
        base_url = "https://broadbandmap.fcc.gov/location-summary/fixed" if broadband_type == "fixed" else "https://broadbandmap.fcc.gov/location-summary/mobile"
        url = f"{base_url}?version=jun2025&addr_full={address}&lon={lon}&lat={lat}&zoom=16.99"
        
        print(f"[{store_id}] Navigiere zu: {url}")
        page.goto(url)
        
        # Warte auf das Canvas
        page.wait_for_selector("canvas")
        time.sleep(5) # Gib der Karte Zeit zum Rendern
        
        # Optische Mitte des gesamten Bildschirms/Canvas
        # Da du eine GUI hast, nutzen wir die Bildschirmmitte
        viewport = page.viewport_size
        cx, cy = viewport['width'] / 2, viewport['height'] / 2
        
        print(f"[{store_id}] Versuche Klick in Mitte (X={cx}, Y={cy})")
        
        # Raster für den Fall, dass der Punkt 10-20px daneben liegt
        offsets = [(0,0), (15,0), (-15,0), (0,15), (0,-15), (15,15), (-15,-15)]
        
        for ox, oy in offsets:
            page.mouse.click(cx + ox, cy + oy)
            time.sleep(2) # Genug Zeit, damit die URL umschlägt
            if "location_id=" in page.url:
                print(f"[{store_id}] ✅ Punkt getroffen!")
                break
        
        # Extraktion
        time.sleep(3)
        # Hier kannst du jetzt live sehen, ob die Tabelle erscheint
        print(f"[{store_id}] Extraktion beendet.")
        browser.close()

@app.post("/api/v1/fcc_agent_bluecollar")
async def main(request: AddressRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper, request.store_id, request.address, request.lat, request.lon, request.webhook_url, request.broadband_type)
    return {"status": "started"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)