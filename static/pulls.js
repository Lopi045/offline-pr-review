// PR list: toggle all checkboxes on/off.
function toggleAll(e) {
  e.preventDefault();
  const boxes = document.querySelectorAll('input[name=number]');
  const on = ![...boxes].every(c => c.checked);
  boxes.forEach(c => c.checked = on);
}
