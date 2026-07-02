const next = new URLSearchParams(location.search).get("next") || "/social-credit/admin";
document.getElementById("form").addEventListener("submit", async e => {
  e.preventDefault();
  const res = await fetch("/api/auth", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({token: document.getElementById("token").value})
  });
  if (res.ok) { location.href = next; }
  else {
    const err = document.getElementById("err");
    err.textContent = res.status === 429 ? "Too many attempts. Try again later." : "Invalid token.";
    err.style.display = "block";
  }
});
