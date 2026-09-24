const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);

const state = { workers: [], toastTimer: null };
const CRITERIA_TEMPLATE = [
  { id: "PLAN_DIGEST", description: "Exact plan version recorded", required: true },
  { id: "SECURITY_EVIDENCE", description: "Security checks attached", required: true },
  { id: "HUMAN_ACCEPTANCE", description: "Accountable human accepts result", required: true }
];

function money(value) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value || 0));
}

function localDateInput(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  const pad = number => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDate(iso) {
  if (!iso) return "Not scheduled";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "Invalid date" : date.toLocaleString(undefined, {
    dateStyle: "medium", timeStyle: "short"
  });
}

function sourceLink(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && ["jobs.lever.co", "jobs.eu.lever.co"].includes(url.hostname)
      ? url.href : null;
  } catch {
    return null;
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}

function notify(message, type = "success") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.className = `toast ${type === "error" ? "error" : ""}`;
  toast.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { toast.hidden = true; }, 5000);
}

function emptyState(title, detail) {
  return `<div class="empty-state"><strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`;
}

function renderSummary(jobs, opportunities, tracks, searched) {
  const accepted = jobs.filter(job => job.status === "ACCEPTED").length;
  const items = [
    [opportunities.length, searched ? "matching opportunities" : "source-observed opportunities"],
    [tracks.length, "locally tracked applications"],
    [accepted, "locally accepted outcomes"]
  ];
  $("#summary").innerHTML = items.map(([count, label]) =>
    `<div class="snapshot-item"><span class="snapshot-number">${count}</span><span class="snapshot-label">${esc(label)}</span></div>`
  ).join("");
  $("#health-label").textContent = "Reference API connected";
}

function renderOpportunity(item, track) {
  const url = sourceLink(item.source_url);
  const statusTone = item.freshness === "FRESH" ? "good" :
    item.freshness === "MISSING_ONCE" || item.freshness === "STALE" ? "warn" : "";
  const initials = item.organization.slice(0, 2).toUpperCase();
  const reasons = item.match_reasons?.length
    ? `<p class="reason-line">Matched ${esc(item.match_reasons.join(" · "))} · text score ${esc(item.retrieval_score)}</p>`
    : "";
  const options = ["SAVED", "APPLIED", "INTERVIEW", "OFFER", "CLOSED"].map(status =>
    `<option value="${status}"${track?.status === status ? " selected" : ""}>${status}</option>`
  ).join("");
  return `
    <article class="opportunity-card">
      <div class="card-topline">
        <span class="company-avatar" aria-hidden="true">${esc(initials)}</span>
        <span class="pill ${statusTone}">${esc(item.freshness)}</span>
      </div>
      <h3>${esc(item.title)}</h3>
      <p class="company-line">${esc(item.organization)} · ${esc(item.location)}</p>
      <span class="source-line">Public provider API observed</span>
      ${reasons}
      <div class="card-bottomline">
        ${url ? `<a class="source-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">View source posting ↗</a>` : '<span class="form-note">Source link unavailable</span>'}
        <span class="pill">${track ? esc(track.status) : "NOT TRACKED"}</span>
      </div>
      <details class="track-details">
        <summary>${track ? "Update local tracking" : "Track this opportunity"}</summary>
        <form class="mini-form track-form" data-id="${esc(item.id)}">
          <label>Status<select name="status">${options}</select></label>
          <label>Follow-up date and time<input type="datetime-local" name="follow_up_at" value="${esc(localDateInput(track?.follow_up_at))}"></label>
          <label class="wide">Local note<input name="note" maxlength="1000" value="${esc(track?.note || "")}" placeholder="Your next step"></label>
          <p class="form-note">This tracker is local and unauthenticated. Avoid sensitive personal data.</p>
          <button class="button button-secondary" type="submit">Save local status →</button>
        </form>
      </details>
    </article>`;
}

function renderTracks(tracks) {
  $("#tracks").innerHTML = tracks.length ? tracks.map(track => `
    <article class="track-card">
      <div class="card-topline"><span class="pill">${esc(track.status)}</span><span class="pill ${track.opportunity_status === "CLOSED" ? "warn" : ""}">SOURCE ${esc(track.opportunity_status)}</span></div>
      <h3>${esc(track.title)}</h3>
      <p>${esc(track.organization)}</p>
      <p>${track.note ? esc(track.note) : "No note yet."}</p>
      <p>Follow up: <time>${esc(formatDate(track.follow_up_at))}</time></p>
    </article>`).join("") :
    emptyState("Nothing tracked yet", "Open an opportunity card and save your first application status.");
}

