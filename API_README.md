# HWPX API wrapper

This repository includes an optional FastAPI wrapper for the existing `hwpxskill` scripts. The original CLI workflow remains unchanged.

## Local run

```bash
python -m pip install -r requirements.txt
export HWPX_API_KEY="change-me"   # Windows PowerShell: $env:HWPX_API_KEY="change-me"
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` to test the API.

## Endpoints

- `GET /health` — service health
- `POST /inspect` — validate a HWPX and return editable paragraph/cell slots
- `POST /validate` — structural validation plus layout-risk warnings
- `POST /edit` — edit by replacement map, slot map, and/or paragraph map; validate before returning HWPX

`/inspect`, `/validate`, and `/edit` accept `multipart/form-data` with a `.hwpx` file. If `HWPX_API_KEY` is set, send `Authorization: Bearer <key>`.

The default upload limit is 25 MiB. Override it with `HWPX_MAX_FILE_BYTES`.

## Safety model

- Uploaded documents are written only to temporary working directories.
- The API rejects non-HWPX filenames and oversized uploads.
- `/edit` runs the existing form-preserving `scripts/edit_hwpx.py`.
- The output must pass the existing HWPX structural validator.
- Paragraph count, explicit page/column breaks, table count, and table shapes must remain unchanged.
- Temporary edit files are deleted after the response is sent.

## Docker

```bash
docker build -t hwpxskill-api .
docker run --rm -p 8000:8000 -e HWPX_API_KEY="change-me" hwpxskill-api
```

## GPT Action schema

`openapi.yaml` is a deployment template. Replace the placeholder server URL after deployment.

The API currently uses standard multipart file upload and binary HWPX download. Compatibility with the then-current GPT Actions file-passing behavior should be verified during the GPT integration step before production use.
