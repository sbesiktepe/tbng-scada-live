/* TBNG SCADA Live: latest values only, refreshed every 10 s. */
(() => {
  "use strict";
  const TZ = "Europe/Istanbul";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nf = {};
  const fmt = (v, d) => (v == null ? null : (nf[d] ||= new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })).format(v));
  const tf = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  const state = { cards: [], domain: "production", cat: "", q: "" };

  function ago(iso) {
    if (!iso) return "never";
    const s = Math.round((Date.now() - new Date(iso)) / 1000);
    return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : tf.format(new Date(iso));
  }

  function render() {
    const doms = [["production", "Production"], ["sales", "Sales"]];
    $("domainChips").innerHTML = doms.map(([k, l]) => `<button class="chip" data-dom="${k}" aria-pressed="${state.domain === k}">${l} <span>${state.cards.filter((c) => c.domain === k).length}</span></button>`).join("");
    const inDom = state.cards.filter((c) => c.domain === state.domain);
    const cats = [...new Set(inDom.map((c) => c.category))].sort();
    $("catChips").innerHTML = [["", "All"], ...cats.map((c) => [c, c])].map(([k, l]) => `<button class="chip small" data-cat="${esc(k)}" aria-pressed="${state.cat === k}">${esc(l)}</button>`).join("");
    const q = state.q.toLowerCase();
    const vis = inDom.filter((c) => (!state.cat || c.category === state.cat) && (!q || c.name.toLowerCase().includes(q)))
      .sort((a, b) => a.name.localeCompare(b.name, "en"));
    $("note").textContent = inDom.length ? "" : (state.domain === "production"
      ? "No production device is polled directly yet (wells still on the old Cinterion modems report only to the main server)." : "No devices.");
    $("grid").innerHTML = vis.map((c) => `
      <div class="card st-${c.status}">
        <div class="head"><div><div class="name">${esc(c.name)}</div><div class="sub">${esc([c.category, c.region, c.channel ? "CH" + c.channel : ""].filter(Boolean).join(" · "))}</div></div>
          <span class="pill ${c.status}">${{ normal: "Normal", alarm: "Partial", passive: "Passive", waiting: "Waiting" }[c.status]}</span></div>
        <dl>${c.fields.map((f) => `<dt>${esc(f.label)}</dt><dd>${f.value == null ? '<span class="na">-</span>' : fmt(f.value, f.decimals)}<span class="u">${esc(f.unit)}</span></dd>`).join("")}</dl>
        <div class="foot"><span title="${esc(c.error || "")}">${c.status === "passive" || c.status === "alarm" ? esc((c.error || "").slice(0, 50)) : ""}</span><span>${ago(c.lastOk)}</span></div>
      </div>`).join("") || '<p class="note">Nothing to show.</p>';
  }

  async function refresh() {
    try {
      const r = await fetch("/api/cards", { credentials: "same-origin" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      state.cards = (await r.json()).cards;
      if (!state.cards.some((c) => c.domain === state.domain) && state.cards.length) state.domain = state.cards[0].domain;
      render();
    } catch (e) { $("note").textContent = `Server unreachable: ${e.message}`; }
  }

  document.addEventListener("click", (e) => {
    const d = e.target.closest("[data-dom]"), c = e.target.closest("[data-cat]");
    if (d) { state.domain = d.dataset.dom; state.cat = ""; render(); }
    if (c) { state.cat = c.dataset.cat; render(); }
  });
  $("search").addEventListener("input", (e) => { state.q = e.target.value; render(); });
  setInterval(() => { $("clock").textContent = tf.format(new Date()); }, 1000);
  refresh();
  setInterval(refresh, 10000);
})();