function stepState(job, step) {
  const stage = ({ OPEN: 0, APPLIED: 1, IN_PROGRESS: 2, IN_REVIEW: 3, ACCEPTED: 4, UNRESOLVED: 4 })[job.status] ?? 0;
  return step < stage ? "done" : step === stage ? "current" : "";
}

function workerOptions(job) {
  const allowed = job.worker_policy?.allowed_worker_types || [];
  return state.workers.filter(worker => worker.availability === "AVAILABLE" &&
    allowed.includes(worker.worker_type)).map(worker =>
    `<option value="${esc(worker.id)}">${esc(worker.name)} · ${esc(worker.worker_type)}</option>`
  ).join("");
}

function renderApplications(job) {
  const rows = job.applications.map(app => {
    const canSelect = ["PENDING", "SHORTLISTED"].includes(app.status) &&
      ["OPEN", "APPLIED"].includes(job.status);
    return `<div class="application-row">
      <div><strong>${esc(app.worker_name)}</strong><small>${esc(app.worker_type)} · ${esc(app.status)} · bid ${money(app.bid_usd)}</small><small>${esc(app.proposal || "No proposal supplied.")}</small></div>
      ${canSelect ? `<form class="inline-select application-select-form" data-id="${esc(app.id)}"><label class="sr-only" for="reviewer-${esc(app.id)}">Named human selector</label><input id="reviewer-${esc(app.id)}" name="reviewer" required maxlength="120" placeholder="Your name"><button class="small-button" type="submit">Select</button></form>` : ""}
    </div>`;
  }).join("");
  return rows || '<p>No applications yet. A registered worker can apply below.</p>';
}

function renderRun(job, run) {
  if (!run) return '<p>No run yet. Selection is required before replay.</p>';
  const observed = new Set(run.observed_evidence.map(item => item.criterion_id));
  const criteria = job.acceptance_criteria.filter(item => item.id !== "HUMAN_ACCEPTANCE");
  const checklist = criteria.map(item => `<li class="${observed.has(item.id) ? "present" : ""}">${esc(item.id)} · ${esc(item.description || "")} · ${observed.has(item.id) ? "declared" : "missing"}</li>`).join("");
  const failures = run.failure_codes.length ? run.failure_codes.join(", ") : "none";
  return `<div class="run-summary">
    <span class="pill ${run.outcome === "ACCEPTED" ? "good" : "warn"}">${esc(run.outcome)}</span>
    <p>Route: <b>${esc(run.route)}</b> · human decision: <b>${esc(run.human_acceptance)}</b></p>
    <ul class="evidence-list">${checklist}</ul>
    <p>Failure codes: <code>${esc(failures)}</code></p>
    <div class="estimated-economics">Estimated price <b>${money(job.economics.customer_price_usd)}</b> · direct cost <b>${money(job.economics.total_cost_usd)}</b> · contribution <b>${money(job.economics.contribution_margin_usd)}</b><br><small>Synthetic or user-declared assumptions; no paid transaction.</small></div>
  </div>`;
}

function renderJobActions(job, run) {
  if (["OPEN", "APPLIED"].includes(job.status)) {
    const options = workerOptions(job);
    return options ? `<details class="job-action-details"><summary>Submit a worker application</summary>
      <form class="inline-form job-apply-form" data-job="${esc(job.id)}">
        <label>Available worker<select name="worker_id" required>${options}</select></label>
        <label>Work proposal<textarea name="proposal" rows="2" maxlength="800" placeholder="How will this outcome be delivered?"></textarea></label>
        <label>Bid (USD)<input name="bid_usd" type="number" min="0" step="0.01" required value="28"></label>
        <button class="button button-primary" type="submit">Submit application ↗</button>
      </form></details>` :
      '<p>No registered worker fits this job policy. Register one in the studio below.</p>';
  }
  if (job.status === "IN_PROGRESS") {
    return `<form class="job-launch-form" data-job="${esc(job.id)}"><p>One worker is selected. Replay creates an unresolved local run; no tools or agents execute.</p><button class="button button-primary" type="submit">Route and replay →</button></form>`;
  }
  if (job.status === "IN_REVIEW" && run) {
    const observed = new Set(run.observed_evidence.map(item => item.criterion_id));
    const outstanding = job.acceptance_criteria.filter(item =>
      item.id !== "HUMAN_ACCEPTANCE" && !observed.has(item.id)
    );
    const evidenceForm = outstanding.length ? `<form class="inline-form run-evidence-form" data-run="${esc(run.id)}">
      <label>Evidence criterion<select name="criterion_id">${outstanding.map(item => `<option value="${esc(item.id)}">${esc(item.id)}</option>`).join("")}</select></label>
      <label>Named verifier<input name="verifier" required maxlength="120" placeholder="Different from selected worker ID"></label>
      <label>Artifact SHA-256 digest<input name="artifact_sha256" required pattern="[0-9a-f]{64}" maxlength="64" minlength="64" spellcheck="false" placeholder="64 lowercase hexadecimal characters"></label>
      <p class="form-note">The local system records a declared digest; it cannot authenticate the artifact or verifier.</p>
      <button class="button button-secondary" type="submit">Record declaration →</button>
    </form>` : '<p>All non-human criteria have a local declaration. A reviewer can now record a decision.</p>';
    return `${evidenceForm}<hr class="form-divider"><form class="inline-form job-acceptance-form" data-job="${esc(job.id)}">
      <label>Named acceptance reviewer<input name="reviewer" required maxlength="120" placeholder="Accountable reviewer"></label>
      <label>Decision<select name="decision"><option value="ACCEPTED">Accept if criteria are present</option><option value="CORRECTION_REQUIRED">Request correction</option><option value="REJECTED">Reject outcome</option></select></label>
      <button class="button button-primary" type="submit">Record human decision ↗</button>
    </form>`;
  }
  return `<p>This job is ${esc(job.status.toLowerCase())}. Its decision trail remains visible.</p>`;
}

