const finalResult = [];

for (const item of $input.all()) {
  const storeId = item.json["body.store_id"] || (item.json.body && item.json.body.store_id);
  const address = item.json["body.address"] || (item.json.body && item.json.body.address);
  const broadbandType = item.json["body.broadband_type"] || (item.json.body && item.json.body.broadband_type);
  const providersData = item.json["body.providers"] || (item.json.body && item.json.body.providers);
  
  if (!providersData || providersData === "EMPTY") continue;

  const markdownText = Array.isArray(providersData) ? providersData[0] : providersData;
  const lines = markdownText.split('\n');
  
  const extractedProviders = [];
  let locationInfo = "";
  let serviceCategory = "General"; 

  for (let line of lines) {
    line = line.trim();

    // 1. Location Info extrahieren
    if (line.startsWith("**Location Info:**")) {
      locationInfo = line.replace("**Location Info:**", "").trim();
      continue;
    }

    // 2. NEU: Markdown Überschriften als Kategorie erkennen (z.B. ### Broadband Availability)
    if (line.startsWith("#")) {
      serviceCategory = line.replace(/#/g, "").trim();
      continue;
    }

    // Überspringe leere Zeilen oder Trenner
    if (!line || line.includes("| --- |")) continue;

    // 3. Tabellenzeilen verarbeiten
    if (line.startsWith("|")) {
      const columns = line.split('|')
                          .map(col => col.trim())
                          .filter((col, index, arr) => !(index === 0 && col === "") && !(index === arr.length - 1 && col === ""));

      // 3a. NEU: Erkennung von Kategorien INNERHALB der Tabelle 
      // (Wenn Spalte 1 Text hat, aber Spalte 2 & 3 komplett leer sind)
      const isSubHeader = columns.length >= 1 && columns[0] !== "" && (!columns[1] || columns[1] === "") && (!columns[2] || columns[2] === "");
      
      if (isSubHeader && !columns[0].toLowerCase().includes("provider")) {
        serviceCategory = columns[0].replace(/\*/g, "").trim();
        continue; // Diese Zeile nicht als Provider speichern
      }

      // Überspringe Header-Zeile
      if (columns[0].toLowerCase().includes("provider")) continue;

      // 4. Echte Datenzeile verarbeiten
      if (columns.length >= 4 && columns[0] !== "") {
        let providerFull = columns[0].replace(/\*/g, "").trim();
        let providerShort = providerFull;
        if (providerFull.includes(" Holding Company")) {
            providerShort = providerFull.split(" Holding Company")[0].trim();
        }

        extractedProviders.push({
          store_id: storeId,
          address: address,
          location_info: locationInfo,
          service_category: serviceCategory, 
          provider: providerFull,
          provider_short: providerShort,
          technology: columns[1] || "",
          down_mbps: columns[2] ? Number(columns[2].replace(/[^0-9.]/g, '')) : null,
          up_mbps: columns[3] ? Number(columns[3].replace(/[^0-9.]/g, '')) : null,
          requests: columns[4] || null
        });
      }
    }
  }

  // Finaler Output: Jede Zeile ein Item
  if (extractedProviders.length > 0) {
    for (let p of extractedProviders) {
      finalResult.push({
        json: {
          broadband_type: broadbandType || "unknown",
          ...p
        }
      });
    }
  }
}

return finalResult;