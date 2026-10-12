# Routes Database Directory

This directory contains per-city offline route-to-destination datasets.

## File Format

Each city dataset must be a CSV file named `<city_name>.csv` (all lowercase, no spaces).
The CSV file must contain a header row:
```csv
route,destination
```

Subsequent rows contain:
1. **route**: The route number or code exactly as recognized by OCR (e.g. `21C`, `10C`, `305`). It will be matched case-insensitively.
2. **destination**: The human-readable destination name to be spoken (e.g. `Benz Circle`, `Poranki`).

Example:
```csv
route,destination
21C,Vijayawada Bus Stand
12,Railway Station
```

## How to add a new city

1. Create a new CSV file in this directory: `data/routes/<new_city>.csv`.
2. Populate it with the header and your city's route-to-destination mappings.
3. Change the active city in `config.py` by updating the `CITY` variable:
   ```python
   CITY = "<new_city>"
   ```
4. Regenerate the audio cache for the new city's common routes:
   ```bash
   python tools/pregenerate_cache.py
   ```
