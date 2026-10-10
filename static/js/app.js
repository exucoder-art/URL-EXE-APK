/**
 * EXU URL-to-App Converter – Frontend logic
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // Elements
  const form = $("#build-form");
  const urlInput = $("#url");
  const appNameInput = $("#app_name");
  const packageInput = $("#package_name");
  const themeColor = $("#theme_color");
  const themeHex = $("#theme_color_hex");
  const iconInput = $("#icon");
  const iconDrop = $("#icon-drop");
  const iconPreview = $("#icon-preview");
  const iconLabel = $("#icon-label");
  const btnValidate = $("#btn-validate");
  const btnBuild = $("#btn-build");
  const btnText = btnBuild.querySelector(".btn-text");
  const btnLoader = btnBuild.querySelector(".btn-loader");
  const urlMeta = $("#url-meta");
  const urlError = $("#url-error");
  const statusPanel = $("#status-panel");
  const statusTitle = $("#status-title");
  const statusBadge = $("#status-badge");
  const progressFill = $("#progress-fill");
  const progressPct = $("#progress-pct");
  const statusMsg = $("#status-message");
  const logConsole = $("#log-console");
  const downloadArea = $("#download-area");
  const downloadButtons = $("#download-buttons");

  let currentJobId = null;
  let pollTimer = null;
  let lastLogCount = 0;

  // ── Color sync ──
  themeColor.addEventListener("input", () => {
    themeHex.value = themeColor.value;
  });
  themeHex.addEventListener("input", () => {
    if (/^#[0-9A-Fa-f]{6}$/.test(themeHex.value)) {
      themeColor.value = themeHex.value;
    }
  });

  // ── Icon drop zone ──
  iconDrop.addEventListener("click", () => iconInput.click());
  iconDrop.addEventListener("dragover", (e) => {
    e.preventDefault();
    iconDrop.classList.add("dragover");
  });
  iconDrop.addEventListener("dragleave", () => iconDrop.classList.remove("dragover"));
  iconDrop.addEventListener("drop", (e) => {
    e.preventDefault();
    iconDrop.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      iconInput.files = e.dataTransfer.files;
      previewIcon(e.dataTransfer.files[0]);
    }
  });
  iconInput.addEventListener("change", () => {
    if (iconInput.files[0]) previewIcon(iconInput.files[0]);
  });

  function previewIcon(file) {
    const url = URL.createObjectURL(file);
    iconPreview.innerHTML = `<img src="${url}" alt="icon" />`;
    iconLabel.textContent = file.name.length > 22 ? file.name.slice(0, 20) + "…" : file.name;
  }

  // ── Auto-fill package from app name ──
  appNameInput.addEventListener("blur", () => {
    if (!packageInput.value && appNameInput.value) {
      const slug = appNameInput.value
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "")
        .slice(0, 20) || "app";
      packageInput.value = `com.exu.${slug}`;
    }
  });

  // ── Validate URL ──
  btnValidate.addEventListener("click", validateUrl);
  urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      validateUrl();
    }
  });

  async function validateUrl() {
    const raw = urlInput.value.trim();
    urlError.classList.add("hidden");
    urlMeta.classList.add("hidden");

    if (!raw) {
      showUrlError("Please enter a URL");
      return;
    }

    btnValidate.disabled = true;
    try {
      const res = await fetch("/api/validate-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: raw }),
      });
      const data = await res.json();
      if (!data.ok) {
        showUrlError(data.error || "Invalid URL");
        return;
      }
      urlInput.value = data.url;
      const m = data.metadata || {};
      if (m.title && !appNameInput.value) {
        appNameInput.value = m.title.slice(0, 50);
        appNameInput.dispatchEvent(new Event("blur"));
      }
      let html = "";
      if (m.favicon) {
        html += `<img src="${esc(m.favicon)}" onerror="this.style.display='none'" alt="" />`;
      }
      html += `<div><div class="meta-title">${esc(m.title || data.url)}</div>`;
      if (m.description) html += `<div class="meta-desc">${esc(m.description)}</div>`;
      if (!m.fetch_ok && m.fetch_error) {
        html += `<div class="meta-desc" style="color:var(--warning)">⚠ ${esc(m.fetch_error)}</div>`;
      }
      html += `</div>`;
      urlMeta.innerHTML = html;
      urlMeta.classList.remove("hidden");
    } catch (err) {
      showUrlError("Network error – is the server running?");
    } finally {
      btnValidate.disabled = false;
    }
  }

  function showUrlError(msg) {
    urlError.textContent = msg;
    urlError.classList.remove("hidden");
  }

  // ── Build submit ──
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const targets = [...$$('input[name="targets"]:checked')].map((c) => c.value);
    if (!targets.length) {
      alert("Select at least one build target");
      return;
    }

    setBuilding(true);
    statusPanel.classList.remove("hidden");
    downloadArea.classList.add("hidden");
    logConsole.innerHTML = "";
    lastLogCount = 0;
    updateProgress(0, "queued", "Submitting build job…");

    const fd = new FormData();
    fd.append("url", urlInput.value.trim());
    fd.append("app_name", appNameInput.value.trim());
    fd.append("package_name", packageInput.value.trim());
    fd.append("theme_color", themeColor.value);
    fd.append("targets", targets.join(","));
    if (iconInput.files[0]) {
      fd.append("icon", iconInput.files[0]);
    }

    try {
      const res = await fetch("/api/build", { method: "POST", body: fd });
      const data = await res.json();
      if (!data.ok) {
        updateProgress(0, "failed", data.error || "Build request failed");
        setBuilding(false);
        return;
      }
      currentJobId = data.job_id;
      statusTitle.textContent = `Building “${appNameInput.value.trim()}”`;
      startPolling(currentJobId);
    } catch (err) {
      updateProgress(0, "failed", "Network error");
      setBuilding(false);
    }
  });

  function setBuilding(on) {
    btnBuild.disabled = on;
    btnText.classList.toggle("hidden", on);
    btnLoader.classList.toggle("hidden", !on);
  }

  function startPolling(jobId) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => pollStatus(jobId), 900);
    pollStatus(jobId);
  }

  async function pollStatus(jobId) {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();
      if (!data.ok) return;

      const job = data.job;
      updateProgress(job.progress, job.status, job.message);

      // Append new logs
      const logs = job.logs || [];
      if (logs.length > lastLogCount) {
        for (let i = lastLogCount; i < logs.length; i++) {
          const line = document.createElement("div");
          line.className = "log-line" + (logs[i].msg.startsWith("ERROR") ? " log-err" : "");
          line.textContent = logs[i].msg;
          logConsole.appendChild(line);
        }
        lastLogCount = logs.length;
        logConsole.scrollTop = logConsole.scrollHeight;
      }

      if (job.status === "completed") {
        clearInterval(pollTimer);
        setBuilding(false);
        showDownloads(jobId, job.artifacts || {});
      } else if (job.status === "failed") {
        clearInterval(pollTimer);
        setBuilding(false);
        if (job.error) {
          const line = document.createElement("div");
          line.className = "log-line log-err";
          line.textContent = job.error;
          logConsole.appendChild(line);
        }
      }
    } catch (_) {
      /* ignore transient errors */
    }
  }

  function updateProgress(pct, status, message) {
    progressFill.style.width = `${pct}%`;
    progressPct.textContent = `${pct}%`;
    statusMsg.textContent = message || "";
    statusBadge.textContent = status;
    statusBadge.className = "badge badge-" + status;
  }

  function showDownloads(jobId, artifacts) {
    downloadButtons.innerHTML = "";
    const labels = { apk: "🤖 Download APK", exe: "🪟 Download EXE" };
    for (const [target, path] of Object.entries(artifacts)) {
      const a = document.createElement("a");
      a.href = `/api/download/${jobId}/${target}`;
      a.className = "btn-download";
      a.textContent = labels[target] || `Download ${target}`;
      a.setAttribute("download", "");
      downloadButtons.appendChild(a);
    }
    downloadArea.classList.remove("hidden");
  }

  function esc(str) {
    const d = document.createElement("div");
    d.textContent = str || "";
    return d.innerHTML;
  }
})();
