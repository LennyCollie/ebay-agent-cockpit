// Platz für kleine UI-Interaktionen (z.B. Auto‑Hide Flash-Messages)
setTimeout(() => {
  document.querySelectorAll('.flash').forEach(el => el.style.display = 'none');
}, 5000);
document.addEventListener('DOMContentLoaded', () => {
  const textarea = document.querySelector('textarea[name="query"]');
  if (!textarea) return;

  const FREE_LIMIT = 3; // reine Anzeige; server-seitig gilt die echte Regel
  textarea.addEventListener('input', () => {
    const list = textarea.value
      .split(/\n|,/)
      .map(s => s.trim())
      .filter(Boolean);
    if (list.length > FREE_LIMIT) {
      textarea.classList.add('is-invalid');
    } else {
      textarea.classList.remove('is-invalid');
    }
  });
});