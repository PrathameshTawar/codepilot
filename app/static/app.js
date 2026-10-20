/**
 * CodePilot — Apple HIG Frontend Controller
 * Connects to CodePilot FastAPI Endpoints: /tasks, /tasks/{task_id}/approve
 */

(function () {
  "use strict";

  // 1. Theme Controller
  const themeToggleBtn = document.getElementById("themeToggleBtn");
  const themeToggleIcon = document.getElementById("themeToggleIcon");
  const htmlRoot = document.documentElement;

  function applyTheme(theme) {
    htmlRoot.setAttribute("data-theme", theme);
    localStorage.setItem("codepilot-theme", theme);
    if (themeToggleIcon) {
      themeToggleIcon.textContent = theme === "dark" ? "☀️" : "🌙";
    }
  }

  const savedTheme = localStorage.getItem("codepilot-theme") ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(savedTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const current = htmlRoot.getAttribute("data-theme") || "light";
      applyTheme(current === "dark" ? "light" : "dark");
    });
  }

  // 2. Subtle Matrix Canvas
  const canvas = document.getElementById("matrixCanvas");
  if (canvas) {
    const ctx = canvas.getContext("2d");
    let width = 0, height = 0;
    const gridSize = 42;
    let particles = [];

    function resize() {
      const rect = canvas.parentElement.getBoundingClientRect();
      width = canvas.width = rect.width;
      height = canvas.height = rect.height;
      particles = Array.from({ length: 24 }, () => ({
        x: Math.floor(Math.random() * (width / gridSize)) * gridSize,
        y: Math.floor(Math.random() * (height / gridSize)) * gridSize,
        speed: 1.5 + Math.random() * 2,
        radius: 2 + Math.random() * 2,
        opacity: 0.3 + Math.random() * 0.5,
      }));
    }

    function render() {
      const isDark = htmlRoot.getAttribute("data-theme") === "dark";
      ctx.clearRect(0, 0, width, height);

      // Grid
      ctx.lineWidth = 1;
      ctx.strokeStyle = isDark ? "rgba(34, 211, 238, 0.08)" : "rgba(59, 130, 246, 0.08)";
      ctx.beginPath();
      for (let x = 0; x <= width; x += gridSize) { ctx.moveTo(x, 0); ctx.lineTo(x, height); }
      for (let y = 0; y <= height; y += gridSize) { ctx.moveTo(0, y); ctx.lineTo(width, y); }
      ctx.stroke();

      // Pulses
      particles.forEach((p) => {
        p.y += p.speed;
        if (p.y > height) { p.y = 0; p.x = Math.floor(Math.random() * (width / gridSize)) * gridSize; }
        ctx.fillStyle = isDark ? "rgba(34, 211, 238, 0.85)" : "rgba(59, 130, 246, 0.75)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
      });
      requestAnimationFrame(render);
    }

    window.addEventListener("resize", resize);
    resize();
    render();
  }

  // 3. Autonomous Coding Playground Execution
  const runTaskBtn = document.getElementById("runTaskBtn");
  const taskDescInput = document.getElementById("taskDescInput");
  const repoPathInput = document.getElementById("repoPathInput");
  const terminalLogs = document.getElementById("terminalLogs");
  const approvalGate = document.getElementById("approvalGate");
  const approveBtn = document.getElementById("approveBtn");
  const rejectBtn = document.getElementById("rejectBtn");
  const liveStatusText = document.getElementById("liveStatusText");
  const statusBeacon = document.getElementById("statusBeacon");

  let currentTaskId = null;

  function appendLog(text, type = "info") {
    const p = document.createElement("p");
    p.className = `log-line log-${type}`;
    p.textContent = text;
    terminalLogs.appendChild(p);
    terminalLogs.scrollTop = terminalLogs.scrollHeight;
  }

  async function executeTask(description, repoPath = ".") {
    terminalLogs.innerHTML = "";
    approvalGate.style.display = "none";
    runTaskBtn.disabled = true;
    runTaskBtn.textContent = "Executing Sandbox...";
    liveStatusText.textContent = "SANDBOX EXECUTING";
    statusBeacon.style.background = "#ffbd2e";
    statusBeacon.style.boxShadow = "0 0 10px #ffbd2e";

    appendLog(`[CodePilot Engine] Task Dispatched: "${description}"`, "step");
    appendLog(`[Repository] Target Root: ${repoPath}`, "info");

    try {
      const response = await fetch("/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description, repo_path: repoPath }),
      });

      if (!response.ok) {
        throw new Error(`Server returned status ${response.status}`);
      }

      const task = await response.json();
      currentTaskId = task.task_id;

      appendLog(`✓ Task Registered: ${task.task_id.substring(0, 8)}...`, "success");

      // Print Plan Steps
      if (task.plan && task.plan.length > 0) {
        appendLog(`\n[Execution Plan (${task.plan.length} phases)]:`, "step");
        task.plan.forEach((step, idx) => {
          appendLog(`  Phase ${idx + 1}: ${step}`, "info");
        });
      }

      // Print Execution History
      if (task.execution_history && task.execution_history.length > 0) {
        appendLog(`\n[Isolated Sandbox Execution Trace]:`, "step");
        task.execution_history.forEach((run) => {
          appendLog(`  Command: ${run.command} (Exit Code: ${run.exit_code})`, run.passed ? "success" : "warn");
          appendLog(`  Duration: ${run.duration_seconds}s | Timeout: ${run.timed_out}`, "info");
        });
      }

      // Print Final Status
      appendLog(`\n[Resolution Status]: ${task.status.toUpperCase()}`, "success");
      liveStatusText.textContent = "READY FOR APPROVAL";
      statusBeacon.style.background = "#34d399";
      statusBeacon.style.boxShadow = "0 0 10px #34d399";

      // Show Human-in-the-loop Gate
      approvalGate.style.display = "flex";
    } catch (err) {
      appendLog(`\n✗ Sandbox Error: ${err.message}`, "warn");
      liveStatusText.textContent = "EXECUTION FAILED";
      statusBeacon.style.background = "#ef4444";
    } finally {
      runTaskBtn.disabled = false;
      runTaskBtn.textContent = "Run Autonomous Repair ⚡";
    }
  }

  if (runTaskBtn) {
    runTaskBtn.addEventListener("click", () => {
      const desc = taskDescInput.value.trim() || "Fix payment timeout bug in auth service";
      const repo = repoPathInput.value.trim() || ".";
      executeTask(desc, repo);
    });
  }

  // Presets
  document.querySelectorAll(".preset-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      taskDescInput.value = pill.getAttribute("data-preset");
    });
  });

  // Human Approval Handlers
  if (approveBtn) {
    approveBtn.addEventListener("click", async () => {
      if (!currentTaskId) return;
      approveBtn.disabled = true;
      try {
        const res = await fetch(`/tasks/${currentTaskId}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: true, reviewer: "Lead AI Engineer", notes: "AST and Sandbox verified" }),
        });
        if (res.ok) {
          appendLog(`\n✓ Patch Approved & Applied to Main Repository!`, "success");
          approvalGate.style.display = "none";
        }
      } catch (e) {
        appendLog(`Approval error: ${e.message}`, "warn");
      }
    });
  }

  if (rejectBtn) {
    rejectBtn.addEventListener("click", async () => {
      if (!currentTaskId) return;
      rejectBtn.disabled = true;
      try {
        const res = await fetch(`/tasks/${currentTaskId}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: false, reviewer: "Lead AI Engineer", notes: "Rollback requested" }),
        });
        if (res.ok) {
          appendLog(`\n⟲ Patch Rejected — Atomic Rollback Restored Clean State.`, "warn");
          approvalGate.style.display = "none";
        }
      } catch (e) {
        appendLog(`Rejection error: ${e.message}`, "warn");
      }
    });
  }

  // 4. Modals
  const privacyModal = document.getElementById("privacyModal");
  const termsModal = document.getElementById("termsModal");
  const openPrivacyBtn = document.getElementById("openPrivacyBtn");
  const openTermsBtn = document.getElementById("openTermsBtn");

  function openM(m) { if (m) m.classList.add("active"); }
  function closeM(m) { if (m) m.classList.remove("active"); }

  if (openPrivacyBtn) openPrivacyBtn.addEventListener("click", () => openM(privacyModal));
  if (openTermsBtn) openTermsBtn.addEventListener("click", () => openM(termsModal));

  document.querySelectorAll(".modal-close-btn, #acceptPrivacyBtn, #acceptTermsBtn").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeM(privacyModal);
      closeM(termsModal);
    });
  });

  [privacyModal, termsModal].forEach((m) => {
    if (m) m.addEventListener("click", (e) => { if (e.target === m) closeM(m); });
  });

  console.log("CodePilot Apple HIG Frontend Connected.");
})();
