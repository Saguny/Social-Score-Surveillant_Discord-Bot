const _I18N_STORAGE_KEY = 'sc_lang';
const _I18N_DEFAULT     = 'en';

/* Locales whose script needs a slightly different rendering treatment, and any
   right-to-left locale added later. Keeping this here means a new RTL locale
   only needs a manifest entry plus one line below. */
const _I18N_RTL = ['ar', 'he', 'fa', 'ur'];

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
      try {
        const res = await fetch(`/static/locales/${_I18N_DEFAULT}.json`);
        _locale = await res.json();
        _lang   = _I18N_DEFAULT;
      } catch (e2) { /* keep whatever we already had */ }
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
  } catch (e) { /* manifest missing — leave selectors as authored */ }
}

function t(str) {
  return _locale[str] ?? str;
}

function _applyAttr(selector, attr) {
  document.querySelectorAll(`[${selector}]`).forEach(el => {
    el.setAttribute(attr, t(el.getAttribute(selector)));
  });
}

function _applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    el.innerHTML = t(el.getAttribute('data-i18n-html'));
  });
  _applyAttr('data-i18n-title', 'title');
  _applyAttr('data-i18n-placeholder', 'placeholder');
  _applyAttr('data-i18n-aria', 'aria-label');

  document.querySelectorAll('.lang-select').forEach(sel => { sel.value = _lang; });

  const root = document.documentElement;
  root.setAttribute('lang', _lang);
  root.setAttribute('dir', _I18N_RTL.includes(_lang.split('-')[0]) ? 'rtl' : 'ltr');
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
