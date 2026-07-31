// Defaults to your local backend (see backend/README.md). If you deploy it
// to a VM/cloud host instead, update this AND the host_permissions entry
// in manifest.json to match.
const BACKEND_URL = "http://localhost:8000";

let state = { recording: false, analyzing: false, tabTitle: "" };
let offscreenReady = null;

async function ensureOffscreenDocument() {
  const existing = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  if (existing.length > 0) return;

  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["USER_MEDIA"],
    justification: "Recording tab audio for fact-checking.",
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "VERUM_GET_STATE") {
    sendResponse(state);
    return false;
  }

  if (message.type === "VERUM_START_RECORDING") {
    handleStart(message.tabId, message.tabTitle)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === "VERUM_STOP_RECORDING") {
    handleStop()
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  return false;
});

async function handleStart(tabId, tabTitle) {
  await ensureOffscreenDocument();

  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });

  const response = await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "OFFSCREEN_START",
    streamId,
  });

  if (!response?.ok) {
    throw new Error(response?.error || "Failed to start recording.");
  }

  state = { recording: true, analyzing: false, tabTitle: tabTitle || "Audio Analysis" };
}

async function handleStop() {
  state.recording = false;
  state.analyzing = true;
  broadcast({ type: "VERUM_STATUS", text: "Analyzing \u2014 this can take a minute\u2026" });

  const response = await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "OFFSCREEN_STOP",
  });

  // Offscreen document no longer needed
  chrome.offscreen.closeDocument().catch(() => {});

  if (!response?.ok) {
    state.analyzing = false;
    broadcast({ type: "VERUM_ERROR", text: response?.error || "Recording failed." });
    throw new Error(response?.error || "Recording failed.");
  }

  await sendToBackend(response.audioBase64, state.tabTitle);
  state.analyzing = false;
}

async function sendToBackend(audioDataUrl, tabTitle) {
  try {
    const audioBlob = await (await fetch(audioDataUrl)).blob();

    const formData = new FormData();
    formData.append("audio", audioBlob, "capture.webm");
    formData.append("source_title", tabTitle || "Audio Analysis");

    const res = await fetch(`${BACKEND_URL}/analyze`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => res.statusText);
      throw new Error(`Backend error (${res.status}): ${errText}`);
    }

    const pdfBlob = await res.blob();
    const pdfUrl = await blobToDataUrl(pdfBlob);

    await chrome.downloads.download({
      url: pdfUrl,
      filename: `verum_report_${Date.now()}.pdf`,
      saveAs: false,
    });

    broadcast({ type: "VERUM_DONE" });
  } catch (err) {
    broadcast({ type: "VERUM_ERROR", text: err.message });
  }
}

// URL.createObjectURL() is unreliable inside MV3 background service
// workers (it works fine in the offscreen document, which has DOM access,
// but not reliably here). A base64 data: URL needs no DOM APIs, so it
// works in either context. Chunked to avoid blowing the call stack on
// larger PDFs via a spread argument to String.fromCharCode.
async function blobToDataUrl(blob) {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000; // 32KB per chunk
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  const base64 = btoa(binary);
  return `data:${blob.type || "application/pdf"};base64,${base64}`;
}

function broadcast(message) {
  chrome.runtime.sendMessage(message).catch(() => {
    // No popup open to receive it — that's fine, state is tracked here too.
  });
}