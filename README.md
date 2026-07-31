# Verum — Audio Fact Checker

Two pieces:

- `backend/` — a FastAPI service that runs Whisper transcription, the
  fact/opinion classifier, Tavily search, and the HF LLM verdict call, then
  returns a PDF report. This is your original notebook logic, refactored to
  run as a server instead of in-notebook.
- `extension/` — a Manifest V3 Chrome extension that records the active
  tab's audio, uploads it to the backend, and downloads the resulting PDF.

## 1. Run the backend

**Recommended: run it locally.** The extension and backend are both on
your machine anyway, so there's no cloud step required, no account, and no
risk of a platform changing its free-tier terms out from under you (which
is exactly what happened trying to route this through Hugging Face Spaces
— their free compute options moved twice in the course of building this).

```bash
cd backend
pip install -r requirements.txt --break-system-packages   # or use a venv
# ffmpeg is required by Whisper:
#   macOS:   brew install ffmpeg
#   Ubuntu:  sudo apt install ffmpeg
#   Windows: winget install ffmpeg
export TAVILY_API_KEY=your_key_here
export HF_API_KEY=your_key_here
python app.py
```

This starts the API on `http://localhost:8000`. Leave it running while you
use the extension — the first request will be slow while Whisper and the
classifier load into memory; after that it's fast. The extension's
defaults (`manifest.json` host_permissions, `background.js`
`BACKEND_URL`) already point here, so no further config is needed for
local use.

**Rotate your keys.** The Tavily and Hugging Face keys in the original
notebook were shared in plaintext in this conversation — treat them as
compromised and generate new ones regardless of where you run this.

**If you want it reachable from another device** (not just the machine
running Chrome), the most reliable genuinely-free option right now is an
**Oracle Cloud "Always Free" VM** — unlike a trial credit, that tier
doesn't expire, and it gives enough RAM to run this comfortably. The
`Dockerfile` in this repo works there unchanged:

```bash
# on the VM, after cloning this repo and setting the two env vars:
docker build -t verum-backend ./backend
docker run -d -p 8000:8000 \
  -e TAVILY_API_KEY=your_key_here \
  -e HF_API_KEY=your_key_here \
  verum-backend
```

Then update `BACKEND_URL` in `background.js` and `host_permissions` in
`manifest.json` to `http://<your-vm-ip>:8000` (or set up HTTPS via a
reverse proxy if you want to avoid mixed-content complications later).

## 2. Point the extension at your backend (only needed if not using localhost)

If you deployed to a VM instead of running locally, edit two files and
replace the localhost URL:

- `extension/manifest.json` → `host_permissions`
- `extension/background.js` → `BACKEND_URL` constant

## 3. Load the extension locally

1. Add three icon PNGs to `extension/icons/` (16x16, 48x48, 128x128) —
   any placeholder image works for testing.
2. Go to `chrome://extensions`, enable **Developer mode**.
3. Click **Load unpacked**, select the `extension/` folder.
4. Pin Verum to the toolbar, open a tab playing audio (YouTube, a Canvas
   lecture recording, etc.), click the icon, **Start Recording**, then
   **Stop & Analyze**. The PDF downloads automatically when analysis
   finishes.

## Architecture notes

- **Why two pieces?** Chrome extensions run in JS; Whisper/transformers
  need a real Python process. The extension only handles capture + UI +
  download — all ML work happens server-side.
- **Why an offscreen document?** MV3 service workers can't use
  `getUserMedia`/`MediaRecorder` directly. `chrome.tabCapture` hands the
  service worker a stream ID, which is passed to a hidden offscreen
  document that does the actual recording.
- **Secrets never ship in the extension.** `TAVILY_API_KEY` and
  `HF_API_KEY` live only as backend environment variables.
- **Analysis time.** A 10-minute lecture can take a few minutes to
  transcribe + fact-check (Whisper transcription, then one Tavily + one
  HF call per detected factual claim). The popup shows a status message
  during this; there's no progress bar in this version.

## Known limitations to revisit

- No auth on `/analyze` — anyone with the backend URL can call it and
  burn your API quota. Fine for personal use; add an API key header
  before sharing the extension with others.
- `reliability_score` returns `None` when no factual claims are detected
  (e.g. pure opinion/commentary audio) — the PDF reports this explicitly
  rather than showing a misleading 0%.
- Long recordings produce a large `.webm` upload; consider chunking/
  streaming if you plan to fact-check hour-long content regularly.
