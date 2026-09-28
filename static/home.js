// Home: publish any saved draft + re-download latest PR state, then reload.
async function sync(key, btn) {
  if (!confirm('Publish saved draft (if any) and re-download latest PR state?')) return;
  const t = btn.textContent;
  btn.textContent = 'syncing…';
  btn.disabled = true;
  const j = await (await fetch('/update/' + key, { method: 'POST' })).json();
  if (j.ok) {
    location.reload();
  } else {
    btn.textContent = t;
    btn.disabled = false;
    alert('❌ ' + j.error);
  }
}
