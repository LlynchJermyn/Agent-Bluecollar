require('dotenv').config();
const express = require('express');
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const axios = require('axios');

// Wir nutzen das Stealth-Plugin in seiner reinsten Form (keine manuellen Löschungen mehr!)
puppeteer.use(StealthPlugin());

const app = express();
app.use(express.json());

const PORT = process.env.API_PORT || 8001;
const delay = ms => new Promise(res => setTimeout(res, ms));

const MAX_CONCURRENT_BROWSERS = parseInt(process.env.MAX_CONCURRENT_JOBS) || 1;   
const TICK_INTERVAL_MS = 7500;       

let activeJobs = 0;
const jobQueue = [];

setInterval(() => {
    if (jobQueue.length > 0 && activeJobs < MAX_CONCURRENT_BROWSERS) {
        const nextJob = jobQueue.shift();
        activeJobs++;
        console.log(`\n⏱️ [TICK] Starte Job ${nextJob.store_id}. Aktive Jobs: ${activeJobs}/${MAX_CONCURRENT_BROWSERS}`);
        runWorkflow(nextJob).finally(() => {
            activeJobs--;
            console.log(`\n📉 Job ${nextJob.store_id} beendet. Aktive Jobs: ${activeJobs}/${MAX_CONCURRENT_BROWSERS}`);
        });
    }
}, TICK_INTERVAL_MS);

// Lebenswichtig: Menschliche Mausbewegung VOR dem Klick
async function humanizeMouse(page) {
    for (let i = 0; i < 2; i++) {
        const targetX = Math.floor(Math.random() * 600) + 300;
        const targetY = Math.floor(Math.random() * 400) + 200;
        await page.mouse.move(targetX, targetY, { steps: Math.floor(Math.random() * 15) + 10 });
        await delay(Math.floor(Math.random() * 200) + 100);
    }
}

function getRandomTypeDelay() {
    return Math.floor(Math.random() * (90 - 40 + 1)) + 40; // Leicht variierendes Tippen
}

