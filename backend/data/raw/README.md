# Raw downloads (gitignored)

`python -m backend.data.download_data` fills this folder automatically. Only one source has to be downloaded by hand, because bls.gov blocks automated clients:

- **BLS OEWS, May 2025, Metropolitan and nonmetropolitan area (XLSX zip).**
  - Get it from https://www.bls.gov/oes/tables.htm.
  - Save it here as `bls_oews/oesm25ma.zip`.
  - Optional national file: `bls_oews/oesm25nat.zip`.
