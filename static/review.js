// Review page: renders the diff (unified/split), inline comment editing,
// existing read-only comments, and save/publish/update actions.
// Server data arrives via window.PR (see review.html).
const KEY = window.PR.key;
const FILES = window.PR.files;
const EXISTING = window.PR.existing;
let comments = window.PR.comments;
let view = localStorage.getItem('prview') || 'unified';
let pending = null;  // {path, side, anchor, idx} first click of a potential range

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function copyBranch(el) {
  navigator.clipboard.writeText(el.textContent).then(() => {
    const old = el.textContent;
    el.textContent = '✓ copied';
    setTimeout(() => { el.textContent = old; }, 900);
  });
}

function prefix(t) { return t === 'add' ? '+' : t === 'del' ? '-' : ' '; }

function renderDiff() {
  const out = FILES.map(f => {
    const rows = f.hunks.map(h => {
      const hd = view === 'split'
        ? `<tr class="hunk"><td class="ln"></td><td class="code">${esc(h.header)}</td>` +
          `<td class="ln"></td><td class="code"></td></tr>`
        : `<tr class="hunk"><td class="ln"></td><td class="ln"></td><td class="code">${esc(h.header)}</td></tr>`;
      return hd + (view === 'split' ? splitLines(f.path, h.lines) : unifiedLines(f.path, h.lines));
    }).join('');
    const cls = view === 'split' ? 'diff split' : 'diff';
    return `<div class="file"><div class="fname">${esc(f.path)}</div>
      <table class="${cls}"><tbody>${rows}</tbody></table></div>`;
  }).join('');
  document.getElementById('diff').innerHTML = out;
  bindGutters();
  renderComments();
}

function unifiedLines(path, lines) {
  return lines.map(l => {
    const side = l.type === 'del' ? 'LEFT' : 'RIGHT';
    const line = l.type === 'del' ? l.old : l.new;
    return `<tr class="${l.type}">
      <td class="ln gut" data-path="${esc(path)}" data-line="${line}" data-side="${side}">${l.old || ''}</td>
      <td class="ln gut" data-path="${esc(path)}" data-line="${line}" data-side="${side}">${l.new || ''}</td>
      <td class="code">${esc(prefix(l.type) + l.text)}</td></tr>`;
  }).join('');
}

function splitLines(path, lines) {
  // pair del/add runs; context aligns on both sides
  const rows = [];
  let i = 0;
  const cell = (side, num, txt, type) => num == null
    ? `<td class="ln"></td><td class="code empty"></td>`
    : `<td class="ln gut" data-path="${esc(path)}" data-line="${num}" data-side="${side}">${num}</td>` +
      `<td class="code ${type}">${esc((type === 'del' ? '-' : type === 'add' ? '+' : ' ') + txt)}</td>`;
  while (i < lines.length) {
    const l = lines[i];
    if (l.type === 'ctx') {
      rows.push(`<tr>${cell('LEFT', l.old, l.text, 'ctx')}${cell('RIGHT', l.new, l.text, 'ctx')}</tr>`);
      i++;
    } else {
      const dels = [], adds = [];
      while (i < lines.length && lines[i].type === 'del') dels.push(lines[i++]);
      while (i < lines.length && lines[i].type === 'add') adds.push(lines[i++]);
      const n = Math.max(dels.length, adds.length);
      for (let k = 0; k < n; k++) {
        const d = dels[k], a = adds[k];
        rows.push(`<tr>${d ? cell('LEFT', d.old, d.text, 'del') : cell('LEFT', null)}` +
                  `${a ? cell('RIGHT', a.new, a.text, 'add') : cell('RIGHT', null)}</tr>`);
      }
    }
  }
  return rows.join('');
}

function bindGutters() {
  document.querySelectorAll('td.gut').forEach(td => {
    td.style.cursor = 'pointer';
    td.title = 'click to comment / range';
    td.onclick = () => onGutter(td);
  });
}

