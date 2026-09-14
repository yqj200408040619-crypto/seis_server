function fmtUnix(ts) {
  if (!ts) return '-';
  const d = new Date(Number(ts) * 1000);
  if (Number.isNaN(d.getTime())) return '-';
  return d.toISOString().replace('T', ' ').replace('Z', ' UTC');
}

document.querySelectorAll('.unix-time').forEach(el => {
  el.textContent = fmtUnix(el.dataset.unix);
});
