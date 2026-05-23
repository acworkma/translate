(() => {
  const $ = (id) => document.getElementById(id);
  const drop = $("drop");
  const fileInput = $("fileInput");
  const fileName = $("fileName");
  const startBtn = $("startBtn");
  const language = $("language");
  const errBox = $("errBox");
  const workflowCard = $("workflow-card");
  const resultCard = $("result-card");
  const stepsEl = $("steps");
  const jobIdLabel = $("jobIdLabel");
  const scoreBadge = $("scoreBadge");
  const downloadBtn = $("downloadBtn");
  const reviewBtn = $("reviewBtn");
  const resetBtn = $("resetBtn");
  const resultMsg = $("resultMsg");
  const preview = $("preview");
  const srcPreview = $("srcPreview");
  const tgtPreview = $("tgtPreview");

  let chosenFile = null;
  let pollTimer = null;

  function showErr(msg) {
    errBox.textContent = msg;
    errBox.classList.remove("hidden");
  }
  function clearErr() {
    errBox.classList.add("hidden");
  }

  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("drag");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("drag");
    if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length) setFile(e.target.files[0]);
  });

  function setFile(f) {
    if (!f.name.toLowerCase().endsWith(".docx")) {
      showErr("Only .docx files are supported.");
      return;
    }
    clearErr();
    chosenFile = f;
    fileName.textContent = `${f.name} — ${(f.size / 1024).toFixed(1)} KB`;
    startBtn.disabled = false;
  }

  startBtn.addEventListener("click", async () => {
    if (!chosenFile) return;
    startBtn.disabled = true;
    startBtn.textContent = "Uploading…";
    clearErr();
    const fd = new FormData();
    fd.append("file", chosenFile);
    fd.append("language", language.value);
    try {
      const r = await fetch("/api/jobs", { method: "POST", body: fd });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(`HTTP ${r.status}: ${t}`);
      }
      const data = await r.json();
      jobIdLabel.textContent = data.jobId;
      workflowCard.classList.remove("hidden");
      resetSteps();
      startPolling(data.jobId, data.language);
    } catch (err) {
      showErr(err.message);
      startBtn.disabled = false;
      startBtn.textContent = "Start translation";
    }
  });

  resetBtn.addEventListener("click", () => {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    chosenFile = null;
    fileInput.value = "";
    fileName.textContent = "No file selected";
    startBtn.disabled = true;
    startBtn.textContent = "Start translation";
    workflowCard.classList.add("hidden");
    resultCard.classList.add("hidden");
    preview.classList.add("hidden");
    downloadBtn.classList.add("hidden");
    reviewBtn.classList.add("hidden");
    scoreBadge.textContent = "—";
    resetSteps();
  });

  function resetSteps() {
    for (const li of stepsEl.querySelectorAll(".step")) {
      li.dataset.state = "pending";
      li.querySelector('[data-role="badge"]').textContent = "";
    }
  }

  function applySteps(stepsState) {
    for (const li of stepsEl.querySelectorAll(".step")) {
      const k = li.dataset.key;
      const s = stepsState[k] || "pending";
      li.dataset.state = s;
      const badge = li.querySelector('[data-role="badge"]');
      badge.textContent = s === "done" ? "✓" : s === "running" ? "…" : s === "failed" ? "✗" : "";
      badge.className = "text-xs " + (s === "running" ? "pulse-running" : "");
    }
  }

  function startPolling(jobId, lang) {
    let stopped = false;
    const poll = async () => {
      if (stopped) return;
      try {
        const r = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (!r.ok) throw new Error("status fetch failed");
        const data = await r.json();
        applySteps(data.steps);
        if (data.runtimeStatus === "Completed") {
          stopped = true;
          clearInterval(pollTimer);
          await showResult(jobId, lang, data);
        } else if (["Failed", "Terminated"].includes(data.runtimeStatus)) {
          stopped = true;
          clearInterval(pollTimer);
          showErr(`Job ${data.runtimeStatus.toLowerCase()}.`);
          startBtn.disabled = false;
          startBtn.textContent = "Start translation";
        }
      } catch (err) {
        console.error(err);
      }
    };
    poll();
    pollTimer = setInterval(poll, 4000);
  }

  async function showResult(jobId, lang, data) {
    resultCard.classList.remove("hidden");
    const out = data.output || {};
    const status = out.status || "?";
    const score = typeof out.score === "number" ? out.score.toFixed(2) : "—";
    scoreBadge.textContent = score;
    scoreBadge.className = "text-2xl font-semibold " +
      (status === "completed" ? "text-emerald-400" : "text-amber-400");
    resultMsg.textContent =
      status === "completed"
        ? `Auto-approved (${out.attempts || 1} attempt${(out.attempts || 1) > 1 ? "s" : ""}).`
        : status === "needs_review"
        ? `Needs human review (${out.attempts || 1} attempt${(out.attempts || 1) > 1 ? "s" : ""}).`
        : `Status: ${status}.`;

    if (status === "completed") {
      downloadBtn.href = `/api/jobs/${encodeURIComponent(jobId)}/download?language=${encodeURIComponent(lang)}`;
      downloadBtn.classList.remove("hidden");
    } else if (status === "needs_review") {
      reviewBtn.href = `/api/jobs/${encodeURIComponent(jobId)}/review`;
      reviewBtn.classList.remove("hidden");
      // also allow downloading the DT-only translation
      downloadBtn.href = `/api/jobs/${encodeURIComponent(jobId)}/download?language=${encodeURIComponent(lang)}`;
      downloadBtn.textContent = "Download DT draft .docx";
      downloadBtn.classList.remove("hidden");
    }

    // fetch preview
    try {
      const pr = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/preview/${encodeURIComponent(lang)}`);
      if (pr.ok) {
        const pj = await pr.json();
        srcPreview.textContent = (pj.source || []).join("\n\n") || "(empty)";
        tgtPreview.textContent = (pj.target || []).join("\n\n") || "(empty)";
        preview.classList.remove("hidden");
      }
    } catch (_) {}
    startBtn.disabled = false;
    startBtn.textContent = "Start translation";
  }
})();