function onGutter(td) {
  const path = td.dataset.path, side = td.dataset.side, line = parseInt(td.dataset.line);
  // second click in same file & side extends the pending comment into a range
  if (pending && pending.path === path && pending.side === side && line !== pending.anchor) {
    const c = comments[pending.idx];
    c.start_line = Math.min(pending.anchor, line);
    c.line = Math.max(pending.anchor, line);
    pending = null;
    clearSel();
    renderComments();
    return;
  }
  // first click: drop a single-line comment box and arm it for a range
  comments.push({ path, side, line, start_line: line, body: '' });
  pending = { path, side, anchor: line, idx: comments.length - 1 };
  renderComments();
  markPending(td);
}
function markPending(td) { clearSel(); td.classList.add('sel'); }
function clearSel() { document.querySelectorAll('.sel').forEach(e => e.classList.remove('sel')); }

function renderComments() {
  document.querySelectorAll('tr.cbox-row').forEach(e => e.remove());
  const cols = view === 'split' ? 4 : 3;
  // existing (read-only) comments already on GitHub
  EXISTING.forEach(c => {
    const sel = `td.gut[data-path="${CSS.escape(c.path)}"][data-line="${c.line}"][data-side="${c.side}"]`;
    const td = document.querySelector(sel);
    if (!td) return;
    const nr = document.createElement('tr');
    nr.className = 'cbox-row';
    nr.innerHTML = `<td colspan="${cols}"><div class="ebox">
      <div class="who">${esc(c.author)}</div>${esc(c.body).replace(/\n/g, '<br>')}</div></td>`;
    td.closest('tr').after(nr);
  });
  comments.forEach((c, i) => {
    const sel = `td.gut[data-path="${CSS.escape(c.path)}"][data-line="${c.line}"][data-side="${c.side}"]`;
    const td = document.querySelector(sel);
    if (!td) return;
    const range = c.start_line && c.start_line < c.line ? `lines ${c.start_line}–${c.line}` : `line ${c.line}`;
    const nr = document.createElement('tr');
    nr.className = 'cbox-row';
    nr.innerHTML = `<td colspan="${cols}"><div class="cbox">
      <div class="muted" style="font-size:.8rem">${esc(c.path)} · ${range} · ${c.side}</div>
      <textarea>${esc(c.body)}</textarea>
      <button class="sec" onclick="delComment(${i})">delete</button></div></td>`;
    nr.querySelector('textarea').addEventListener('input', e => { comments[i].body = e.target.value; });
    td.closest('tr').after(nr);
  });
}
function delComment(i) { comments.splice(i, 1); pending = null; clearSel(); renderComments(); }

function setView(v) {
  view = v;
  localStorage.setItem('prview', v);
  document.getElementById('btn-unified').classList.toggle('on', v === 'unified');
  document.getElementById('btn-split').classList.toggle('on', v === 'split');
  pending = null;
  renderDiff();
}

async function post(url) {
  const payload = {
    review_body: document.getElementById('review_body').value,
    event: document.getElementById('event').value,
    pr_comment: document.getElementById('pr_comment').value,
    comments: comments.filter(c => c.body.trim())
  };
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload) });
}
async function saveDraft() {
  await post('/save/' + KEY);
  document.getElementById('status').textContent = 'saved ' + new Date().toLocaleTimeString();
}
async function publish() {
  if (!confirm('Publish review to GitHub now? Your draft will be pushed and then ' +
               'reloaded as read-only comments.')) return;
  await saveDraft();
  document.getElementById('status').textContent = 'publishing…';
  const j = await (await post('/publish/' + KEY)).json();
  if (j.ok) { location.reload(); } else { document.getElementById('status').textContent = '❌ ' + j.error; }
}
async function syncPR() {
  if (!confirm('Publish your saved draft (if any) and re-download the latest PR state?\n' +
               'Note: refreshing resets the local draft.')) return;
  await saveDraft();
  document.getElementById('status').textContent = 'syncing…';
  const j = await (await fetch('/update/' + KEY, { method: 'POST' })).json();
  if (j.ok) { location.reload(); } else { document.getElementById('status').textContent = '❌ ' + j.error; }
}

setView(view);
