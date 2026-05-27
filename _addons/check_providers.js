// Überprüft, ob die Provider-Tabelle leer ist
return $input.all().map(item => {
  // WICHTIG: Hier greifen wir auf das verschachtelte Objekt zu (body -> providers)
  // Das ?. (Optional Chaining) schützt vor Fehlern, falls "body" mal komplett fehlt
  const p = item.json.body?.providers;
  
  return {
    json: {
      // Kopiert alle ursprünglichen Felder
      ...item.json, 
      
      // True, wenn leer, null, nicht vorhanden oder leeres Array. False, wenn Daten da sind.
      error: !p || (Array.isArray(p) && p.length === 0) || p === ""
    }
  };
});