const f = document.getElementById("f");
const err = document.getElementById("err");
const go = document.getElementById("go");

f.addEventListener("submit", async (e) => {
  e.preventDefault();
  err.hidden = true;
  go.disabled = true;
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: f.code.value }),
    });
    const json = await res.json().catch(() => ({}));
    if (res.ok) { location.replace("/"); return; }
    err.textContent = json.error || "Sign-in failed.";
  } catch {
    err.textContent = "Can't reach the PC. Is Project Tracker running?";
  }
  err.hidden = false;
  go.disabled = false;
  f.code.select();
});
