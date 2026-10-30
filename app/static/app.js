const $ = (selector) => document.querySelector(selector);

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.json()).detail || "Request failed");
  return response.json();
}

function itemInput(value) {
  const [title, owner = "Unassigned", due_date = null] = value.split("|").map((part) => part.trim());
  return { title, owner: owner || "Unassigned", due_date: due_date || null };
}

async function load() {
  const [meetings, radar] = await Promise.all([request("/api/meetings"), request("/api/radar")]);
  $("#radar-count").textContent = radar.length;
  $("#radar-list").innerHTML = radar.length ? radar.map((item) => `
    <div class="radar-item">
      <strong>${item.title}</strong>
      <div class="radar-meta"><span>${item.owner} · ${item.due_date || "No due date"}</span><b class="risk-${item.risk}">${item.score}/100 ${item.risk} risk</b></div>
      <div class="nudge">${item.nudge}</div>
    </div>`).join("") : '<p class="muted">Nothing stale. Nice work.</p>';
  $("#meeting-list").innerHTML = meetings.length ? meetings.map((meeting) => `
    <article class="meeting"><div class="meeting-header"><h3>${meeting.title}</h3><small>${new Date(meeting.occurred_at).toLocaleDateString()}</small></div>
    <p class="muted">${meeting.recap || "No recap available."}</p>
    <div class="chips">${meeting.action_items.map((item) => `<span class="chip ${item.status}">${item.title} · ${item.owner}</span>`).join("")}</div></article>`).join("") : '<p class="muted">Your meeting history will appear here.</p>';
}

$("#meeting-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const actions = (form.get("actions") || "").split("\n").map(itemInput).filter((item) => item.title);
  try {
    await request("/api/meetings", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({
      title: form.get("title"), raw_notes: form.get("raw_notes"), participants: (form.get("participants") || "").split(",").map((x) => x.trim()),
      decisions: (form.get("decisions") || "").split("\n").filter(Boolean), action_items: actions,
    })});
    event.target.reset(); $("#form-message").textContent = "Saved. AI recap and carry-forward items are ready."; await load();
  } catch (error) { $("#form-message").textContent = error.message; }
});

$("#brief-button").addEventListener("click", async () => {
  $("#brief-dialog").showModal(); $("#brief-content").textContent = "Generating...";
  try { $("#brief-content").textContent = (await request("/api/brief")).brief; } catch (error) { $("#brief-content").textContent = error.message; }
});
load();
