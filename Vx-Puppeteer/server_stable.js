require('dotenv').config();
const express = require('express');
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const axios = require('axios');

puppeteer.use(StealthPlugin());

const app = express();
app.use(express.json());

const PORT = process.env.API_PORT || 8001;
const delay = ms => new Promise(res => setTimeout(res, ms));

// Mutex Lock für Docker RAM-Schutz
class Mutex {
    constructor() {
        this.queue = [];
        this.locked = false;
    }
    lock() {
        return new Promise(resolve => {
            if (this.locked) this.queue.push(resolve);
            else { this.locked = true; resolve(); }
        });
    }
    unlock() {
        if (this.queue.length > 0) this.queue.shift()();
        else this.locked = false;
    }
}
const agentLock = new Mutex();

async function humanizeMouse(page) {
    const startX = Math.floor(Math.random() * 500) + 100;
    const startY = Math.floor(Math.random() * 500) + 100;
    await page.mouse.move(startX, startY);
    const endX = Math.floor(Math.random() * 1000) + 200;
    const endY = Math.floor(Math.random() * 800) + 100;
    await page.mouse.move(endX, endY, { steps: Math.floor(Math.random() * 15) + 10 });
    await delay(Math.floor(Math.random() * 300) + 100);
}

function getRandomTypeDelay() {
    return Math.floor(Math.random() * (120 - 40 + 1)) + 40;
}

