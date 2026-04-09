# ----------------------------------------
# AGENT BLUECOLLAR V1.7: HTML Scraper & Token Optimization
# Optimiert für n8n, Docker und GPT-5-nano
# ----------------------------------------

import os
import sys
import asyncio
import json
import inspect
import urllib.parse
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from browser_use import BrowserProfile, Browser
from browser_use import Agent, ChatOpenAI
from fastapi import FastAPI
import uvicorn

# Lädt Umgebungsvariablen aus der .env Datei
load_dotenv()

# ----------------------------------------
# SICHERE UMWELTVARIABLEN (FALLBACKS)
# Das 'or' sorgt dafür, dass leere Strings ("") ignoriert werden und der Fallback greift.
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
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ],
    chromium_sandbox=False,
    devtools=False,
    
    minimum_wait_page_load_time=0.5,            
    wait_for_network_idle_page_load_time=0.5,    
    wait_between_actions=1.0,                    
    deterministic_rendering=False,               

    highlight_elements=True,                     
    paint_order_filtering=True,                  
)

llm = ChatOpenAI(model=llm_model_name, temperature=llm_temperature)

app = FastAPI()
agent_lock = asyncio.Lock()

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
    
    encoded_address = urllib.parse.quote_plus(address)
    target_url = f"https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full={encoded_address}&lon={lon}&lat={lat}&zoom=15.00&env=0&tech=tech4g"
    
    async with agent_lock:
        browser = Browser(browser_profile=profile)
        print(f"\n--- Starte Scraping (Direct URL) für: {address} ---")
        print(f"🔗 Target URL: {target_url}")
        
        task = f"""
                ### STRICT STATE-MACHINE SOP ###
                Execute sequentially. Verify state before proceeding. Do not hallucinate steps.

                STATE 1: DIRECT LOAD
                - Go directly to this URL: {target_url}
                - CRITICAL: WAIT AT LEAST 6 SECONDS for the page API to render the table. Do not rush.

                STATE 2: EXTRACT 
                - Use the `extract` tool EXACTLY ONCE on the 'table-mobileProviders' table.
                - CRITICAL QUERY: Your query MUST be exactly: "Extract the full 'table-mobileProviders' as a RAW MARKDOWN TABLE. Include all columns and all rows. DO NOT summarize."
                - CRITICAL INSTRUCTION: As soon as you get the Markdown result, your VERY NEXT ACTION MUST BE STATE 3. DO NOT evaluate. DO NOT extract again.

                STATE 3: FINISH (TERMINAL STATE)
                - You MUST immediately trigger your `done` tool to finish the task.
                - Pass ONLY the exact, raw Markdown string from STATE 2 into the `text` parameter of your `done` tool. 
                - DO NOT write JSON. DO NOT write prose. ONLY the raw Markdown table.

                STATE 4: FAIL-SAFE
                - IF the table never loads or you get stuck: Trigger your `done` tool and pass EXACTLY this word into the `text` parameter: EMPTY
                """

        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            calculate_cost=True
        )
        
        try:
            # --- TIMER START ---
            start_time = time.time()

            history = await agent.run(max_steps=max_agent_steps)

            # --- TIMER STOP ---
            end_time = time.time()
            duration_seconds = round(end_time - start_time, 2)

            # --- 1. ERGEBNIS & USAGE DATA SAMMELN ---
            res_str = history.final_result() if hasattr(history, 'final_result') else None
        
            usage_data = {}
            if hasattr(agent, 'token_cost_service') and agent.token_cost_service:
                summary = agent.token_cost_service.get_usage_summary()
                
                if inspect.iscoroutine(summary):
                    summary = await summary
                    
                # ACHTUNG: Das hier MUSS auf dieser Einrückungsebene stehen (außerhalb des if-coroutine Blocks)
                print("\n" + "="*50)
                print(f"💰 USAGE SUMMARY FOR: {address}")
                print(summary)
                print(f"⏱️ DAUER: {duration_seconds} Sekunden")
                print("="*50 + "\n")

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
                
            # --- 2. AUSWERTUNG ---
            if not res_str:
                return {
                    "store_id": store_id, 
                    "address": address, 
                    "status": "error", 
                    "message": "Agent finished but returned no content.", 
                    "providers": [],
                    "usage": usage_data
                }

            clean_text = res_str.replace('```markdown', '').replace('```', '').strip()
                
            if clean_text == "EMPTY":
                providers_array = []
            else:
                providers_array = [clean_text]
                    
            return {
                "store_id": store_id,
                "address": address,
                "status": "success",
                "providers": providers_array,
                "usage": usage_data
            }
                
        except Exception as e:
            return {
                "store_id": store_id, 
                "address": address, 
                "status": "error", 
                "message": f"Agent execution failed: {str(e)}", 
                "providers": [],
                "usage": {}
            }

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", 8001))
    print(f"🚀 Starte API Server auf {api_host}:{api_port} (Headless: {is_headless})")
    uvicorn.run(app, host=api_host, port=api_port)