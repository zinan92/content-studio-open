'use strict';
/* In-memory form drafts survive navigation. Server facts remain the only saved value. */
function createFormState() {
  const groups = new Map();
  const copy = (v) => JSON.parse(JSON.stringify(v));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  return {
    load(key, values, { mergeUntouched = false } = {}) {
      let s = groups.get(key);
      if (!s) { s = { baseline: copy(values), values: copy(values), dirty: false, saving: false, revision: 0, touched: {}, message: '当前设置已保存', state: 'saved' }; groups.set(key, s); }
      else if (mergeUntouched && !s.saving) {
        for (const [field, value] of Object.entries(values)) if (!s.touched[field]) s.values[field] = copy(value);
        s.baseline = copy(values); s.dirty = !same(s.values, s.baseline);
        s.state = s.dirty ? 'dirty' : 'saved'; s.message = s.dirty ? '未保存 · 切页后改动仍保留' : '当前设置已保存';
      }
      else if (!s.dirty && !s.saving) {
        if (s.acknowledged && !same(values, s.acknowledged)) return s;
        s.acknowledged = null; s.values = s.baseline = copy(values);
      }
      return s;
    },
    get(key) { return groups.get(key); },
    edit(key, values) {
      const s = groups.get(key); if (!s) return;
      for (const key of Object.keys(values)) if (!same(values[key], s.values[key])) s.touched[key] = true;
      s.values = copy(values); s.revision++; s.dirty = !same(s.values, s.baseline);
      if (!s.saving) { s.state = s.dirty ? 'dirty' : 'saved'; s.message = s.dirty ? '未保存 · 切页后改动仍保留' : '当前设置已保存'; }
      return s;
    },
    begin(key) {
      const s = groups.get(key); if (!s || s.saving) return null;
      s.saving = true; s.state = 'saving'; s.message = '正在保存…';
      return { values: copy(s.values), revision: s.revision };
    },
    complete(key, sent, canonical = sent.values) {
      const s = groups.get(key); s.saving = false;
      if (same(s.values, sent.values)) s.values = copy(canonical);
      s.baseline = copy(canonical); s.acknowledged = copy(canonical); s.dirty = !same(s.values, s.baseline);
      s.state = s.dirty ? 'dirty' : 'saved'; s.message = s.dirty ? '上一版已保存；新改动还未保存' : '已保存';
      return s;
    },
    fail(key, error) {
      const s = groups.get(key); s.saving = false; s.state = 'error'; s.message = `保存失败：${error}；改动已保留，可重试。`; return s;
    },
    hasDirty() { return [...groups.values()].some((s) => s.dirty || s.saving); },
  };
}
const FormState = createFormState();
function paintFormState(key, form) {
  const s = FormState.get(key); if (!s || !form) return;
  let out = form.querySelector('[data-save-status]');
  if (!out) { out = document.createElement('p'); out.dataset.saveStatus = ''; out.className = 'ui-save-status'; out.setAttribute('role', 'status');
    // 「已保存」放在保存按钮左边同一行（10/9）；按钮不在自己那一行里的老表单照旧放最后
    const host = form.querySelector('button[type="submit"]')?.parentElement;
    if (host && host !== form) host.insertBefore(out, host.firstChild); else form.append(out); }
  out.textContent = s.message; out.dataset.state = s.state;
  const button = form.querySelector('button[type="submit"]'); if (button) button.disabled = s.saving || form.dataset.awaitingRead === '1';
}
function bindFormDraft(key, form, read) {
  if (!form) return;
  form.oninput = () => { FormState.edit(key, read()); paintFormState(key, form); };
  paintFormState(key, form);
}
async function submitFormDraft(key, form, read, send) {
  if (FormState.get(key)?.saving) return false;
  FormState.edit(key, read());
  const sent = FormState.begin(key); if (!sent) return false;
  paintFormState(key, form);
  try { const result = await send(sent.values); FormState.complete(key, sent, result?.savedValues || sent.values); paintFormState(key, form); return true; }
  catch (err) { FormState.fail(key, err.message); paintFormState(key, form); return false; }
}
if (typeof window !== 'undefined') {
  window.FormState = FormState;
  window.addEventListener('beforeunload', (event) => { if (FormState.hasDirty()) { event.preventDefault(); event.returnValue = ''; } });
}
if (typeof module !== 'undefined') module.exports = { createFormState };