async function processAndSendWebhook(store_id, address, lat, lon, webhook_url, broadband_type) {
    broadband_type = broadband_type.toLowerCase();
    
    await agentLock.lock();
    const startTime = Date.now();
    let extractedData = "EMPTY";
    let resolvedUrl = "Nicht ermittelt";
    let browser = null;

    try {
        console.log(`\n--- [START] Xvfb Headed Workflow für Store ${store_id}: ${address} ---`);
        
        browser = await puppeteer.launch({
            headless: false, 
            executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || null,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--mute-audio',
                '--start-maximized',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--window-size=1920,1080'
            ],
            defaultViewport: null
        });
        
        const page = await browser.newPage();
        
        const subVersion = Math.floor(Math.random() * 100);
        await page.setUserAgent(`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.${subVersion} Safari/537.36`);
        await page.setExtraHTTPHeaders({ 'Accept-Language': 'en-US,en;q=0.9' });

        if (broadband_type === 'fixed') {
            console.log(`--- [PHASE 1] Suche Adresse ---`);
            
            await page.goto('https://broadbandmap.fcc.gov/home?version=jun2025', { waitUntil: 'domcontentloaded', timeout: 60000 });
            resolvedUrl = page.url();

            await page.waitForSelector('#addrSearch', { visible: true, timeout: 20000 });
            
            console.log("🖱️ Simuliere menschliche Mausbewegungen...");
            await humanizeMouse(page);
            
            console.log("⌨️ Tippe Adresse ein...");
            await page.click('#addrSearch');
            await page.evaluate(() => document.querySelector('#addrSearch').value = '');
            await page.type('#addrSearch', address, { delay: getRandomTypeDelay() });

            console.log("⏳ Warte auf Geocoder-Dropdown...");
            await page.waitForSelector('.search-results button, .search-results .dropdown-item', { visible: true, timeout: 30000 });
            await delay(Math.floor(Math.random() * 1000) + 800);
            
            console.log("🖱️ Klicke auf Suchergebnis...");
            const elements = await page.$$('.search-results button, .search-results .dropdown-item');
            if(elements.length > 0) {
                const box = await elements[0].boundingBox();
                if(box) {
                    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 5 });
                }
                await elements[0].click();
            }

            console.log("⏳ Warte auf Angular-Redirect...");
            try {
                await page.waitForFunction(() => window.location.href.includes('/location-summary/fixed'), { timeout: 30000 });
                resolvedUrl = page.url();
                console.log(`🔗 Redirect erfolgreich auf: ${resolvedUrl}`);
            } catch (e) {
                resolvedUrl = page.url();
                console.log(`⚠️ Warnung: Redirect nicht erkannt. Aktuelle URL: ${resolvedUrl}`);
            }

        } else {
            const encodedAddress = encodeURIComponent(address);
            const targetUrl = `https://broadbandmap.fcc.gov/location-summary/mobile?version=jun2025&addr_full=${encodedAddress}&lon=${lon}&lat=${lat}&zoom=15.00&env=0&tech=tech4g`;
            await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
            resolvedUrl = page.url();
        }

        console.log(`\n--- [PHASE 2] Extrahiere Daten ---`);
        console.log("⏳ Warte auf Daten-Tabelle...");
        await delay(3000);
        
        let tableLoaded = false;

        try {
            await page.waitForFunction(() => {
                const table = document.querySelector('.table-responsive table');
                return table && table.tBodies[0] && table.tBodies[0].rows.length > 0;
            }, { timeout: 15000 });
            tableLoaded = true;
        } catch (e) {
            console.log("⚠️ Tabelle hängt fest (Akamai Tarpit). Leite Angular-Kickstart ein (Reload)...");
        }

        if (!tableLoaded) {
            console.log("🔄 Lade Seite neu, um API zu triggern...");
            await page.reload({ waitUntil: 'domcontentloaded', timeout: 40000 });
            resolvedUrl = page.url();
            await humanizeMouse(page);
            
            try {
                await page.waitForFunction(() => {
                    const table = document.querySelector('.table-responsive table');
                    return table && table.tBodies[0] && table.tBodies[0].rows.length > 0;
                }, { timeout: 35000 });
                tableLoaded = true;
            } catch (e) {
                console.log(`❌ Timeout bei Daten-Extraktion auch nach Reload.`);
            }
        }

        if (tableLoaded) {
            console.log("✅ Tabelle erfolgreich geladen!");
            extractedData = await page.evaluate((type) => {
                let finalOutput = "";
                if (type === "fixed") {
                    const statusEl = Array.from(document.querySelectorAll('p.small.text-nowrap.mb-0')).find(p => p.innerText.includes('Status:'));
                    if (statusEl) finalOutput += "**Location Info:** " + statusEl.innerText.trim() + "\n\n";
                }

                const target = document.querySelector('.table-responsive table');
                if (!target) return "EMPTY";
                
                let md = "";
                for (let i = 0; i < target.rows.length; i++) {
                    const row = target.rows[i];
                    if (row.cells.length === 1 && row.cells[0].classList.contains('fw-bold')) {
                        md += "| **" + row.cells[0].innerText.trim() + "** | | | | |\n";
                        continue;
                    }
                    let rowData = Array.from(row.cells).map(c => c.innerText.replace(/\n/g, ' ').trim());
                    md += "| " + rowData.join(" | ") + " |\n";
                    if (i === 0) {
                        md += "| " + Array(row.cells.length).fill("---").join(" | ") + " |\n";
                    }
                }
                return finalOutput + md.trim();
            }, broadband_type);
        }

    } catch (e) {
        console.log(`⚠️ KRITISCHER FEHLER: ${e.message}`);
    } finally {
        if (browser) {
            await browser.close();
            console.log("🧹 Browser geschlossen.");
        }
        agentLock.unlock();
    }

    const durationSeconds = ((Date.now() - startTime) / 1000).toFixed(2);
    
    const finalPayload = {
        store_id: store_id,
        address: address,
        resolved_url: resolvedUrl, 
        status: extractedData !== "EMPTY" ? "success" : "error",
        broadband_type: broadband_type,
        providers: extractedData === "EMPTY" ? [] : [extractedData],
        usage: { duration_seconds: parseFloat(durationSeconds) }
    };

    try {
        await axios.post(webhook_url, finalPayload);
        console.log(`🚀 Webhook gesendet in ${durationSeconds}s`);
    } catch (err) {
        console.log(`❌ Webhook-Fehler: ${err.message}`);
    }
}

app.post('/api/v1/fcc_agent_bluecollar', (req, res) => {
    const { store_id, address, lat, lon, webhook_url, broadband_type = "mobile" } = req.body;
    res.json({ status: "queued", store_id: store_id });
    processAndSendWebhook(store_id, address, lat, lon, webhook_url, broadband_type).catch(console.error);
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`🚀 Agent Bluecollar (Humanizer Edition) läuft auf Port ${PORT}`);
});