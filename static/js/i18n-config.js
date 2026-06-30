// i18next 配置和初始化
window.i18nInitialized = false;

function initI18n() {
  return new Promise((resolve, reject) => {
    if (window.i18nInitialized && window.i18next) {
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
        returnObjects: false,
        returnNull: false,
        backend: {
          loadPath: '/static/locales/{{lng}}.json?v=6'
        }
      }, (err, t) => {
        if (err) {
          console.error('i18next initialization failed:', err);
          reject(err);
        } else {
          // 检查资源是否已加载（loaded 事件可能在注册前就已发射）
          window.i18nInitialized = true;
          applyTranslations();
          // 注册 loaded 事件以处理后续语言切换
          i18next.on('loaded', function() {
            applyTranslations();
          });
          resolve(window.i18next.t);
        }
      });
  });
}

function t(key, options) {
  if (!window.i18next || !window.i18next.isInitialized) {
    return key;
  }
  return window.i18next.t(key, options);
}

function applyTranslations() {
  if (!window.i18next || !window.i18next.isInitialized) return;

  const currentLang = window.i18next.language;

  // text content and attributes (support [attribute]key format)
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const attrValue = el.getAttribute('data-i18n');
    if (!attrValue) return;
    
    // Check for [attribute]key format
    const attrMatch = attrValue.match(/^\[(\w+)\](.+)$/);
    if (attrMatch) {
      const attrName = attrMatch[1];
      const key = attrMatch[2];
      const val = t(key);
      if (val && val !== key) {
        el[attrName] = val;
      }
    } else {
      // Regular text content (support data-i18n-opt for parameterized translations)
      var opts = el.getAttribute('data-i18n-opt');
      var options = opts ? JSON.parse(opts) : undefined;
      const val = t(attrValue, options);
      if (val && val !== attrValue) el.textContent = val;
    }
  });

  // placeholders (old format for compatibility)
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    const val = t(key);
    if (val && val !== key) el.placeholder = val;
  });

  // innerHTML (for steps with code tags)
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const key = el.getAttribute('data-i18n-html');
    const val = t(key);
    if (val && val !== key) el.innerHTML = val;
  });

  // update html lang
  document.documentElement.lang = currentLang === 'zh' ? 'zh-CN' : 'en';
}

function setupLanguageChangeListener() {
  window.addEventListener('storage', (e) => {
    if (e.key === 'sdLang') {
      const newLang = e.newValue || 'zh';
      window.i18next.changeLanguage(newLang, () => {
        // reloadResources 确保 HTTP 请求完成的资源已就绪
        window.i18next.reloadResources(newLang).then(() => {
          applyTranslations();
          const activeLink = document.querySelector('.sidebar-menu a.active');
          if (activeLink) {
            const page = activeLink.dataset.page;
            if (typeof switchPage === 'function') switchPage(page);
          }
        });
      });
    }
  });
}

function switchLang(lang) {
  if (!window.i18next) return;
  window.i18next.changeLanguage(lang, () => {
    localStorage.setItem('sdLang', lang);
    // reloadResources 确保 HTTP 请求完成的资源已就绪
    window.i18next.reloadResources(lang).then(() => {
      applyTranslations();
      const activeLink = document.querySelector('.sidebar-menu a.active');
      if (activeLink) {
        const page = activeLink.dataset.page;
        if (typeof switchPage === 'function') switchPage(page);
      }
    });
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
