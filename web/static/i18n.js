const _I18N_STORAGE_KEY = 'sc_lang';
const _I18N_DEFAULT     = 'en';

let _locale = {};
let _lang   = localStorage.getItem(_I18N_STORAGE_KEY) || _I18N_DEFAULT;

async function _loadLocale(lang) {
  try {
    const res = await fetch(`/static/locales/${lang}.json`);
    if (!res.ok) throw new Error(res.status);
    _locale = await res.json();
    _lang   = lang;
    localStorage.setItem(_I18N_STORAGE_KEY, lang);
  } catch (e) {
    if (lang !== _I18N_DEFAULT) {
      const res = await fetch(`/static/locales/${_I18N_DEFAULT}.json`);
      _locale = await res.json();
    }
  }
}

async function _populateSelectors() {
  try {
    const res = await fetch('/static/locales/manifest.json');
    if (!res.ok) return;
    const langs = await res.json();
    document.querySelectorAll('.lang-select').forEach(sel => {
      sel.innerHTML = langs.map(l =>
        `<option value="${l.code}"${l.code === _lang ? ' selected' : ''}>${l.label}</option>`
      ).join('');
    });
  } catch (e) { /* manifest missing — leave selectors empty */ }
}

function t(str) {
  return _locale[str] ?? str;
}

function _applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const key = el.getAttribute('data-i18n-html');
    el.innerHTML = t(key);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    el.setAttribute('title', t(key));
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    el.setAttribute('placeholder', t(key));
  });
  document.querySelectorAll('.lang-select').forEach(sel => {
    sel.value = _lang;
  });
}

async function setLang(lang) {
  await _loadLocale(lang);
  _applyI18n();
  document.dispatchEvent(new CustomEvent('i18n:changed', { detail: { lang } }));
}

(async () => {
  await _loadLocale(_lang);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', async () => {
      await _populateSelectors();
      _applyI18n();
    });
  } else {
    await _populateSelectors();
    _applyI18n();
  }
})();
