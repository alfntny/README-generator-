const API_BASE = ""; // same-origin; change if frontend is served separately

let currentMarkdown = "";

// ---- tab switching (input) --------------------------------------------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.remove("hidden");
  });
});

// ---- tab switching (output) -------------------------------------------
document.querySelectorAll(".otab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".otab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const rendered = document.getElementById("rendered-output");
    const raw = document.getElementById("raw-output");
    if (btn.dataset.otab === "rendered") {
      rendered.classList.remove("hidden");
      raw.classList.add("hidden");
    } else {
      rendered.classList.add("hidden");
      raw.classList.remove("hidden");
    }
  });
});

// ---- status helper -------------------------------------------------------
function setStatus(msg, type = "") {
  const el = document.getElementById("status-msg");
  el.textContent = msg;
  el.className = "status " + type;
}

function renderMarkdown(md) {
  currentMarkdown = md;
  document.getElementById("rendered-output").innerHTML = marked.parse(md);
  document.getElementById("raw-output").value = md;
  document.getElementById("copy-btn").disabled = false;
  document.getElementById("download-btn").disabled = false;
}

// ---- prompt mode ----------------------------------------------------------
document.getElementById("generate-prompt-btn").addEventListener("click", async () => {
  const prompt = document.getElementById("prompt-input").value.trim();
  if (!prompt) {
    setStatus("Describe your project first.", "error");
    return;
  }
  setStatus("Generating…");
  try {
    const res = await fetch(`${API_BASE}/api/generate-from-prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    renderMarkdown(data.readme);
    setStatus("Done.", "success");
  } catch (err) {
    setStatus("Error: " + err.message, "error");
  }
});

// ---- upload mode: drag & drop / browse ------------------------------------
const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
let selectedFiles = [];

dropZone.addEventListener("click", () => fileInput.click());

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  addFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => addFiles(fileInput.files));

function addFiles(fileListObj) {
  selectedFiles = Array.from(fileListObj);
  const listEl = document.getElementById("file-list");
  if (selectedFiles.length === 0) {
    listEl.textContent = "";
    return;
  }
  listEl.textContent = `${selectedFiles.length} file(s) selected: ` +
    selectedFiles.slice(0, 6).map((f) => f.webkitRelativePath || f.name).join(", ") +
    (selectedFiles.length > 6 ? ", …" : "");
}

document.getElementById("generate-upload-btn").addEventListener("click", async () => {
  if (selectedFiles.length === 0) {
    setStatus("Add files or a .zip first.", "error");
    return;
  }
  setStatus("Uploading & analyzing…");
  try {
    const formData = new FormData();
    selectedFiles.forEach((f) => {
      // preserve folder structure in the filename so the backend can rebuild it
      const relPath = f.webkitRelativePath || f.name;
      formData.append("files", f, relPath);
    });
    formData.append("prompt", document.getElementById("upload-context-input").value.trim());

    const res = await fetch(`${API_BASE}/api/generate-from-upload`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    renderMarkdown(data.readme);
    setStatus("Done.", "success");
  } catch (err) {
    setStatus("Error: " + err.message, "error");
  }
});

// ---- copy / download -------------------------------------------------------
document.getElementById("copy-btn").addEventListener("click", async () => {
  await navigator.clipboard.writeText(currentMarkdown);
  setStatus("Copied to clipboard.", "success");
});

document.getElementById("download-btn").addEventListener("click", () => {
  const blob = new Blob([currentMarkdown], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "README.md";
  a.click();
  URL.revokeObjectURL(url);
});
