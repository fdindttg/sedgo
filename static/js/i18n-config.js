// i18next 配置和初始化
let i18nInitialized = false;

function initI18n() {
  return new Promise((resolve, reject) => {
    if (i18nInitialized && window.i18next) {
      resolve(window.i18next.t);
      return;
    }
    
    const currentLang = localStorage.getItem('sdLang') || 'zh';
    
    i18next
      .use(window.i18nextHttpBackend)
      .init({
        fallbackLng: 'zh',
        debug: false,
        lng: currentLang,
        supportedLngs: ['zh', 'zh-TW', 'en', 'ja', 'ko', 'ru', 'vi', 'es'],
        backend: {
          loadPath: '/static/locales/{{lng}}.json'
        }
      }, (err, t) => {
        if (err) {
          console.error('i18next initialization failed:', err);
          reject(err);
        } else {
          i18nInitialized = true;
          window.t = t;
          resolve(t);
        }
      });
  });
}

function t(key) {
  if (!i18nInitialized || !window.i18next) {
    return key;
  }
  return window.i18next.t(key);
}

function applyTranslations() {
  if (!i18nInitialized) return;

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const attrValue = el.getAttribute('data-i18n');
    if (!attrValue) return;
    
    const attrMatch = attrValue.match(/^\[(\w+)\](.+)$/);
    if (attrMatch) {
      const attrName = attrMatch[1];
      const key = attrMatch[2];
      const val = t(key);
      if (val && val !== key) {
        el[attrName] = val;
      }
    } else {
      const val = t(attrValue);
      if (val && val !== attrValue) el.textContent = val;
    }
  });
}

function setupLanguageChangeListener() {
  window.addEventListener('storage', (e) => {
    if (e.key === 'sdLang') {
      const newLang = e.newValue || 'zh';
      window.i18next.changeLanguage(newLang, (err, t) => {
        if (!err) {
          applyTranslations();
          
          const activeLink = document.querySelector('.sidebar-menu a.active');
          if (activeLink) {
            const page = activeLink.dataset.page;
            if (typeof switchPage === 'function') switchPage(page);
          }
        }
      });
    }
  });
}

function switchLang(lang) {
  if (!window.i18next) return;
  window.i18next.changeLanguage(lang, (err, t) => {
    if (err) {
      console.error('Failed to change language:', err);
      return;
    }
    localStorage.setItem('sdLang', lang);
    applyTranslations();
    
    const activeLink = document.querySelector('.sidebar-menu a.active');
    if (activeLink) {
      const page = activeLink.dataset.page;
      if (typeof switchPage === 'function') switchPage(page);
    }
  });
}

function setupLangMenuListeners() {
  const langMenu = document.getElementById('lang-menu');
  const langBtn = document.querySelector('.lang-btn');
  const langOptions = document.querySelectorAll('.lang-option');
  
  if (langBtn) {
    langBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      langMenu.classList.toggle('open');
    });
  }
  
  langOptions.forEach(opt => {
    opt.addEventListener('click', () => {
      const lang = opt.dataset.lang;
      switchLang(lang);
      langMenu.classList.remove('open');
    });
  });
  
  document.addEventListener('click', () => {
    if (langMenu) langMenu.classList.remove('open');
  });
}

function getCurrentLang() {
  return localStorage.getItem('sdLang') || 'zh';
}
