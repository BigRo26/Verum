const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const statusEl = document.getElementById("status");

function setStatus(text, recording = false) {
  statusEl.innerHTML = recording ? `<span class="dot"></span>${text}` : text;
}

// Reflect current state when popup opens (recording may be in progress)
chrome.runtime.sendMessage({ type: "VERUM_GET_STATE" }, (state) => {
  if (chrome.runtime.lastError) return;
  if (state?.recording) {
    startBtn.disabled = true;
    stopBtn.disabled = false;
    setStatus("Recording tab audio\u2026", true);
  } else if (state?.analyzing) {
    startBtn.disabled = true;
    stopBtn.disabled = true;
    setStatus("Analyzing \u2014 this can take a minute\u2026");
  }
});

startBtn.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) {
    setStatus("No active tab found.");
    return;
  }

  chrome.runtime.sendMessage(
    { type: "VERUM_START_RECORDING", tabId: tab.id, tabTitle: tab.title },
    (response) => {
      if (response?.ok) {
        startBtn.disabled = true;
        stopBtn.disabled = false;
        setStatus("Recording tab audio\u2026", true);
      } else {
        setStatus(response?.error || "Could not start recording.");
      }
    }
  );
});

stopBtn.addEventListener("click", () => {
  stopBtn.disabled = true;
  setStatus("Analyzing \u2014 this can take a minute\u2026");
  chrome.runtime.sendMessage({ type: "VERUM_STOP_RECORDING" }, (response) => {
    if (!response?.ok) {
      setStatus(response?.error || "Analysis failed.");
      startBtn.disabled = false;
    }
    // On success, background.js triggers the PDF download directly;
    // it also broadcasts a status update we listen for below.
  });
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "VERUM_STATUS") {
    setStatus(msg.text, msg.recording);
  }
  if (msg.type === "VERUM_DONE") {
    setStatus("Report downloaded \u2713");
    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
  if (msg.type === "VERUM_ERROR") {
    setStatus(`Error: ${msg.text}`);
    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
});
