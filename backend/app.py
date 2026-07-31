import os
import tempfile
import logging

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from fact_checker import AudioFactChecker
from pdf_report import build_pdf_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verum")

app = FastAPI(title="Verum Fact-Check API")

# Chrome extensions call this API from a chrome-extension:// origin.
# Restrict this to your extension's ID once you have one, e.g.:
#   allow_origins=["chrome-extension://<your-extension-id>"]
ALLOWED_ORIGINS = os.environ.get("VERUM_ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGINS] if ALLOWED_ORIGINS != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(audio: UploadFile = File(...), source_title: str = "Audio Analysis"):
    if not audio.filename:
        raise HTTPException(status_code=400, detail="No audio file provided.")

    suffix = os.path.splitext(audio.filename)[1] or ".webm"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await audio.read())
            tmp_path = tmp.name

        logger.info("Running fact-check pipeline on %s", tmp_path)
        checker = AudioFactChecker(tmp_path)
        eval_df, reliability_score = checker.fact_check_audio()

        pdf_buffer = build_pdf_report(eval_df, reliability_score, source_title=source_title)

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="verum_report.pdf"'},
        )
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
