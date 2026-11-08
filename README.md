# Carretera · Asturias

App web (instalable) con el estado de los puertos y autovías de Asturias: incidencias y cámaras de la DGT y avisos de AEMET.

- `scripts/actualizar.py` descarga los datos y genera `estado.json`. Lo ejecuta cada 10 minutos la tarea `.github/workflows/datos.yml`, que publica el resultado en la rama `datos`.
- `zonas.json` define las zonas (carreteras, recuadro geográfico y puntos para cruzar con los avisos de AEMET). Añadir una zona es añadir una entrada.
- La app (`index.html`, `app.js`, `app.css`) lee `estado.json` de la rama `datos`.
- La clave de AEMET va en el secreto del repo `AEMET_API_KEY`.

Fuentes: DGT, Punto de Acceso Nacional (CC BY) · AEMET OpenData.
