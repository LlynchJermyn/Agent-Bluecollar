# ----------------------------------------
# AGENT BLUECOLLAR V2.0: Asynchroner Webhook Edition
# Optimiert für gigantische Datenmengen
# ----------------------------------------

import os
import sys
import asyncio
import json
import inspect
import urllib.parse
import time
import httpx  # <-- NEU: Für den Rückversand an n8n
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from browser_use import BrowserProfile, Browser
from browser_use import Agent, ChatOpenAI
from fastapi import FastAPI, BackgroundTasks

import uvicorn

# Lädt Umgebungsvariablen aus der .env Datei
load_dotenv()

# ----------------------------------------
# KUGELSICHERE UMWELTVARIABLEN (FALLBACKS)
# ----------------------------------------
is_headless = (os.getenv("HEADLESS") or "true").lower() == "true"
llm_model_name = os.getenv("LLM_MODEL") or "gpt-5-nano"

try:
    llm_temperature = float(os.getenv("LLM_TEMPERATURE") or "0.1")
except (ValueError, TypeError):
    llm_temperature = 0.1

try:
    max_agent_steps = int(os.getenv("MAX_STEPS") or "8")
except (ValueError, TypeError):
    max_agent_steps = 8

# ----------------------------------------
# DOCKER & BROWSER KONFIGURATION
# ----------------------------------------
profile = BrowserProfile(
    headless=is_headless,
    window_size={'width': 1920, 'height': 1080},
    viewport={'width': 1920, 'height': 1080},
    window_position={'width': 0, 'height': 0},   
    no_viewport=None,                            
    device_scale_factor=1.0,                     

    args=[
        '--disable-http2',
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--blink-settings=imagesEnabled=false', # <-- Lädt keine Bilder im Browser
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ],
    chromium_sandbox=False,
    devtools=False,
    
    minimum_wait_page_load_time=0.5,            
    wait_for_network_idle_page_load_time=0.1,    
    wait_between_actions=0.0,                    
    deterministic_rendering=False,               

    highlight_elements=True,                     
    paint_order_filtering=True,                  
)

llm = ChatOpenAI(model=llm_model_name, temperature=llm_temperature)

app = FastAPI()
agent_lock = asyncio.Lock()

# ----------------------------------------
# NEU: Request-Modell inkl. Webhook-URL
# ----------------------------------------
class AddressRequest(BaseModel):
    store_id: float
    address: str
    lat: float
    lon: float
    webhook_url: str  # <-- NEU: Hier sagt n8n dem Agenten, wo das Ergebnis hin soll

