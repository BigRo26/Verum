// Runs inside the extension's offscreen document, which is where MV3
// extensions are allowed to touch getUserMedia / MediaRecorder.

let mediaRecorder = null;
let recordedChunks = [];
let mediaStream = null;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.target !== "offscreen") return false;

  if (message.type === "OFFSCREEN_START") {
    startRecording(message.streamId)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // async response
  }

  if (message.type === "OFFSCREEN_STOP") {
    stopRecording()
      .then((blob) => blobToBase64(blob))
      .then((base64) => sendResponse({ ok: true, audioBase64: base64 }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // async response
  }

  return false;
});

async function startRecording(streamId) {
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  });

  // Keep playing the audio through so the user still hears the tab
  // while we capture it (otherwise tabCapture mutes the tab).
  const audioContext = new AudioContext();
  const source = audioContext.createMediaStreamSource(mediaStream);
  source.connect(audioContext.destination);

  recordedChunks = [];
  mediaRecorder = new MediaRecorder(mediaStream, { mimeType: "audio/webm" });
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) recordedChunks.push(e.data);
  };
  mediaRecorder.start(1000);
}

function stopRecording() {
  return new Promise((resolve, reject) => {
    if (!mediaRecorder) {
      reject(new Error("No active recording."));
      return;
    }
    mediaRecorder.onstop = () => {
      const blob = new Blob(recordedChunks, { type: "audio/webm" });
      mediaStream.getTracks().forEach((track) => track.stop());
      mediaRecorder = null;
      mediaStream = null;
      resolve(blob);
    };
    mediaRecorder.stop();
  });
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result); // data: URL
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}
