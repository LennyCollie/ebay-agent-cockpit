// Platz für kleine UI-Interaktionen (z.B. Auto‑Hide Flash-Messages)
setTimeout(() => {
  document.querySelectorAll('.flash').forEach(el => el.style.display = 'none');
}, 5000);