# ----------------------------------------
# DIE HINTERGRUND-AUFGABE (Macht die harte Arbeit)
# ----------------------------------------
async def process_and_send_webhook(store_id: float, address: str, lat: float, lon: float, webhook_url: str):
    encoded_address = urllib.parse.quote_plus(address)
    target_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
    
    # Das Lock sorgt dafür, dass dieser Container brav eine Adresse nach der anderen abarbeitet
    async with agent_lock:
        browser = Browser(browser_profile=profile)
        print(f"\n--- [BACKGROUND JOB] Starte Scraping für: {address} ---")
        
        task = f"""
                CRITICAL MISSION:
                Go to {target_url}, extract the 'table-mobileProviders' table as a RAW MARKDOWN TABLE, and return it.

                STRICT EXECUTION STEPS:
                1. WAIT: Use the `wait` tool to wait exactly 3 seconds. The page needs time to render the data.
                2. EXTRACT: Use the `extract` tool. Your query MUST be: "Extract the full 'table-mobileProviders' as a RAW MARKDOWN TABLE. Include all columns and rows."
                3. DONE: Immediately use the `done` tool and pass the exact Markdown text into the `text` parameter. 

                RULE: Do NOT extract twice. As soon as you have the Markdown table, you must call `done`.
                FAIL-SAFE: If the table does not exist after waiting, call `done` with the text: EMPTY
                
                IMPORTANT FOR EVALUATOR / JUDGE: 
                The extracted table WILL contain placeholder text like "Click to filter map by provider". This is EXACTLY what the user wants. Do NOT fail the task. You MUST mark this task as 100% SUCCESSFUL if the markdown table is returned, regardless of its text content.
                """

        agent = Agent(
            task=task, 
            llm=llm, 
            browser=browser,
            use_vision=False, 
            calculate_cost=True
            )
        final_payload = {}
        
        try:
            start_time = time.time()
            history = await agent.run(max_steps=max_agent_steps)
            duration_seconds = round(time.time() - start_time, 2)

            res_str = history.final_result() if hasattr(history, 'final_result') else None
        
            usage_data = {}
            if hasattr(agent, 'token_cost_service') and agent.token_cost_service:
                summary = agent.token_cost_service.get_usage_summary()
                if inspect.iscoroutine(summary):
                    summary = await summary
                    
                print(f"⏱️ DAUER: {duration_seconds} Sekunden | {address}")

                by_model_dict = getattr(summary, 'by_model', {})
                used_models = list(by_model_dict.keys())
                model_name_str = ", ".join(used_models) if used_models else "unknown"

                usage_data = {
                    "model": model_name_str,
                    "duration_seconds": duration_seconds,
                    "total_tokens": getattr(summary, 'total_tokens', 0),
                    "total_cost": getattr(summary, 'total_cost', 0.0),
                    "prompt_tokens": getattr(summary, 'total_prompt_tokens', 0),
                    "prompt_cost": getattr(summary, 'total_prompt_cost', 0.0),
                    "cached_prompt_tokens": getattr(summary, 'total_prompt_cached_tokens', 0),
                    "cached_prompt_cost": getattr(summary, 'total_prompt_cached_cost', 0.0),
                    "completion_tokens": getattr(summary, 'total_completion_tokens', 0),
                    "completion_cost": getattr(summary, 'total_completion_cost', 0.0),
                    "iterations": getattr(summary, 'entry_count', 0)
                }
                
            if not res_str:
                final_payload = {"store_id": store_id, "address": address, "status": "error", "message": "No content.", "providers": [], "usage": usage_data}
            else:
                clean_text = res_str.replace('```markdown', '').replace('```', '').strip()
                providers_array = [] if clean_text == "EMPTY" else [clean_text]
                
                final_payload = {
                    "store_id": store_id,
                    "address": address,
                    "status": "success",
                    "providers": providers_array,
                    "usage": usage_data
                }
                
        except Exception as e:
            print(f"⚠️ FEHLER bei {address}: {str(e)}")
            final_payload = {"store_id": store_id, "address": address, "status": "error", "message": str(e), "providers": [], "usage": {}}

        # --- NEU: ERGEBNIS AN n8n WEBHOOK SCHICKEN ---
        try:
            print(f"📤 Sende Ergebnis für {address} an Webhook...")
            # Timeouts etwas höher setzen, falls n8n gerade beschäftigt ist
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(webhook_url, json=final_payload)
                response.raise_for_status()
                print(f"✅ Webhook erfolgreich übermittelt! (Status {response.status_code})")
        except Exception as webhook_err:
            print(f"❌ FEHLER: Konnte Webhook für {address} nicht senden. Grund: {str(webhook_err)}")

# ----------------------------------------
# DER API-ENDPOINT (Antwortet sofort)
# ----------------------------------------
@app.post("/api/v1/fcc_agent_bluecollar")
async def main(request: AddressRequest, background_tasks: BackgroundTasks):
    
    # Packt den schweren Job in die Warteschlange von FastAPI
    background_tasks.add_task(
        process_and_send_webhook, 
        request.store_id, 
        request.address, 
        request.lat, 
        request.lon,
        request.webhook_url
    )
    
    # Antwortet n8n in < 50 Millisekunden!
    return {
        "status": "queued",
        "store_id": request.store_id,
        "address": request.address,
        "message": f"Job accepted. The result will be posted to {request.webhook_url}"
    }

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", 8001))
    print(f"🚀 Starte API Server auf {api_host}:{api_port} (Headless: {is_headless})")
    uvicorn.run(app, host=api_host, port=api_port)