# ----------------------------------------
# AGENT BLUECOLLAR V1.5: HTML Scraper & Token Optimization
# Optimiert für n8n, Docker und GPT-4o 
# ----------------------------------------

import os
import sys
import asyncio
import json
import inspect
import urllib.parse
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from browser_use import BrowserProfile, Browser
from browser_use import Agent, ChatOpenAI
from fastapi import FastAPI
import uvicorn

# Lädt Umgebungsvariablen aus der .env Datei (z.B. API Keys, Host, Port)
load_dotenv()

# ----------------------------------------
# DOCKER & BROWSER KONFIGURATION
# ----------------------------------------
# HEADLESS: Steuert, ob der Browser sichtbar ist. In Docker IMMER 'true'!
is_headless = os.getenv("HEADLESS", "true").lower() == "true"

profile = BrowserProfile(
    # 1. Anzeige & Erscheinungsbild
    headless=is_headless,
    window_size={'width': 1920, 'height': 1080},
    viewport={'width': 1920, 'height': 1080},
    window_position={'width': 0, 'height': 0},   
    no_viewport=None,                            
    device_scale_factor=1.0,                     

    # 2. Browser Start & Chromium Args
    # Diese Flags sind überlebenswichtig, um Firewalls zu umgehen und RAM-Crashes im Docker-Container zu verhindern.
    args=[
        '--disable-http2',                               # Umgeht den ERR_HTTP2_PROTOCOL_ERROR
        '--disable-blink-features=AutomationControlled', # Verschleiert den Bot-Status
        '--no-sandbox',                                  # Zwingend für Docker
        '--disable-dev-shm-usage',                       # Verhindert Speicherüberlauf in Docker (/dev/shm)
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ],
    chromium_sandbox=False,                              # In Docker auf False setzen
    devtools=False,
    
    # 3. Timing & Performance
    minimum_wait_page_load_time=0.5,            
    wait_for_network_idle_page_load_time=0.5,    
    wait_between_actions=1.0,                    
    deterministic_rendering=False,               

    # 4. AI & Interaktion
    highlight_elements=True,                     
    paint_order_filtering=True,                  
)

# ----------------------------------------
# LLM & AGENT CONFIGURATION (Variabilisiert für Docker)
# ----------------------------------------
llm_model_name = os.getenv("LLM_MODEL", "gpt-4o")
llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
max_agent_steps = int(os.getenv("MAX_STEPS", "8")) # Steuert das Limit an Iterationen pro Adresse

llm = ChatOpenAI(model=llm_model_name, temperature=llm_temperature)

app = FastAPI()
agent_lock = asyncio.Lock()

# Neues Request-Modell inklusive Koordinaten! HIER NOCH DIE STORE_ID abfragen, damit wir die Ergebnisse später besser zuordnen können.
class AddressRequest(BaseModel):
    store_id: float
    address: str
    lat: float
    lon: float

@app.post("/api/v1/fcc_agent_bluecollar")
async def main(request: AddressRequest):
    store_id = request.store_id 
    address = request.address
    lat = request.lat
    lon = request.lon
    
    # URL dynamisch zusammenbauen
    encoded_address = urllib.parse.quote_plus(address)
    target_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
    
    async with agent_lock:
        browser = Browser(browser_profile=profile)
        print(f"\n--- Starte Scraping (Direct URL) für: {address} ---")
        print(f"🔗 Target URL: {target_url}")
        
        # ----------------------------------------
        # ULTRA-FAST DIRECT URL PROMPT
        # ----------------------------------------
        task = f"""
                    ### STRICT STATE-MACHINE SOP ###
                        Execute sequentially. Verify state before proceeding. Do not hallucinate steps.

                        STATE 1: DIRECT LOAD
                        - Go directly to this URL: {target_url}
                        - CRITICAL: WAIT AT LEAST 6 SECONDS for the page API to render the table. Do not rush.

                        STATE 2: EXTRACT & EVALUATE
                        - Use the `extract` tool on the 'table-mobileProviders' table.
                        - IF the result is empty or has 0 providers: Click the center of the map canvas, wait 5 seconds, and extract one more time.
                        - IF the result contains a Markdown table with provider data: Proceed IMMEDIATELY to STATE 3. DO NOT extract again!

                        STATE 3: JSON EXPORT (TERMINAL STATE)
                        - You MUST immediately trigger your `done` tool to finish the task.
                        - Pass EXACTLY the following JSON structure into the `text` parameter of your `done` tool. Do not add prose or explanations.
                        - Hardcode "{address}" and "{store_id}" into the respective keys.
                        - Put the exact, raw Markdown string from STATE 2 into the "providers" array. Escape all quotes and newlines (\\n).

                        STATE 4: ERROR HANDLING & FAIL-SAFE (CRITICAL)
                        - IF the table never loads or you get stuck: DO NOT write apologies or status updates.
                        - You MUST trigger your `done` tool and pass EXACTLY this fallback JSON into the `text` parameter:
                        {{
                            "store_id": "{store_id}",
                            "address": "{address}",
                            "providers": []
                        }}

                        Expected Success JSON format:
                        {{
                            "store_id": "{store_id}",
                            "address": "{address}",
                            "providers": [
                                "<RAW_MARKDOWN_STRING_ESCAPED>"
                            ]
                        }}
                """

        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            calculate_cost=True
        )
        
        try:
            history = await agent.run(max_steps=max_agent_steps)
            res_str = history.final_result() if hasattr(history, 'final_result') else None
            
            if hasattr(agent, 'token_cost_service') and agent.token_cost_service:
                summary = agent.token_cost_service.get_usage_summary()
                if inspect.iscoroutine(summary):
                    summary = await summary
                print("\n" + "="*50)
                print(f"💰 USAGE SUMMARY FOR: {address}")
                print(summary)
                print("="*50 + "\n")
            
            # store_id in den leeren Fallback eingefügt
            if not res_str:
                return {"store_id": store_id, "address": address, "status": "error", "message": "Agent finished but returned no content.", "providers": []}

            try:
                clean_json = res_str.replace('```json', '').replace('```', '').strip()
                parsed_data = json.loads(clean_json)
                
                # Python erzwingt die store_id, falls das LLM sie vergessen hat
                parsed_data["store_id"] = store_id 
                
                if "providers" not in parsed_data:
                    parsed_data["providers"] = []
                parsed_data["status"] = "success"
                return parsed_data
                
            except json.JSONDecodeError:
                # store_id in den JSON-Fehler-Fallback eingefügt
                return {"store_id": store_id, "address": address, "status": "parsing_needed", "raw_result": res_str, "providers": []}
                
        except Exception as e:
            # store_id in den globalen Error-Fallback eingefügt
            return {"store_id": store_id, "address": address, "status": "error", "message": f"Agent execution failed: {str(e)}", "providers": []}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", 8001))
    print(f"🚀 Starte API Server auf {api_host}:{api_port} (Headless: {is_headless})")
    uvicorn.run(app, host=api_host, port=api_port)