function renderJob(job) {
  const run = job.runs?.[0];
  const tone = job.status === "ACCEPTED" ? "good" :
    ["UNRESOLVED", "IN_REVIEW"].includes(job.status) ? "warn" : "";
  const stages = ["Contract", "Select", "Replay", "Review"];
  return `<article class="job-card">
    <div class="job-head"><div><span class="tiny-label">WORK CONTRACT · ${esc(job.id)}</span><h3>${esc(job.title)}</h3><p>${esc(job.objective)}</p></div><div class="job-tags"><span class="pill ${tone}">${esc(job.status)}</span><span class="pill">${esc(job.evidence_class)}</span></div></div>
    <div class="job-meta"><span>Budget <b>${money(job.budget_usd)}</b></span><span>${job.applications.length} applications</span><span>Independent verifier: <b>${job.worker_policy?.requires_independent_verifier ? "required" : "optional"}</b></span></div>
    <div class="job-steps" aria-label="Workflow stage">${stages.map((label, index) => `<span class="job-step ${stepState(job, index)}"><i aria-hidden="true"></i>${label}</span>`).join("")}</div>
    <div class="job-content-grid">
      <div class="job-panel"><h4>Applications and next step</h4>${renderApplications(job)}${renderJobActions(job, run)}</div>
      <div class="job-panel"><h4>Result and evidence</h4>${renderRun(job, run)}</div>
    </div>
  </article>`;
}

function renderWorkers(workers) {
  $("#workers").innerHTML = workers.length ? workers.map(worker => `
    <div class="worker-card"><strong>${esc(worker.name)}</strong><span>${esc(worker.worker_type)} · ${esc(worker.id)}</span></div>
  `).join("") : emptyState("No workers registered", "Use the form above to add a local worker record.");
}

function renderEvolution(candidates) {
  $("#evolution").innerHTML = candidates.length ? candidates.map(candidate => `
    <div class="evolution-item"><div class="card-topline"><strong>${esc(candidate.version)}</strong><span class="pill ${candidate.status === "PROMOTED" ? "good" : "warn"}">${esc(candidate.status)}</span></div><p>Holdout: ${candidate.metrics?.holdout_passed ? "declared passed" : "not passed"} · cost per accepted outcome: ${candidate.metrics?.cost_per_accepted_outcome_usd == null ? "undefined" : money(candidate.metrics.cost_per_accepted_outcome_usd)}</p></div>
  `).join("") : '<p>No local candidates.</p>';
}

async function refresh() {
  const search = new FormData($("#search-form"));
  const query = new URLSearchParams();
  if (String(search.get("q") || "").trim()) query.set("q", String(search.get("q")).trim());
  if (String(search.get("location") || "").trim()) query.set("location", String(search.get("location")).trim());
  const opportunityPath = "/api/opportunities" + (query.size ? `?${query}` : "");
  const [jobs, workers, evolution, opportunities, tracks] = await Promise.all([
    api("/api/jobs"), api("/api/workers"), api("/api/evolution"),
    api(opportunityPath), api("/api/tracks")
  ]);
  state.workers = workers.workers;
  const byOpportunity = new Map(tracks.tracks.map(item => [item.opportunity_id, item]));
  $("#opportunities").innerHTML = opportunities.opportunities.length
    ? opportunities.opportunities.map(item => renderOpportunity(item, byOpportunity.get(item.id))).join("")
    : emptyState(query.size ? "No matching opportunities" : "No opportunities imported",
      query.size ? "Try a broader title or location." : "Import a public Lever board with the CLI in the README.");
  $("#opportunity-count").textContent = `${opportunities.opportunities.length} ${query.size ? "matching" : "active"} opportunities`;
  renderTracks(tracks.tracks);
  $("#jobs").innerHTML = jobs.jobs.length ? jobs.jobs.map(renderJob).join("") :
    emptyState("No work contracts yet", "Publish a local contract in the studio below.");
  renderWorkers(workers.workers);
  renderEvolution(evolution.candidates);
  renderSummary(jobs.jobs, opportunities.opportunities, tracks.tracks, query.size > 0);
}