async function runWorkflow(jobData) {
    const { store_id, address, lat, lon, webhook_url, broadband_type } = jobData;
    const typeLower = broadband_type.toLowerCase();
    
    const startTime = Date.now();
    let extractedData = "EMPTY";
    let resolvedUrl = "Nicht ermittelt";
    let browser = null;

    try {
        const jitterDelay = 2000 + Math.floor(Math.random() * 3000);
        console.log(`[Store ${store_id}] Warte ${jitterDelay}ms auf Start...`);
        await delay(jitterDelay);

        browser = await puppeteer.launch({
            headless: false, // In Docker zwingend false für Xvfb
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--mute-audio',
                '--start-maximized',
                '--window-size=1920,1080',
                // WICHTIG FÜR DOCKER: Normalisiert Canvas-Fingerprinting in Xvfb!
                '--force-color-profile=srgb', 
                '--disable-features=site-per-process,IsolateOrigins',
                '--disable-site-isolation-trials'
            ],
            defaultViewport: null
        });
        
        const page = await browser.newPage();
        
        // Sprache anpassen (verhindert Mismatch zwischen IP und Browser)
        await page.setExtraHTTPHeaders({
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7'
        });

        console.log(`[Store ${store_id}] --- [PHASE 1] Aufruf & Suche ---`);
        
        await page.goto('https://broadbandmap.fcc.gov/home?version=jun2025', { waitUntil: 'domcontentloaded', timeout: 60000 });
        
        // Kurzes Warmup, damit Akamai die Mausbewegungen registrieren kann
        await delay(2000);
        await humanizeMouse(page);

        await page.waitForSelector('#addrSearch', { visible: true, timeout: 20000 });
        console.log(`[Store ${store_id}] ⌨️ Tippe Adresse ein...`);
        await page.click('#addrSearch');
        await page.evaluate(() => document.querySelector('#addrSearch').value = '');
        await page.type('#addrSearch', address, { delay: getRandomTypeDelay() });

        console.log(`[Store ${store_id}] ⏳ Warte auf Geocoder-Dropdown...`);
        await page.waitForSelector('.search-results button, .search-results .dropdown-item', { visible: true, timeout: 25000 });
        
        // Akamai verlangt eine kleine Pause zwischen Tippen und Klicken
        await delay(1500); 
        
        const elements = await page.$$('.search-results button, .search-results .dropdown-item');
        if(elements.length > 0) {
            const box = await elements[0].boundingBox();
            if(box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 5 });
            
            console.log(`[Store ${store_id}] 🖱️ Klicke auf Ergebnis...`);
            // Wir warten nach dem Klick darauf, dass die URL sich ändert
            await Promise.all([
                page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {}),
                elements[0].click()
            ]);
        }

        // Falls die waitForNavigation oben nicht getriggert hat, warten wir manuell auf die URL
        try {
            await page.waitForFunction(() => window.location.href.includes('/location-summary'), { timeout: 15000 });
        } catch(e) {}
        
        resolvedUrl = page.url();
        console.log(`[Store ${store_id}] 🔗 URL nach Redirect: ${resolvedUrl}`);
        
        console.log(`[Store ${store_id}] --- [PHASE 2] Warte natürlich auf DOM (Kein API Sniffing!) ---`);
        
        let tableLoaded = false;
        
        // Wir lassen Angular einfach in Ruhe laden und prüfen alle paar Millisekunden, 
        // ob die Tabelle mit Provider-Daten endlich gezeichnet wurde.
        try {
            await page.waitForFunction(() => {
                const tables = document.querySelectorAll('table');
                for (let t of tables) {
                    // Prüft, ob es eine Tabelle gibt, die mehr als 1 Zeile hat
                    if (t.rows.length > 1 && t.innerText.includes('Provider')) return true;
                }
                return false;
            }, { timeout: 35000, polling: 1000 });
            tableLoaded = true;
        } catch (e) {
            console.log(`[Store ${store_id}] ⚠️ Tabelle nicht nach 35s gefunden.`);
        }

        if (tableLoaded) {
            console.log(`[Store ${store_id}] 📊 Tabelle gefunden! Lese Daten aus...`);
            
            extractedData = await page.evaluate((type) => {
                let finalOutput = "";
                
                // Location Status extrahieren
                if (type === "fixed") {
                    const allElements = document.querySelectorAll('*');
                    for (let el of allElements) {
                        if (el.innerText && el.innerText.trim().startsWith('Status:')) {
                            finalOutput += "**Location Info:** " + el.innerText.replace(/\n/g, ' ').trim() + "\n\n";
                            break;
                        }
                    }
                }

                const tables = Array.from(document.querySelectorAll('table'));
                if (tables.length === 0) return "EMPTY";
                
                // Wir nehmen die Tabelle mit den meisten Zeilen
                let targetTable = tables.reduce((prev, current) => (prev.rows.length > current.rows.length) ? prev : current);
                if (!targetTable || targetTable.rows.length <= 1) return "EMPTY";
                
                let md = "";
                for (let i = 0; i < targetTable.rows.length; i++) {
                    const row = targetTable.rows[i];
                    
                    // Business-only Header überspringen
                    if (row.cells.length === 1 && row.cells[0].innerText.trim().length > 0) {
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

            if (extractedData !== "EMPTY") {
                console.log(`[Store ${store_id}] ✅ DOM Daten erfolgreich gerettet!`);
            }
        }

        // Speicher freigeben
        try { await page.goto('about:blank'); } catch(e) {}

    } catch (e) {
        console.log(`[Store ${store_id}] ⚠️ KRITISCHER FEHLER: ${e.message}`);
    } finally {
        if (browser) {
            try { await browser.close(); } catch(e) {}
            console.log(`[Store ${store_id}] 🧹 Browser geschlossen.`);
        }
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
        console.log(`[Store ${store_id}] 🚀 Webhook gesendet in ${durationSeconds}s`);
    } catch (err) {
        console.log(`[Store ${store_id}] ❌ Webhook-Fehler: ${err.message}`);
    }
}

app.post('/api/v1/fcc_agent_bluecollar', (req, res) => {
    const { store_id, address, lat, lon, webhook_url, broadband_type = "mobile" } = req.body;
    jobQueue.push({ store_id, address, lat, lon, webhook_url, broadband_type });
    console.log(`\n📥 Request empfangen: Store ${store_id} (Warteschlange: ${jobQueue.length})`);
    res.json({ status: "queued", store_id: store_id, queue_length: jobQueue.length });
});

const server = app.listen(PORT, '0.0.0.0', () => {
    console.log(`🚀 Agent Bluecollar (Mac-Parity Native Edition) läuft auf Port ${PORT}`);
});

server.keepAliveTimeout = 14400000;
server.headersTimeout = 14401000;