async function postForm(form, path, payload, message) {
  const button = form.querySelector('button[type="submit"]');
  if (button) button.disabled = true;
  try {
    await api(path, { method: "POST", body: JSON.stringify(payload) });
    await refresh();
    notify(message);
  } catch (error) {
    notify(error.message, "error");
  } finally {
    if (button?.isConnected) button.disabled = false;
  }
}

function initMotion() {
  const elements = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window) ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    elements.forEach(element => element.classList.add("visible"));
    return;
  }
  document.documentElement.classList.add("motion-ready");
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  elements.forEach(element => observer.observe(element));
}

document.addEventListener("submit", async event => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  event.preventDefault();
  if (form.id === "search-form") {
    try { await refresh(); } catch (error) { notify(error.message, "error"); }
    return;
  }
  const values = new FormData(form);
  if (form.classList.contains("track-form")) {
    let followUp = null;
    try {
      const local = String(values.get("follow_up_at") || "");
      followUp = local ? new Date(local).toISOString() : null;
    } catch {
      notify("Enter a valid follow-up date and time.", "error");
      return;
    }
    await postForm(form, `/api/opportunities/${encodeURIComponent(form.dataset.id)}/track`,
      { status: values.get("status"), note: values.get("note"), follow_up_at: followUp },
      "Local application status saved.");
  } else if (form.classList.contains("job-apply-form")) {
    await postForm(form, `/api/jobs/${encodeURIComponent(form.dataset.job)}/applications`,
      { worker_id: values.get("worker_id"), proposal: values.get("proposal"), bid_usd: Number(values.get("bid_usd")) },
      "Worker application submitted.");
  } else if (form.classList.contains("application-select-form")) {
    await postForm(form, `/api/applications/${encodeURIComponent(form.dataset.id)}/decision`,
      { status: "SELECTED", reviewer: values.get("reviewer") }, "Human selection recorded.");
  } else if (form.classList.contains("job-launch-form")) {
    await postForm(form, `/api/jobs/${encodeURIComponent(form.dataset.job)}/launch`, {},
      "Synthetic replay created. The run remains unresolved.");
  } else if (form.classList.contains("run-evidence-form")) {
    await postForm(form, `/api/runs/${encodeURIComponent(form.dataset.run)}/evidence`,
      { criterion_id: values.get("criterion_id"), verifier: values.get("verifier"),
        artifact_sha256: values.get("artifact_sha256") }, "Operator-declared evidence recorded.");
  } else if (form.classList.contains("job-acceptance-form")) {
    await postForm(form, `/api/jobs/${encodeURIComponent(form.dataset.job)}/acceptance`,
      { reviewer: values.get("reviewer"), decision: values.get("decision") }, "Human decision recorded.");
  } else if (form.id === "job-form") {
    const allowed = values.getAll("worker_type");
    if (!allowed.length) { notify("Choose at least one worker type.", "error"); return; }
    await postForm(form, "/api/jobs", {
      title: values.get("title"), objective: values.get("objective"),
      budget_usd: Number(values.get("budget")), customer_price_usd: Number(values.get("budget")),
      acceptance_criteria: CRITERIA_TEMPLATE,
      worker_policy: { allowed_worker_types: allowed, requires_independent_verifier: true },
      evidence_class: "SYNTHETIC"
    }, "Local work contract published.");
  } else if (form.id === "worker-form") {
    await postForm(form, "/api/workers", {
      name: values.get("name"), worker_type: values.get("type"),
      capabilities: String(values.get("capabilities") || "").split(",").map(item => item.trim()).filter(Boolean)
    }, "Local worker record registered.");
  }
});

$("#clear-search").addEventListener("click", () => {
  $("#search-form").reset();
  refresh().catch(error => notify(error.message, "error"));
});
initMotion();
refresh().catch(error => {
  $("#health-label").textContent = "Reference API unavailable";
  notify(error.message, "error");
});
