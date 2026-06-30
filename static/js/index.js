// 积分/秒配置缓存（从后台动态加载）
let _pointsPerSecCache = null;
// 图片生成成本缓存（从后台拉取）
let _imageCostsCache = null;
// 模型配置缓存（包含支持的分辨率等信息）
let _modelsConfigCache = null;
// 短剧模式：单集 or 连续剧
let _dramaIsSingleEpisode = false;

function showPricingTab(tab) {
  document.querySelectorAll('.pricing-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.pricing-content').forEach(c => c.style.display = 'none');
  
  document.getElementById('tab-' + tab).classList.add('active');
  document.getElementById('pricing-' + tab).style.display = 'block';
}

// 全局变量存储当前计费周期
let isAnnualBilling = false;
let subscriptionPlansData = [];

async function loadSubscriptionPlans() {
  try {
    const response = await fetch('/api/subscriptions/plans');
    const plans = await response.json();
    subscriptionPlansData = plans;
    
    // 更新折扣标签显示实际折扣值
    const promoBadge = document.querySelector('.promo-badge');
    if (promoBadge && plans.length > 0) {
      const discount = plans[0].annual_discount || 17;
      promoBadge.textContent = `省 ${discount}%`;
    }
    
    renderSubscriptionCards();
  } catch (error) {
    console.error('Failed to load subscription plans:', error);
  }
}

// 定价计划名称和描述的翻译映射
function getPlanTranslation(key, defaultValue) {
  const translationKey = `pricing.plans.${key}`;
  const translated = t(translationKey);
  return translated !== translationKey ? translated : defaultValue;
}

function renderSubscriptionCards() {
  const container = document.getElementById('pricing-cards-container');
  if (!container) return;
  
  container.innerHTML = '';
  
  subscriptionPlansData.forEach((plan, index) => {
    const isFeatured = plan.id === 2;
    
    // 计算价格：按年付折扣
    const monthlyPrice = plan.price_cents / 100;
    const discount = plan.annual_discount || 17;
    const annualMonthly = isAnnualBilling ? monthlyPrice * (100 - discount) / 100 : null;
    const displayPrice = isAnnualBilling ? annualMonthly.toFixed(2) : monthlyPrice.toFixed(2);
    const originalPrice = isAnnualBilling ? monthlyPrice.toFixed(2) : null;
    const period = isAnnualBilling ? t('pricing.monthly_annual') : t('pricing.monthly');
    const annualPrice = isAnnualBilling ? (annualMonthly * 12).toFixed(2) : null;
    
    // 从缓存中获取任意可用的720p配置，不使用硬编码的模型ID
    let pts720pPerSec = 4;
    const config = _pointsPerSecCache || {};
    for (const [, modelConfig] of Object.entries(config)) {
        if (modelConfig && modelConfig['720p']) {
            pts720pPerSec = modelConfig['720p'];
            break;
        }
    }
    const minutes = Math.floor(plan.points_per_month / (pts720pPerSec * 60));
    
    const card = document.createElement('div');
    card.className = `pricing-card ${isFeatured ? 'featured' : ''}`;
    
    const features = [
      `✓ ${plan.points_per_month.toLocaleString()} ${t('pricing.points_per_month')}`,
      `✓ ${plan.max_batch_size} ${t('pricing.max_batch_size')}`,
      `✓ ${plan.max_concurrent_tasks || 1} ${t('pricing.max_concurrent_tasks')}`,
      `✓ ${plan.max_resolution === '1080p' ? t('pricing.full_hd') : t('pricing.hd')}${t('pricing.output_support')}`,
      `✓ ${t('pricing.priority_support')}`,
      `✓ ${t('pricing.custom_watermark')}`,
      `✓ ${t('pricing.seedance_video')}`,
      `✓ ${t('pricing.multi_models')}`,
      `✓ ${t('pricing.private_space')}`
    ];
    
    // 获取翻译后的计划名称和描述
    const planName = getPlanTranslation(`name_${plan.id}`, plan.name);
    const planDesc = getPlanTranslation(`desc_${plan.id}`, plan.description || '');
    
    card.innerHTML = `
      ${isFeatured ? `<div class="featured-badge">${t('pricing.recommended')}</div>` : ''}
      <div class="pricing-card-header">
        <h3>${planName}</h3>
        <p class="pricing-card-desc">${planDesc}</p>
      </div>
      <div class="pricing-card-price">
        ${originalPrice ? `<span class="price-original" style="text-decoration: line-through; color: #999; font-size: 0.8em; margin-right: 8px;">$${originalPrice}</span>` : ''}
        <span class="price-currency">USD</span>
        <span class="price-amount">${displayPrice}</span>
        <span class="price-period">${period}</span>
      </div>
      ${annualPrice ? `<div style="color: #666; font-size: 0.9em; margin-top: 4px;">${t('pricing.annual_total')} $${annualPrice}</div>` : ''}
      <ul class="pricing-card-features">
        ${features.map(f => `<li>${f}</li>`).join('')}
      </ul>
      <button class="pricing-card-btn ${isFeatured ? 'primary' : ''}" onclick="subscribeToPlan(${plan.id}, ${isAnnualBilling})">${t('pricing.subscribe_now')}</button>
    `;
    
    container.appendChild(card);
  });
}

async function loadCreditPackages() {
  const container = document.getElementById('credits-cards-container');
  if (!container) return;
  try {
    const res = await fetch('/api/payments/packages');
    const data = await res.json();
    const packages = data.packages || [];
    container.innerHTML = packages.map(pkg => {
      const price = '$' + (pkg.price_cents / 100).toFixed(0);
      const points = pkg.points.toLocaleString();
      return `<div class="credits-card ${pkg.featured ? 'featured' : ''}">
        ${pkg.featured ? `<div class="featured-badge">推荐</div>` : ''}
        <h3>${pkg.name}</h3>
        <div class="credits-card-price">${price}</div>
        <ul class="credits-card-features">
          <li>✓ ${points}</li>
          <li>✓ 包含所有功能</li>
          <li>✓ 积分永不过期</li>
        </ul>
        <button class="credits-card-btn ${pkg.featured ? 'primary' : ''}" onclick="openTopupModal && openTopupModal('${pkg.key}')">立即购买</button>
      </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = '<div style="color:var(--t3);text-align:center;padding:20px;">加载失败</div>';
  }
}

async function loadModelPricingTable() {
  const wrap = document.getElementById('model-pricing-tables');
  if (!wrap) return;
  try {
    const cfg = await _getPointsPerSec();
    const resolutions = ['480p', '720p', '1080p'];
    const durations = [5, 10, 15];

    let rows = '';
    for (const [, val] of Object.entries(cfg)) {
      const label = val.label || '';
      for (const res of resolutions) {
        const perSec = val[res];
        if (perSec == null) continue;
        const costs = durations.map(d => Math.max(0.1, Math.round(perSec * d * 10) / 10));
        rows += `<tr>
          <td class="price-model">${label}</td>
          <td>${res}</td>
          <td><span class="credit-pill">${perSec} </span></td>
          ${costs.map(c => `<td>${c} </td>`).join('')}
        </tr>`;
      }
    }

    wrap.innerHTML = `<table class="pricing-table">
      <thead><tr>
        <th>模型</th><th>分辨率</th><th>积分/秒</th><th>5秒</th><th>10秒</th><th>15秒</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  } catch (e) {
    wrap.innerHTML = '<div style="color:var(--t3);text-align:center;padding:20px;">加载失败</div>';
  }
}

function toggleBillingCycle() {
  isAnnualBilling = !isAnnualBilling;
  
  // 更新切换按钮状态
  const toggle = document.getElementById('billing-toggle');
  if (toggle) {
    toggle.classList.toggle('on', !isAnnualBilling);
    toggle.classList.toggle('off', isAnnualBilling);
  }
  
  // 重新渲染卡片
  renderSubscriptionCards();
}

async function subscribeToPlan(planId, isAnnual = false) {
  const token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
  if (!token) {
    alert(t('js.signin_first'));
    return;
  }
  
  try {
    const response = await fetch('/api/subscriptions/subscribe', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ 
        plan_id: planId,
        billing_cycle: isAnnual ? 'annual' : 'monthly'
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      alert(t('js.subscribe_success') + '!');
      location.reload();
    } else {
      alert(t('js.subscribe_failed') + ': ' + (result.detail || t('js.unknown_error')));
    }
  } catch (error) {
    console.error('Failed to subscribe:', error);
    alert(t('js.subscribe_failed') + ': ' + error.message);
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  // 先初始化 i18next 和积分配置（并行）
  await Promise.all([initI18n(), _getPointsPerSec(), _getImageCosts()]);

  // After config loads, update all cost displays
  updateVideoCostDisplay();
  updateImageCostDisplay();
  updateDramaCostDisplay();

  // 监听积分配置更新广播
  if (window.BroadcastChannel) {
    const channel = new BroadcastChannel('pointsConfig');
    channel.addEventListener('message', async (event) => {
      if (event.data.type === 'refresh') {
        await refreshPointsConfig();
        updateVideoCostDisplay();
        updateImageCostDisplay();
        loadSubscriptionPlans();
        loadModelPricingTable();
      }
    });
  }

  // 应用翻译
  applyTranslations();

  // 然后加载订阅计划（需要翻译）
  loadSubscriptionPlans();
  loadCreditPackages();
  loadModelPricingTable();
  
  // 绑定定价标签切换事件
  const tabTeam = document.getElementById('tab-team');
  if (tabTeam) {
    tabTeam.addEventListener('click', () => showPricingTab('team'));
  }
  const tabCredits = document.getElementById('tab-credits');
  if (tabCredits) {
    tabCredits.addEventListener('click', () => showPricingTab('credits'));
  }
  
  // 绑定计费周期切换事件
  const billingToggle = document.getElementById('billing-toggle');
  if (billingToggle) {
    billingToggle.addEventListener('click', toggleBillingCycle);
  }
  
  // 初始化 AI 优化提示词按钮
  initAIEnhanceButtons();
  
  // 初始化视频积分消耗显示
  updateVideoCostDisplay();
  
  // 添加视频模型选择器的事件监听器
  const videoModelSelect = document.getElementById('modelSelect-video');
  if (videoModelSelect) {
    videoModelSelect.addEventListener('change', updateVideoCostDisplay);
  }
  
  // 初始化图片积分消耗显示（移至下方 dropdown 节处理避免跨作用域）
  

  // 预先加载短剧项目列表 - URL参数处理移至下方dropdown节避免跨作用域
});

// i18next 初始化
let i18nInitialized = false;

function initI18n() {
  return new Promise((resolve, reject) => {
    i18next
      .use(window.i18nextHttpBackend)
      .init({
        fallbackLng: 'zh',
        debug: false,
        lng: localStorage.getItem('sdLang') || 'zh',
        supportedLngs: ['zh', 'zh-TW', 'en', 'ja', 'ko', 'ru', 'vi', 'es'],
        backend: {
          loadPath: '/static/locales/{{lng}}.json'
        }
      }, (err, tFn) => {
        if (err) {
          console.error('i18next initialization failed:', err);
          reject(err);
        } else {
          i18nInitialized = true;
          window.t = tFn;
          console.log('[i18n] initialized, language:', window.i18next.language, 'sdLang:', localStorage.getItem('sdLang'));
          resolve(tFn);
        }
      });
  });
}

// 简化的翻译函数，兼容现有代码
function t(key) {
  if (!i18nInitialized || !window.i18next) {
    return key;
  }
  return window.i18next.t(key);
}

function applyTranslations() {
  if (!i18nInitialized) return;

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

  // update page title
  document.title = currentLang === 'zh' ? 'SedGo — AI 视频生成' : 'SedGo — AI Video Generation';

  // update lang button text
  const langBtn = document.getElementById('lang-btn');
  const langNames = { zh:t('lang.zh'), 'zh-TW':t('lang.zh-TW'), en:t('lang.en'), ja:t('lang.ja'), ko:t('lang.ko'), ru:t('lang.ru'), vi:t('lang.vi'), es:t('lang.es') };
  if (langBtn) {
    langBtn.textContent = langNames[currentLang] || currentLang;
  }

  // highlight active lang option
  document.querySelectorAll('.lang-option').forEach(opt => {
    opt.classList.toggle('active', opt.getAttribute('data-lang') === currentLang);
  });

  // update upload count format
  updateUploadCountDisplay();

  // update prompt hints
  const hintVideo1 = document.getElementById('hint-video-1');
  const hintVideo2 = document.getElementById('hint-video-2');
  const hintAivideo1 = document.getElementById('hint-aivideo-1');
  const hintAivideo2 = document.getElementById('hint-aivideo-2');
  
  if (hintVideo1) hintVideo1.textContent = t('gen.hint1');
  if (hintVideo2) hintVideo2.textContent = t('gen.hint2');
  if (hintAivideo1) hintAivideo1.textContent = t('gen.hint3');
  if (hintAivideo2) hintAivideo2.textContent = t('gen.hint2');

  // update signed-in button if applicable
  updateSignInButtonText();

  // refresh idle generate buttons (not mid-generation) — with emoji prefix
  var genBtnLabels = {
    'gen-btn-video': { key: 'js.generate', emoji: '🎬' },
    'gen-btn-aivideo': { key: 'js.generate', emoji: '🎬' },
    'gen-btn-drama': { key: 'js.generate', emoji: '🎬' },
  };
  Object.keys(genBtnLabels).forEach(function(id) {
    var btn = document.getElementById(id);
    var cfg = genBtnLabels[id];
    if (btn && !btn.disabled) btn.innerHTML = cfg.emoji + ' ' + t(cfg.key);
  });
  const imgBtn = document.getElementById('gen-btn-image');
  if (imgBtn && !imgBtn.disabled) imgBtn.innerHTML = '🎨 ' + t('js.generate_image');

  // re-render task cards with new language
  if (typeof renderTaskList === 'function') {
    try { if (currentTasks && currentTasks.length > 0) renderTaskList(); } catch(e) {}
  }

  // refresh ref-mode hint with current active mode
  const activeRefItem = document.querySelector('#refModeMenu-video .dropdown-item.active');
  if (activeRefItem) {
    updateRefModeHint('video', activeRefItem.getAttribute('data-value'));
  }

  // destroy dynamic asset library modal so it rebuilds with new language next open
  const dynModal = document.getElementById('ref-file-library-modal');
  if (dynModal) dynModal.remove();
}

function updateUploadCountDisplay() {
  const countEl = document.querySelector('.upload-count');
  if (countEl) {
    const count = uploadedFiles.length;
    countEl.textContent = count + '/12 ' + t('gen.files');
  }
}

function updateSignInButtonText() {
  const btn = document.getElementById('sign-in-btn');
  const key = apiKey();
  if (key && btn) {
    btn.textContent = t('js.signed_in_alt');
  }
}

function switchLang(lang) {
  if (!window.i18next) return;
  window.i18next.changeLanguage(lang, (err, tFn) => {
    if (err) {
      console.error('Failed to change language:', err);
      return;
    }
    localStorage.setItem('sdLang', lang);
    window.t = tFn;
    applyTranslations();
  });
}

// ── State ─────────────────────────────────────────────────────────
let uploadedFiles = [];
let currentUser = null;
let authToken = localStorage.getItem('sdToken') || '';

// Apply translations on load
applyTranslations();

// ── Language dropdown ──────────────────────────────────────────────
const langBtn = document.getElementById('lang-btn');
const langMenu = document.getElementById('lang-menu');

if (langBtn) langBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  langMenu.classList.toggle('open');
});

document.querySelectorAll('.lang-option').forEach(opt => {
  opt.addEventListener('click', (e) => {
    e.stopPropagation();
    const lang = opt.getAttribute('data-lang');
    switchLang(lang);
    langMenu.classList.remove('open');
  });
});

document.addEventListener('click', () => {
  langMenu.classList.remove('open');
});

// ── Theme toggle ─────────────────────────────────────────────────────
const themeBtn = document.getElementById('theme-btn');
if (themeBtn) {
  // Load saved theme from localStorage
  const savedTheme = localStorage.getItem('theme') || 'dark';
  if (savedTheme === 'light') {
    document.body.classList.add('light-theme');
    themeBtn.textContent = '☽';
  }

  themeBtn.addEventListener('click', () => {
    const isLight = document.body.classList.toggle('light-theme');
    themeBtn.textContent = isLight ? '☽' : '☀';
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
  });
}



// ── Dropdown Menus ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  // Init mode tabs (inside same DOMContentLoaded as loadDramaProjects)
  document.querySelectorAll('.mode-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      if (tab.classList.contains('disabled')) return;
      document.querySelectorAll('.mode-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('.mode-content').forEach(content => {
        content.classList.remove('active');
      });
      const mode = tab.getAttribute('data-mode');
      const activeContent = document.getElementById('mode-' + mode);
      if (activeContent) activeContent.classList.add('active');
      // Show/hide task results area
      var resultsArea = document.getElementById('task-results');
      if (resultsArea) {
        resultsArea.style.display = (mode === 'drama') ? 'none' : '';
      }
      if (mode === 'drama') {
        loadDramaProjects();
        updateDramaCostDisplay();
      }
      if (mode === 'video') {
        updateVideoCostDisplay();
      }
      if (mode === 'image') {
        updateImageCostDisplay();
      }
    });
  });

  // Load drama projects and handle URL params on first render
  setTimeout(function() { loadDramaProjects(); updateDramaCostDisplay(); }, 100);

  // Handle ?tab=drama → switch to drama tab
  if (new URLSearchParams(window.location.search).get('tab') === 'drama') {
    var dramaTab = document.querySelector('.mode-tab[data-mode="drama"]');
    if (dramaTab) dramaTab.click();
  }

  // Handle ?drama=ID → navigate to drama tab and open project
  var dramaParam = new URLSearchParams(window.location.search).get('drama');
  var episodeParam = new URLSearchParams(window.location.search).get('episode');
  if (dramaParam) {
    var dramaTab = document.querySelector('.mode-tab[data-mode="drama"]');
    if (dramaTab) {
      dramaTab.click();
      var checkLoaded2 = setInterval(function() {
        var grid = document.getElementById('dramaProjectGrid');
        if (grid && grid.querySelector('.drama-project-card')) {
          clearInterval(checkLoaded2);
          openDramaDetail(parseInt(dramaParam));
          if (episodeParam) {
            setTimeout(function() { showDramaScene(parseInt(episodeParam)); }, 500);
          }
        }
      }, 300);
      setTimeout(function() { clearInterval(checkLoaded2); }, 10000);
    }
  }

  // Close dropdowns when clicking outside
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.ctrl-item')) {
      document.querySelectorAll('.dropdown-menu').forEach(function(menu) {
        menu.classList.remove('active');
      });
    }
  });

  // Setup all dropdown buttons
  document.querySelectorAll('.ctrl-dropdown').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      
      // Get the associated menu
      var menuId = btn.id.replace('Dropdown', 'Menu');
      var menu = document.getElementById(menuId);
      
      // Close other menus
      document.querySelectorAll('.dropdown-menu').forEach(function(m) {
        if (m.id !== menuId) {
          m.classList.remove('active');
        }
      });
      
      // Toggle current menu
      if (menu) {
        menu.classList.toggle('active');
      }
    });
  });

  // Setup all dropdown items
  document.querySelectorAll('.dropdown-item').forEach(function(item) {
    item.addEventListener('click', function(e) {
      e.stopPropagation();
      
      // Find parent menu
      var menu = item.closest('.dropdown-menu');
      if (menu) {
        menu.classList.remove('active');
        
        // Update dropdown button text
        var dropdownId = menu.id.replace('Menu', 'Dropdown');
        var dropdownBtn = document.getElementById(dropdownId);
        if (dropdownBtn) {
          var itemIcon = item.querySelector('.dropdown-icon, .ratio-icon, .ratio-box');
          if (itemIcon) {
            var iconAttr = '';
            if (itemIcon.classList.contains('ratio-icon')) {
              iconAttr = 'dropdown-icon ratio-icon';
            } else if (itemIcon.classList.contains('ratio-box')) {
              iconAttr = 'dropdown-icon ratio-box';
              var ratioVal = itemIcon.getAttribute('data-ratio');
              if (ratioVal) iconAttr += '" data-ratio="' + ratioVal;
            } else {
              iconAttr = 'dropdown-icon';
            }
            dropdownBtn.innerHTML = '<span class="' + iconAttr + '">' + itemIcon.textContent + '</span> ' + item.textContent.trim().replace(itemIcon.textContent, '').trim();
          } else {
            var icon = dropdownBtn.querySelector('.dropdown-icon');
            if (icon) {
              dropdownBtn.innerHTML = '<span class="dropdown-icon">' + icon.textContent + '</span> ' + item.textContent.trim();
            }
          }
        }
        
        // Update cost display based on control type
        if (dropdownId && dropdownId.includes('-drama')) {
          updateDramaCostDisplay();
        } else if (dropdownId && dropdownId.includes('-video')) {
          updateVideoCostDisplay();
        } else if (dropdownId && dropdownId.includes('-image')) {
          updateImageCostDisplay();
        }
      }
    });
  });

  // Setup duration presets
  document.querySelectorAll('.preset-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      
      var value = btn.textContent.trim();
      var menu = btn.closest('.dropdown-menu');
      if (menu) {
        menu.classList.remove('active');
        
        // Update dropdown button
        var dropdownId = menu.id.replace('Menu', 'Dropdown');
        var dropdownBtn = document.getElementById(dropdownId);
        if (dropdownBtn) {
          dropdownBtn.innerHTML = '<span class="dropdown-icon">◎</span> ' + value;
        }
        
        // Update slider
        var slider = menu.querySelector('input[type="range"]');
        var sliderValue = menu.querySelector('.slider-value');
        if (slider && sliderValue) {
          slider.value = value.replace('s', '');
          sliderValue.textContent = value;
        }
        
        // Update active state
        menu.querySelectorAll('.preset-btn').forEach(function(b) {
          b.classList.remove('active');
        });
        btn.classList.add('active');
        
        // Update cost display
        if (dropdownId) {
          if (dropdownId.includes('-video')) {
            updateVideoCostDisplay();
          } else if (dropdownId.includes('-drama')) {
            updateDramaCostDisplay();
          }
        }
      }
    });
  });

  // Setup duration sliders
  document.querySelectorAll('input[type="range"]').forEach(function(slider) {
    slider.addEventListener('input', function() {
      var value = slider.value;
      var menu = slider.closest('.dropdown-menu');
      if (menu) {
        var sliderValue = menu.querySelector('.slider-value');
        if (sliderValue) {
          sliderValue.textContent = value + 's';
        }
        // Update dropdown button
        var dropdownId = menu.id.replace('Menu', 'Dropdown');
        var dropdownBtn = document.getElementById(dropdownId);
        if (dropdownBtn) {
          dropdownBtn.innerHTML = '<span class="dropdown-icon">◎</span> ' + value + 's';
        }
        // Update cost display
        if (dropdownId && dropdownId.includes('-drama')) {
          updateDramaCostDisplay();
        } else if (dropdownId && dropdownId.includes('-video')) {
          updateVideoCostDisplay();
        }
        
        // Remove active state from presets
        menu.querySelectorAll('.preset-btn').forEach(function(b) {
          b.classList.remove('active');
        });
      }
    });
  });

  // Setup auto/custom toggle
  document.querySelectorAll('.auto-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      btn.classList.add('active');
      var sibling = btn.parentElement.querySelector('.custom-btn');
      if (sibling) sibling.classList.remove('active');
      // Update cost for drama
      if (btn.closest('#durMenu-drama')) updateDramaCostDisplay();
    });
  });

  document.querySelectorAll('.custom-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      btn.classList.add('active');
      var sibling = btn.parentElement.querySelector('.auto-btn');
      if (sibling) sibling.classList.remove('active');
      // Update cost for drama
      if (btn.closest('#durMenu-drama')) updateDramaCostDisplay();
    });
  });

  // ── Drama mode type buttons ──

  document.querySelectorAll('#mode-drama .type-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      var parent = btn.parentElement;
      parent.querySelectorAll('.type-btn').forEach(function(b) {
        b.classList.remove('active');
        b.style.background = 'transparent';
        b.style.border = '1px solid var(--border)';
        b.style.color = 'var(--t2)';
      });
      btn.classList.add('active');
      btn.style.background = 'var(--primary)';
      btn.style.border = '1px solid var(--primary)';
      btn.style.color = '#fff';

      var epCount = document.getElementById('dramaEpisodeCount');
      if (epCount) {
        var isSingle = btn.getAttribute('data-i18n') === 'gen.single_episode';
        _dramaIsSingleEpisode = isSingle;
        epCount.style.display = isSingle ? 'none' : 'inline-block';
        if (isSingle) epCount.value = '1';
      }
      updateDramaCostDisplay();
    });
  });

  // ── Episode count change → update cost ──
  var epCountEl = document.getElementById('dramaEpisodeCount');
  if (epCountEl) epCountEl.addEventListener('change', function() {
    updateDramaCostDisplay();
  });

  // ── Drama API helper ──
  function dramaApi(path, opts) {
    var token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return fetch('/api/drama' + path, { ...opts, headers: { ...headers, ...((opts && opts.headers) || {}) } })
      .then(function(r) { if (!r.ok) return r.text().then(function(t) { throw new Error(t); }); return r.json(); });
  }

  // ── Drama status map ──
  var _dramaStatusText = {
    draft: t('drama.status_draft') || 'Draft',
    generating: t('drama.status_generating') || 'Generating',
    completed: t('drama.status_completed') || 'Completed',
    failed: t('drama.status_failed') || 'Failed'
  };

  // ── Load drama projects ──
  function loadDramaProjects() {
    var grid = document.getElementById('dramaProjectGrid');
    grid.innerHTML = '<div style="text-align:center;padding:30px;color:var(--t3);font-size:13px;">' + t('js.loading') + '</div>';
    dramaApi('/projects').then(function(data) {
      var projects = data.projects || [];
      if (projects.length === 0) {
        grid.innerHTML = '<div style="text-align:center;padding:30px;color:var(--t3);font-size:13px;">' + t('drama.no_projects') + '</div>';
        return;
      }
      grid.innerHTML = projects.map(function(p) {
        var eps = p.episodes || [];
        var totalEpisodes = p.total_episodes || 0;
        var doneEps = eps.filter(function(e) { return e.status === 'completed' || e.merged_video_url; }).length;
        var renderedEps = eps.filter(function(e) { return e.status === 'completed' || e.status === 'generating'; }).length;
        var hasScript = eps.length > 0;
        var hasScenes = eps.some(function(e) { return (e.scene_count || 0) > 0; });
        var progressText = '';
        if (hasScript && hasScenes && renderedEps > 0) {
          progressText = '🎬 已渲染 ' + renderedEps + '/' + totalEpisodes + ' 集';
        } else if (hasScript && hasScenes) {
          progressText = '🎯 已拆解 ' + totalEpisodes + ' 集，待渲染';
        } else if (hasScript) {
          progressText = '📝 剧本已生成，待拆解';
        } else {
          progressText = '📋 创建项目，待生成剧本';
        }
        return '<div class="drama-project-card" data-id="' + p.id + '" style="background:var(--bg3);border-radius:10px;padding:14px;cursor:pointer;border:1px solid transparent;transition:all 0.2s;">' +
          '<div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:6px;">' +
          '<span style="font-size:11px;padding:1px 8px;border-radius:8px;background:#FF4757;color:#fff;">' + (p.genre || t('drama.genre_urban')) + '</span>' +
          '<span style="font-size:11px;padding:1px 8px;border-radius:8px;background:rgba(255,255,255,0.08);color:var(--t2);">' + (_dramaStatusText[p.status] || p.status) + '</span>' +
          '</div>' +
          '<div style="font-size:14px;font-weight:500;margin-bottom:4px;">' + p.title + '</div>' +
          '<div style="font-size:12px;color:var(--t3);">' + doneEps + '/' + totalEpisodes + ' 集完成</div>' +
          '<div style="font-size:11px;color:var(--t3);margin-top:4px;">' + progressText + '</div>' +
          '</div>';
      }).join('');
      // Click to open detail
      grid.querySelectorAll('.drama-project-card').forEach(function(card) {
        card.addEventListener('click', function() { openDramaDetail(parseInt(card.dataset.id)); });
      });
    }).catch(function(e) {
      grid.innerHTML = '<div style="text-align:center;padding:30px;color:var(--t3);font-size:13px;">' + t('js.load_failed') + '</div>';
    });
  }

  // ── Open project detail ──
  function openDramaDetail(projectId) {
    document.getElementById('dramaProjectList').style.display = 'none';
    document.getElementById('dramaDetailView').style.display = 'block';
    document.getElementById('dramaScenePanel').style.display = 'none';
    document.getElementById('dramaExportPanel').style.display = 'none';
    document.getElementById('dramaDetailView').dataset.projectId = projectId;
    loadDramaDetail(projectId);
  }

  function loadDramaDetail(projectId) {
    var titleEl = document.getElementById('dramaDetailTitle');
    var statusEl = document.getElementById('dramaDetailStatus');
    var listEl = document.getElementById('dramaEpisodeList');
    listEl.innerHTML = '<div style="text-align:center;padding:30px;color:var(--t3);font-size:13px;">' + t('js.loading') + '</div>';

    dramaApi('/projects/' + projectId).then(function(project) {
      titleEl.textContent = project.title + (project.genre ? ' (' + project.genre + ')' : '');
      statusEl.textContent = _dramaStatusText[project.status] || project.status;
      statusEl.style.background = project.status === 'draft' ? 'rgba(255,255,255,0.08)' : project.status === 'generating' ? 'rgba(34,197,94,0.15)' : project.status === 'completed' ? 'rgba(255,71,87,0.15)' : 'rgba(239,68,68,0.15)';
      statusEl.style.color = project.status === 'draft' ? 'var(--t2)' : project.status === 'generating' ? '#22c55e' : project.status === 'completed' ? '#FF4757' : '#ef4444';

      // Render pipeline
      renderDramaPipeline(project);

      var eps = project.episodes || [];
      if (eps.length === 0) {
        listEl.innerHTML = '<div style="text-align:center;padding:20px;color:var(--t3);font-size:13px;">' + t('drama.no_episodes') + '</div>';
        return;
      }
      listEl.innerHTML = eps.map(function(ep) {
        var icon = ep.status === 'draft' ? '📝' : ep.status === 'generating' ? '⏳' : ep.status === 'completed' ? '✅' : '❌';
        var hasScenes = (ep.scene_count || 0) > 0;
        var scenesRendered = ep.scenes_rendered || 0;
        var allRendered = hasScenes && scenesRendered >= ep.scene_count;
        var someRendered = scenesRendered > 0 && scenesRendered < ep.scene_count;
        var isFailed = ep.status === 'failed';
        var isDraft = ep.status === 'draft';
        var statusLabel = _dramaStatusText[ep.status] || ep.status;
        return '<div style="background:var(--bg2);border-radius:8px;padding:12px;margin-bottom:6px;border:1px solid transparent;">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">' +
          '<div class="drama-episode-card" data-ep="' + ep.id + '" style="cursor:pointer;flex:1;">' +
          '<div style="font-size:12px;color:#FF4757;font-weight:600;">' + icon + ' ' + t('drama.episode_title', { n: ep.episode_number }) + '</div>' +
          '<div style="font-size:14px;margin:4px 0;">' + (ep.title || '') + '</div>' +
          (ep.hook ? '<div style="font-size:12px;color:var(--t3);font-style:italic;">' + t('drama.hook_label') + ep.hook.substring(0, 50) + (ep.hook.length > 50 ? '...' : '') + '</div>' : '') +
          '<div style="font-size:11px;color:var(--t3);margin-top:4px;">' + (allRendered ? '✅ 全部渲染完成' : someRendered ? '🎬 渲染中 ' + scenesRendered + '/' + ep.scene_count : t('drama.scene_count', { n: ep.scene_count || 0 })) + '</div>' +
          '</div>' +
          '<span style="font-size:10px;padding:1px 6px;border-radius:4px;background:rgba(255,255,255,0.08);color:var(--t2);white-space:nowrap;">' + statusLabel + '</span>' +
          '</div>' +
          // 有分镜且未全部渲染完 → 显示渲染按钮
          (hasScenes && !allRendered ? '<div style="display:flex;gap:6px;margin-top:6px;padding-top:8px;border-top:1px solid var(--border);">' +
            '<button class="drama-render-ep-btn" data-ep="' + ep.id + '" style="flex:1;padding:5px;border:none;border-radius:6px;background:rgba(34,197,94,0.15);color:#22c55e;font-size:11px;cursor:pointer;">🎬 ' + (someRendered ? '继续渲染(' + (ep.scene_count - scenesRendered) + ')' : '渲染') + '</button>' +
            '</div>' : '') +
          // 有渲染完成的分镜 → 显示合成和预览
          ((allRendered || someRendered) ? '<div style="display:flex;gap:6px;margin-top:6px;padding-top:8px;border-top:1px solid var(--border);">' +
            '<button class="drama-merge-btn" data-ep="' + ep.id + '" style="flex:1;padding:5px;border:none;border-radius:6px;background:rgba(124,58,237,0.15);color:#7c3aed;font-size:11px;cursor:pointer;">🔗 合成</button>' +
            '<button class="drama-preview-btn" data-ep="' + ep.id + '" style="flex:1;padding:5px;border:none;border-radius:6px;background:rgba(34,197,94,0.15);color:#22c55e;font-size:11px;cursor:pointer;">▶ 预览</button>' +
            '</div>' : '') +
          (ep.merged_video_url ? '<div style="margin-top:4px;">' +
            '<a href="' + ep.merged_video_url + '" target="_blank" style="display:inline-block;padding:5px 10px;background:#7c3aed;color:#fff;border-radius:6px;font-size:11px;text-decoration:none;">⬇ 下载完整剧集</a>' +
            '</div>' : '') +
          (isFailed ? '<div style="display:flex;gap:6px;margin-top:6px;padding-top:8px;border-top:1px solid var(--border);">' +
            '<button class="drama-retry-btn" data-ep="' + ep.id + '" style="flex:1;padding:5px;border:none;border-radius:6px;background:rgba(255,71,87,0.15);color:#FF4757;font-size:11px;cursor:pointer;">🔄 ' + t('drama.retry') + '</button>' +
            '</div>' : '') +
          (isDraft && !hasScenes ? '<div style="display:flex;gap:6px;margin-top:6px;padding-top:8px;border-top:1px solid var(--border);">' +
            '<button class="drama-retry-btn" data-ep="' + ep.id + '" style="flex:1;padding:5px;border:none;border-radius:6px;background:#22c55e;color:#fff;font-size:11px;cursor:pointer;">▶ ' + t('drama.continue') + '</button>' +
            '</div>' : '') +
          '</div>';
      }).join('');
      listEl.querySelectorAll('.drama-episode-card').forEach(function(card) {
        card.addEventListener('click', function() { showDramaScene(parseInt(card.dataset.ep)); });
      });
      listEl.querySelectorAll('.drama-preview-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) { e.stopPropagation(); var epId = parseInt(btn.dataset.ep); loadDramaExport(epId); });
      });
      listEl.querySelectorAll('.drama-dl-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) { e.stopPropagation(); downloadDramaEpisodeFromHome(parseInt(btn.dataset.ep)); });
      });
      listEl.querySelectorAll('.drama-render-ep-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) { e.stopPropagation(); doRenderEpisode(parseInt(btn.dataset.ep)); });
      });
      listEl.querySelectorAll('.drama-merge-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) { e.stopPropagation(); mergeEpisode(parseInt(btn.dataset.ep)); });
      });
      listEl.querySelectorAll('.drama-retry-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          var epId = parseInt(btn.dataset.ep);
          var pid = document.getElementById('dramaDetailView').dataset.projectId;
          if (confirm(t('drama.confirm_retry') || '确定要重新生成该集吗？')) {
            doGenerateScriptForEpisode(parseInt(pid), epId);
          }
        });
      });
    }).catch(function(e) {
      listEl.innerHTML = '<div style="text-align:center;padding:20px;color:var(--t3);font-size:13px;">' + t('js.load_failed') + '</div>';
    });
  }

  // ── Show scene detail ──
  var _currentEpisodeId = null;
  function showDramaScene(episodeId) {
    _currentEpisodeId = episodeId;
    var panel = document.getElementById('dramaScenePanel');
    panel.style.display = 'block';
    panel.innerHTML = '<div style="text-align:center;padding:20px;color:var(--t3);font-size:13px;">' + t('js.loading') + '</div>';
    document.getElementById('dramaExportPanel').style.display = 'none';

    dramaApi('/episodes/' + episodeId).then(function(ep) {
      var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
        '<div><strong>' + t('drama.episode_title', { n: ep.episode_number }) + '</strong><span style="margin-left:8px;font-size:13px;color:var(--t3);">' + (ep.title || '') + '</span></div>' +
        '<div style="display:flex;gap:6px;">' +
        '<button class="drama-inline-btn" data-action="breakdown-ep" style="padding:5px 12px;border-radius:6px;border:none;cursor:pointer;font-size:11px;background:rgba(255,255,255,0.1);color:var(--t1);">' + t('drama.breakdown_ep') + '</button>' +
        '<button class="drama-inline-btn" data-action="render-ep" style="padding:5px 12px;border-radius:6px;border:none;cursor:pointer;font-size:11px;background:#22c55e;color:#fff;">' + t('drama.render_ep') + '</button>' +
        '<button class="drama-inline-btn" data-action="export-ep" style="padding:5px 12px;border-radius:6px;border:none;cursor:pointer;font-size:11px;background:rgba(255,255,255,0.1);color:var(--t1);">' + t('drama.export_ep') + '</button>' +
        '</div></div>';
      if (ep.hook) html += '<div style="font-size:12px;color:var(--t3);margin-bottom:6px;">' + t('drama.hook_label') + ep.hook + '</div>';
      if (ep.cliffhanger) html += '<div style="font-size:12px;color:var(--t3);margin-bottom:6px;">' + t('drama.cliffhanger_label') + ep.cliffhanger + '</div>';

      var scenes = ep.scenes || [];
      if (scenes.length > 0) {
        html += '<div style="font-size:12px;color:var(--t2);margin-bottom:6px;">' + t('drama.scenes_label', { n: scenes.length }) + '</div>';
        scenes.forEach(function(s) {
          var sIcon = s.status === 'draft' ? '📝' : s.status === 'generating' ? '⏳' : s.status === 'completed' ? '✅' : '❌';
          html += '<div style="background:rgba(255,255,255,0.03);border-radius:6px;padding:10px;margin-bottom:6px;">' +
            '<div style="display:flex;justify-content:space-between;font-size:12px;">' +
            '<span>' + sIcon + ' ' + t('drama.scene_label', { n: s.scene_number }) + (s.location ? ' — ' + s.location : '') + '</span>' +
            '<span style="color:var(--t3);">' + (s.duration || 5) + 's</span></div>' +
            (s.camera_instruction ? '<div style="font-size:11px;color:#FF6B81;margin:2px 0;">📷 ' + s.camera_instruction + '</div>' : '') +
            '<div style="font-size:11px;color:var(--t3);word-break:break-all;">' + (s.prompt_text ? s.prompt_text.substring(0, 100) + (s.prompt_text.length > 100 ? '...' : '') : '') + '</div>' +
            (s.selected_url ? '<div style="margin-top:4px;"><video src="' + s.selected_url + '" controls style="width:100%;max-height:150px;border-radius:4px;"></video></div>' : '') +
            (s.quality_score ? '<div style="font-size:11px;margin-top:2px;">⭐ ' + s.quality_score + '/10</div>' : '') +
            '</div>';
        });
      }
      panel.innerHTML = html;

      // Inline action buttons
      panel.querySelectorAll('.drama-inline-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var action = btn.dataset.action;
          if (action === 'breakdown-ep') doBreakdown(episodeId);
          else if (action === 'render-ep') doRenderEpisode(episodeId);
          else if (action === 'export-ep') doExport(episodeId);
        });
      });
    }).catch(function(e) {
      panel.innerHTML = '<div style="color:#FF4757;font-size:13px;">' + t('js.load_failed') + ': ' + e.message + '</div>';
    });
  }

  // ── Dramaa actions ──
  function doGenerateScript() {
    var pid = document.getElementById('dramaDetailView').dataset.projectId;
    if (!pid) return;
    document.getElementById('dramaDetailActions').innerHTML = '<span style="font-size:13px;color:var(--t3);">' + t('drama.generating_script') + '</span>';
    dramaApi('/projects/' + pid + '/generate-script', { method: 'POST', body: '{}' }).then(function(r) {
      alert('✅ ' + r.message);
      loadDramaDetail(parseInt(pid));
    }).catch(function(e) { alert(t('drama.gen_failed') + e.message); loadDramaDetail(parseInt(pid)); });
  }

  function doGenerateScriptForEpisode(projectId, episodeId) {
    // Find episode number from the current loaded project
    dramaApi('/projects/' + projectId).then(function(project) {
      var eps = project.episodes || [];
      var ep = eps.find(function(e) { return e.id === episodeId; });
      var epNum = ep ? ep.episode_number : null;
      var body = epNum ? JSON.stringify({ episode_numbers: [epNum] }) : '{}';
      return dramaApi('/projects/' + projectId + '/generate-script', { method: 'POST', body: body });
    }).then(function(r) {
      alert('✅ ' + r.message);
      loadDramaDetail(projectId);
    }).catch(function(e) { alert(t('drama.gen_failed') + e.message); });
  }

  function doBreakdown(episodeId) {
    dramaApi('/episodes/' + episodeId + '/breakdown', { method: 'POST' }).then(function(r) {
      alert('✅ ' + r.message);
      showDramaScene(episodeId);
    }).catch(function(e) { alert(t('drama.breakdown_failed') + e.message); });
  }

  function doRenderEpisode(episodeId) {
    var params = getDramaRenderParams();
    params.episode_ids = [episodeId];
    dramaApi('/render', { method: 'POST', body: JSON.stringify(params) }).then(function(r) {
      alert('✅ ' + r.message);
    }).catch(function(e) { alert(t('drama.render_failed') + e.message); });
  }

  function doRenderAll() {
    var pid = document.getElementById('dramaDetailView').dataset.projectId;
    if (!pid) return;
    // Fetch project to get all episode IDs with scenes
    dramaApi('/projects/' + pid).then(function(project) {
      var epIds = (project.episodes || []).filter(function(ep) { return (ep.scene_count || 0) > 0; }).map(function(ep) { return ep.id; });
      if (epIds.length === 0) { alert('没有可渲染的剧集（请先拆解分镜）'); return; }
      var params = getDramaRenderParams();
      params.episode_ids = epIds;
      return dramaApi('/render', { method: 'POST', body: JSON.stringify(params) });
    }).then(function(r) {
      if (r) alert('✅ ' + r.message);
    }).catch(function(e) { alert(t('drama.render_failed') + e.message); });
  }

  function doSync() {
    dramaApi('/tasks/sync').then(function(r) {
      alert('✅ ' + t('drama.sync_complete') + r.synced + ' ' + t('drama.scenes_updated'));
      var pid = document.getElementById('dramaDetailView').dataset.projectId;
      if (pid) loadDramaDetail(parseInt(pid));
      if (_currentEpisodeId) showDramaScene(_currentEpisodeId);
    }).catch(function(e) { alert(t('drama.sync_failed') + e.message); });
  }

  function doExport(episodeId) {
    dramaApi('/episodes/' + episodeId + '/export').then(function(manifest) {
      var panel = document.getElementById('dramaExportPanel');
      panel.style.display = 'block';
      var clips = manifest.clips || [];
      var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
        '<div style="font-size:14px;font-weight:500;">' + t('drama.export_title', { title: manifest.title || '', duration: manifest.total_duration || 0, count: clips.length }) + '</div>' +
        (clips.length > 0 ? '<button onclick="downloadAllClips(' + episodeId + ')" style="padding:5px 12px;border:none;border-radius:6px;background:#7c3aed;color:#fff;font-size:11px;cursor:pointer;">⬇ ' + t('drama.download') + '</button>' : '') +
        '</div>';
      if (clips.length === 0) {
        html += '<div style="color:var(--t3);font-size:13px;">' + t('drama.no_clips') + '</div>';
      } else {
        clips.forEach(function(c, i) {
          html += '<div style="background:rgba(255,255,255,0.03);border-radius:6px;padding:8px;margin-bottom:4px;font-size:12px;">' +
            t('drama.clip_label', { n: i+1 }) + ' — ' + t('drama.scene_label', { n: c.scene_number }) + ' (' + (c.duration || 0) + 's)' +
            (c.camera ? '<br><span style="color:#FF6B81;">📷 ' + c.camera + '</span>' : '') +
            (c.video_url ? '<br><video src="' + c.video_url + '" controls style="width:100%;max-height:120px;border-radius:4px;margin-top:4px;"></video>' : '<br><span style="color:#FF4757;">' + t('drama.no_video') + '</span>') +
            '</div>';
        });
      }
      panel.innerHTML = html;
    }).catch(function(e) { alert(t('drama.export_failed') + e.message); });
  }

  // ── Download helpers for homepage ──
  function loadDramaExport(episodeId) { doExport(episodeId); }

  async function downloadDramaEpisodeFromHome(episodeId) {
    try {
      var data = await dramaApi('/episodes/' + episodeId + '/export');
      var clips = data.clips || [];
      if (clips.length === 0) { alert(t('drama.no_clips')); return; }
      var videoUrl = clips[0].video_url;
      if (!videoUrl) { alert(t('drama.no_video')); return; }
      var a = document.createElement('a');
      a.href = videoUrl;
      a.download = 'episode_' + (data.episode_number || episodeId) + '.mp4';
      a.target = '_blank';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
    } catch(e) { alert(t('drama.export_failed') + e.message); }
  }

  async function downloadAllClips(episodeId) {
    try {
      var data = await dramaApi('/episodes/' + episodeId + '/export');
      var clips = data.clips || [];
      if (clips.length === 0) { alert(t('drama.no_clips')); return; }
      var urls = {};
      clips.forEach(function(c) { if (c.video_url && !urls[c.video_url]) { urls[c.video_url] = true; window.open(c.video_url, '_blank'); } });
    } catch(e) { alert(t('drama.export_failed') + e.message); }
  }

  async function mergeEpisode(episodeId) {
    var btn = document.querySelector('.drama-merge-btn[data-ep="' + episodeId + '"]');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 合成中...'; }
    try {
      var res = await fetch('/api/drama/episodes/' + episodeId + '/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('sdToken') }
      });
      var data = await res.json();
      if (!data.success) {
        alert('合成失败: ' + (data.detail || data.message || ''));
        if (btn) { btn.disabled = false; btn.textContent = '🔗 合成'; }
        return;
      }
      var pid = document.getElementById('dramaDetailView').dataset.projectId;
      var pollCount = 0;
      if (btn) btn.textContent = '⏳ 合成中...' + data.clip_count + '片段';
      var checkMerged = setInterval(function() {
        pollCount++;
        dramaApi('/projects/' + pid).then(function(project) {
          var ep = (project.episodes || []).find(function(e) { return e.id === episodeId; });
          if (ep && ep.merged_video_url) {
            clearInterval(checkMerged);
            loadDramaDetail(parseInt(pid));
          } else if (pollCount > 120) {
            clearInterval(checkMerged);
            loadDramaDetail(parseInt(pid));
            if (btn) { btn.disabled = false; btn.textContent = '🔗 合成'; }
          }
        }).catch(function() {});
      }, 3000);
    } catch(e) { alert('合成失败: ' + e.message); if (btn) { btn.disabled = false; btn.textContent = '🔗 合成'; } }
  }

  // ── Detail action buttons ──
  // Pipeline buttons (new step-by-step UI)
  function renderDramaPipeline(project) {
    var pid = project.id;
    var eps = project.episodes || [];
    var hasScript = eps.length > 0;
    var hasScenes = eps.some(function(ep) { return (ep.scene_count || 0) > 0; });
    var hasRendered = eps.some(function(ep) { return ep.status === 'completed' || ep.status === 'generating'; });
    var allMerged = eps.length > 0 && eps.every(function(ep) { return !!ep.merged_video_url; });

    var steps = [
      { label: '① 生成剧本', key: 'script', done: hasScript, color: '#FF4757' },
      { label: '② 拆解分镜', key: 'breakdown', done: hasScenes, color: '#f59e0b' },
      { label: '③ 渲染视频', key: 'render', done: hasRendered, color: '#22c55e' },
      { label: '④ 合成下载', key: 'merge', done: allMerged, color: '#7c3aed' },
    ];

    var activeIdx = steps.findIndex(function(s) { return !s.done; });
    if (activeIdx < 0) activeIdx = steps.length;

    var html = '';
    steps.forEach(function(s, i) {
      var state = i < activeIdx ? 'done' : i === activeIdx ? 'current' : 'future';
      var bg = state === 'done' ? s.color : state === 'current' ? s.color : 'rgba(255,255,255,0.06)';
      var textColor = state === 'future' ? 'var(--t3)' : '#fff';
      var icon = state === 'done' ? '✅' : state === 'current' ? '▶' : '○';
      html += '<button class="drama-step-btn" data-step="' + s.key + '" style="' +
        'flex:1;min-width:100px;padding:10px 8px;border:none;border-radius:8px;' +
        'background:' + bg + ';color:' + textColor + ';font-size:12px;font-weight:500;' +
        'cursor:' + (i === activeIdx ? 'pointer' : 'default') + ';opacity:' + (state === 'future' ? '0.5' : '1') + ';' +
        'transition:all 0.2s;text-align:center;' +
        '">' + icon + ' ' + s.label + '</button>';
    });
    document.getElementById('dramaPipeline').innerHTML = html;

    // Click handler for current step
    document.querySelectorAll('.drama-step-btn[data-step]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var step = btn.dataset.step;
        if (step === 'script') {
          doGenerateScriptAuto(pid);
        } else if (step === 'breakdown') {
          doBreakdownAll(pid, eps);
        } else if (step === 'render') {
          doRenderAllAuto(pid, eps);
        } else if (step === 'merge') {
          doMergeAll(pid, eps);
        }
      });
    });
  }

  function doGenerateScriptAuto(pid) {
    var pipeline = document.getElementById('dramaPipeline');
    pipeline.querySelector('[data-step="script"]').textContent = '⏳ 生成中...';
    dramaApi('/projects/' + pid + '/generate-script', { method: 'POST', body: '{}' }).then(function(r) {
      alert('✅ ' + r.message);
      loadDramaDetail(parseInt(pid));
    }).catch(function(e) { alert(t('drama.gen_failed') + e.message); loadDramaDetail(parseInt(pid)); });
  }

  function doBreakdownAll(pid, eps) {
    var epIds = eps.map(function(ep) { return ep.id; });
    var pipeline = document.getElementById('dramaPipeline');
    pipeline.querySelector('[data-step="breakdown"]').textContent = '⏳ 拆解中...';
    var promises = epIds.map(function(epId) {
      return dramaApi('/episodes/' + epId + '/breakdown', { method: 'POST' }).catch(function() { return null; });
    });
    Promise.all(promises).then(function() {
      loadDramaDetail(parseInt(pid));
    });
  }

  function doRenderAllAuto(pid, eps) {
    var epIds = eps.filter(function(ep) { return (ep.scene_count || 0) > 0; }).map(function(ep) { return ep.id; });
    if (epIds.length === 0) { alert('请先拆解分镜'); return; }
    var pipeline = document.getElementById('dramaPipeline');
    pipeline.querySelector('[data-step="render"]').textContent = '⏳ 渲染中...';
    var params = getDramaRenderParams();
    params.episode_ids = epIds;
    dramaApi('/render', { method: 'POST', body: JSON.stringify(params) }).then(function(r) {
      alert('✅ ' + r.message + '\n渲染完成后将自动合成');
      // Poll for completion then auto-merge
      var checkCount = 0;
      var pollInterval = setInterval(function() {
        checkCount++;
        dramaApi('/projects/' + pid).then(function(project) {
          var eps = project.episodes || [];
          var allDone = eps.length > 0 && eps.every(function(ep) {
            return ep.status === 'completed' || ep.status === 'generating';
          });
          if (allDone) {
            clearInterval(pollInterval);
            loadDramaDetail(parseInt(pid));
            // Auto merge
            doMergeAll(pid, project.episodes || []);
          } else {
            loadDramaDetail(parseInt(pid));
          }
        }).catch(function() {});
        if (checkCount > 120) clearInterval(pollInterval);
      }, 15000);
    }).catch(function(e) { alert(t('drama.render_failed') + e.message); });
  }

  function doMergeAll(pid, eps) {
    var todoEps = eps.filter(function(ep) {
      return (ep.scene_count || 0) > 0 && !ep.merged_video_url;
    });
    if (todoEps.length === 0) { alert('没有需要合成的剧集'); return; }
    var pipeline = document.getElementById('dramaPipeline');
    pipeline.querySelector('[data-step="merge"]').textContent = '⏳ 合成中...';
    function mergeNext(idx) {
      if (idx >= todoEps.length) { loadDramaDetail(parseInt(pid)); return; }
      var ep = todoEps[idx];
      fetch('/api/drama/episodes/' + ep.id + '/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('sdToken') }
      }).then(function(r) { return r.json(); }).then(function() {
        setTimeout(function() { mergeNext(idx + 1); }, 8000);
      }).catch(function() { mergeNext(idx + 1); });
    }
    mergeNext(0);
  }

  // ── Back button ──
  document.getElementById('dramaBackBtn').addEventListener('click', function() {
    document.getElementById('dramaDetailView').style.display = 'none';
    document.getElementById('dramaProjectList').style.display = 'block';
    loadDramaProjects();
  });

  // ── Create project ──
  document.getElementById('gen-btn-drama').addEventListener('click', function() {
    var token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
    if (!token) { openAuthModal(); return; }
    var prompt = document.getElementById('prompt-drama').value.trim();
    if (!prompt) { alert(t('drama.prompt_required')); return; }
    var genre = document.getElementById('dramaGenre').value;
    var episodes = _dramaIsSingleEpisode ? 1 : (parseInt(document.getElementById('dramaEpisodeCount').value) || 10);
    var title = prompt.substring(0, 20) + (prompt.length > 20 ? '...' : '');

    var btn = document.getElementById('gen-btn-drama');
    btn.disabled = true;
    btn.textContent = t('drama.creating');

    fetch('/api/drama/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey')) },
      body: JSON.stringify({ title: title, genre: genre, logline: prompt, total_episodes: episodes })
    }).then(function(r) { return r.json(); }).then(function(project) {
      // Generate script
      return fetch('/api/drama/projects/' + project.id + '/generate-script', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey')) },
        body: '{}'
      }).then(function() { return project; });
    }).then(function(project) {
      btn.disabled = false;
      btn.textContent = t('drama.start_create');
      document.getElementById('prompt-drama').value = '';
      var uploadBtn = document.querySelector('#mode-drama .drama-upload-btn');
      if (uploadBtn) uploadBtn.innerHTML = '<span>📄</span> ' + t('gen.upload_script');
      openDramaDetail(project.id);
    }).catch(function(e) {
      btn.disabled = false;
      btn.textContent = t('drama.start_create');
      alert(t('drama.create_failed') + e.message);
    });
  });

  // ── Upload script ──
  var dramaUploadBtn = document.querySelector('#mode-drama .drama-upload-btn');
  var dramaScriptInput = document.getElementById('drama-script-input');
  if (dramaUploadBtn) {
    dramaUploadBtn.addEventListener('click', function() {
      document.getElementById('drama-script-input').click();
    });
  }
  if (dramaScriptInput) {
    dramaScriptInput.addEventListener('change', function(e) {
      var file = e.target.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function(ev) {
        document.getElementById('prompt-drama').value = ev.target.result;
        var btn = document.querySelector('#mode-drama .drama-upload-btn');
        if (btn) btn.innerHTML = '<span>📄</span> ' + file.name;
      };
      reader.readAsText(file);
    });
  }
});

// ── Ctrl buttons (radio within group) ─────────────────────────────
document.querySelectorAll('.ctrl-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.ctrl;
    document.querySelectorAll(`.ctrl-btn[data-ctrl="${key}"]`).forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

// ── Toggles ──────────────────────────────────────────────────────
document.querySelectorAll('.toggle-item').forEach(item => {
  item.addEventListener('click', () => item.classList.toggle('on'));
});
const billingToggle = document.getElementById('billing-toggle');
if (billingToggle) {
  billingToggle.addEventListener('click', e => e.stopPropagation());
}

// ── Advanced Settings ──────────────────────────────────────────────
// Advanced button toggle
const advancedBtn = document.getElementById('advanced-btn-video');
const advancedPanel = document.getElementById('advanced-panel-video');
if (advancedBtn && advancedPanel) {
  advancedBtn.addEventListener('click', () => {
    advancedPanel.style.display = advancedPanel.style.display === 'none' || advancedPanel.style.display === '' ? 'block' : 'none';
    advancedBtn.classList.toggle('active');
  });
}

// Real people checkbox toggle (advanced panel)
const useRealPeopleCheckbox = document.getElementById('use-real-people-video');
const realPeopleOptions = document.getElementById('real-people-options-video');
if (useRealPeopleCheckbox && realPeopleOptions) {
  useRealPeopleCheckbox.addEventListener('change', () => {
    realPeopleOptions.style.display = useRealPeopleCheckbox.checked ? 'block' : 'none';
  });
}

// Real people quick options toggle (reference panel)
const useRealPeopleRefCheckbox = document.getElementById('use-real-people-ref-video');
const realPeopleRefSelect = document.getElementById('real-people-ref-select');
if (useRealPeopleRefCheckbox && realPeopleRefSelect) {
  useRealPeopleRefCheckbox.addEventListener('change', () => {
    realPeopleRefSelect.style.display = useRealPeopleRefCheckbox.checked ? 'block' : 'none';
    // Sync with advanced panel
    if (useRealPeopleCheckbox) {
      useRealPeopleCheckbox.checked = useRealPeopleRefCheckbox.checked;
      if (realPeopleOptions) {
        realPeopleOptions.style.display = useRealPeopleRefCheckbox.checked ? 'block' : 'none';
      }
    }
  });
}

// Advanced panel checkbox sync with reference panel
if (useRealPeopleCheckbox) {
  useRealPeopleCheckbox.addEventListener('change', () => {
    if (useRealPeopleRefCheckbox) {
      useRealPeopleRefCheckbox.checked = useRealPeopleCheckbox.checked;
      if (realPeopleRefSelect) {
        realPeopleRefSelect.style.display = useRealPeopleCheckbox.checked ? 'block' : 'none';
      }
    }
  });
}

// ── Asset Library Functions ────────────────────────────────────────
let currentAssetType = 'portrait';
let currentAssetInputId = '';
let selectedAsset = null;

// Asset upload handlers
const assetUploadButtons = {
  'avatar': { btn: 'avatar-upload-btn-video', file: 'avatar-upload-video', input: 'avatar-id-video', preview: 'avatar-preview-video' },
  'portrait': { btn: 'portrait-upload-btn-video', file: 'portrait-upload-video', input: 'real-human-portrait-id-video', preview: 'portrait-preview-video' },
  'background': { btn: 'background-upload-btn-video', file: 'background-upload-video', input: 'background-id-video', preview: 'background-preview-video' }
};

Object.entries(assetUploadButtons).forEach(([type, elements]) => {
  const btn = document.getElementById(elements.btn);
  const fileInput = document.getElementById(elements.file);
  const input = document.getElementById(elements.input);
  const preview = document.getElementById(elements.preview);
  
  if (btn && fileInput) {
    btn.addEventListener('click', () => fileInput.click());
    
    fileInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      
      btn.disabled = true;
      btn.textContent = '📤 ' + t('js.uploading');
      
      try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('asset_type', type);
        
        const response = await fetch('/api/assets/upload', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + apiKey() },
          body: formData
        });
        
        const data = await response.json();
        if (data.success && data.data) {
          input.value = data.data.external_id || data.data.id;
          if (preview) {
            preview.innerHTML = `<img src="${data.data.asset_url}" style="max-width: 100px; max-height: 100px;">`;
          }
        } else {
          alert(t('js.upload_failed') + (data.message || ''));
        }
      } catch (err) {
        alert(t('js.upload_error') + err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = '📤';
        fileInput.value = '';
      }
    });
  }
});

// Asset library modal handlers
const assetLibraryModal = document.getElementById('asset-library-modal');
const assetLibraryClose = document.getElementById('asset-library-close');
const assetLibraryTabs = document.querySelectorAll('.asset-tab');
const assetGrid = document.getElementById('asset-grid');
const assetPrevBtn = document.getElementById('asset-prev');
const assetNextBtn = document.getElementById('asset-next');
const assetPageInfo = document.getElementById('asset-page-info');
const assetCancelBtn = document.getElementById('asset-cancel');
const assetConfirmBtn = document.getElementById('asset-confirm');

let currentAssetPage = 1;
let totalAssetPages = 1;

// Library buttons
const libraryButtons = [
  { btn: 'avatar-library-btn-video', input: 'avatar-id-video', preview: 'avatar-preview-video', type: 'avatar' },
  { btn: 'portrait-library-btn-video', input: 'real-human-portrait-id-video', preview: 'portrait-preview-video', type: 'portrait' },
  { btn: 'action-library-btn-video', input: 'action-id-video', preview: null, type: 'action' },
  { btn: 'background-library-btn-video', input: 'background-id-video', preview: 'background-preview-video', type: 'background' },
  { btn: 'voice-library-btn-video', input: 'voice-id-video', preview: null, type: 'voice' }
];

libraryButtons.forEach(({ btn, input, preview, type }) => {
  const button = document.getElementById(btn);
  if (button) {
    button.addEventListener('click', () => {
      currentAssetType = type;
      currentAssetInputId = input;
      selectedAsset = null;
      currentAssetPage = 1;
      loadAssetLibrary(type, 1);
      assetLibraryModal.style.display = 'flex';
    });
  }
});

assetLibraryTabs.forEach(tab => {
  tab.addEventListener('click', () => {
    assetLibraryTabs.forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentAssetType = tab.dataset.tab;
    currentAssetPage = 1;
    selectedAsset = null;
    loadAssetLibrary(currentAssetType, 1);
  });
});

async function loadAssetLibrary(type, page) {
  assetGrid.innerHTML = '<div class="loading">' + t('js.loading') + '</div>';
  
  try {
    const response = await fetch(`/api/assets/byteplus/${type}s?page=${page}&page_size=12`, {
      headers: { 'Authorization': 'Bearer ' + apiKey() }
    });
    
    const data = await response.json();
    if (data.success) {
      if (data.unavailable) {
        assetGrid.innerHTML = '<div class="empty" style="padding:24px;text-align:center;color:var(--t3);font-size:13px;">🔒 ' + t('js.asset_unavailable') + '</div>';
        assetPageInfo.textContent = '— / —';
        assetPrevBtn.disabled = true;
        assetNextBtn.disabled = true;
        return;
      }
      totalAssetPages = Math.ceil(data.total / 12) || 1;
      assetPageInfo.textContent = `${page} / ${totalAssetPages}`;
      assetPrevBtn.disabled = page <= 1;
      assetNextBtn.disabled = page >= totalAssetPages;

      renderAssetGrid(data.data);
    } else {
      assetGrid.innerHTML = '<div class="empty">' + t('js.no_data') + '</div>';
    }
  } catch (err) {
    assetGrid.innerHTML = '<div class="error">' + t('js.load_error') + '</div>';
  }
}

function renderAssetGrid(assets) {
  if (!assets || assets.length === 0) {
    assetGrid.innerHTML = '<div class="empty">' + t('js.no_data') + '</div>';
    return;
  }
  
  assetGrid.innerHTML = assets.map(asset => `
    <div class="asset-item ${selectedAsset?.id === asset.id ? 'selected' : ''}" data-asset='${JSON.stringify(asset)}'>
      <div class="asset-thumbnail">
        ${(asset.thumbnail_url || asset.url) ? `<img src="${asset.thumbnail_url || asset.url}" alt="${asset.name}" style="width:100%;height:100%;object-fit:cover;">` : '<div class="asset-icon">📦</div>'}
      </div>
      <div class="asset-name">${asset.name || asset.id}</div>
    </div>
  `).join('');
  
  // Add click handlers
  assetGrid.querySelectorAll('.asset-item').forEach(item => {
    item.addEventListener('click', () => {
      assetGrid.querySelectorAll('.asset-item').forEach(i => i.classList.remove('selected'));
      item.classList.add('selected');
      selectedAsset = JSON.parse(item.dataset.asset);
    });
  });
}

if (assetPrevBtn) assetPrevBtn.addEventListener('click', () => {
  if (currentAssetPage > 1) {
    currentAssetPage--;
    loadAssetLibrary(currentAssetType, currentAssetPage);
  }
});

if (assetNextBtn) assetNextBtn.addEventListener('click', () => {
  if (currentAssetPage < totalAssetPages) {
    currentAssetPage++;
    loadAssetLibrary(currentAssetType, currentAssetPage);
  }
});

function closeAssetModal() {
  assetLibraryModal.style.display = 'none';
  selectedAsset = null;
}

if (assetLibraryClose) assetLibraryClose.addEventListener('click', closeAssetModal);
if (assetCancelBtn) assetCancelBtn.addEventListener('click', closeAssetModal);

// 上传素材到火山引擎素材库
const assetUploadInput = document.getElementById('asset-upload-input');
const assetUploadBtn = document.getElementById('asset-upload-btn');
const assetUploadStatus = document.getElementById('asset-upload-status');

if (assetUploadBtn) assetUploadBtn.addEventListener('click', () => assetUploadInput && assetUploadInput.click());

if (assetUploadInput) assetUploadInput.addEventListener('change', async () => {
  const file = assetUploadInput.files[0];
  if (!file) return;
  assetUploadInput.value = '';

  // group_type 由当前 tab 决定
  assetUploadStatus.textContent = '上传中...';
  assetUploadBtn.disabled = true;

  try {
    const fd = new FormData();
    fd.append('file', file);

    const resp = await fetch('/api/files/upload', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + apiKey() },
      body: fd,
    });
    const data = await resp.json();
    if (data.success) {
      assetUploadStatus.textContent = '✓ 上传成功';
      setTimeout(() => { assetUploadStatus.textContent = ''; }, 2000);
      _loadRefLibrary('uploads');
    } else {
      assetUploadStatus.textContent = '✗ ' + (data.message || '上传失败');
    }
  } catch (e) {
    assetUploadStatus.textContent = '✗ 网络错误';
  } finally {
    assetUploadBtn.disabled = false;
  }
});

if (assetConfirmBtn) assetConfirmBtn.addEventListener('click', () => {
  if (selectedAsset && currentAssetInputId) {
    const input = document.getElementById(currentAssetInputId);
    if (input) {
      input.value = selectedAsset.id;
      
      // Update preview if available
      const previewId = libraryButtons.find(b => b.input === currentAssetInputId)?.preview;
      if (previewId) {
        const preview = document.getElementById(previewId);
        if (preview && (selectedAsset.thumbnail_url || selectedAsset.url)) {
          preview.innerHTML = `<img src="${selectedAsset.thumbnail_url || selectedAsset.url}" style="max-width: 100px; max-height: 100px;">`;
        }
      }
    }
    closeAssetModal();
  } else {
    alert(t('js.select_asset_first'));
  }
});

// ── FAQ ───────────────────────────────────────────────────────────
document.querySelectorAll('.faq-q').forEach(q => {
  q.addEventListener('click', () => q.parentElement.classList.toggle('open'));
});

// ── Auth System ──────────────────────────────────────────────────────
const signinBtn = document.getElementById('sign-in-btn');
const userBtn = document.getElementById('user-btn');
const userAvatar = document.getElementById('userAvatar');
const userName = document.getElementById('userName');
const userDropdown = document.getElementById('userDropdown');
const authModal = document.getElementById('authModal');

async function loadAuthConfig() {
  try {
    const res = await fetch('/api/auth/config');
    const cfg = await res.json();
    const googleBtn = document.getElementById('googleBtn');
    if (!cfg.allow_google_login && googleBtn) googleBtn.style.display = 'none';
    if (!cfg.allow_registration) {
      const registerTab = document.querySelector('[data-tab="register"]');
      if (registerTab) {
        registerTab.style.display = 'none';
      }
    }
  } catch (e) { console.error('Failed to load auth config'); }
}

function openAuthModal() { if (authModal) authModal.classList.add('open'); }

function handleGenError(detail) {
  if (detail && detail.startsWith('INSUFFICIENT_POINTS:')) {
    const parts = detail.split(':');
    showInsufficientPointsModal(parseInt(parts[1]) || 0, parseInt(parts[2]) || 0);
    return;
  }
  alert(detail || t('js.gen_failed'));
}

function showInsufficientPointsModal(required, balance) {
  const existing = document.getElementById('insufficient-points-modal');
  if (existing) existing.remove();
  const modal = document.createElement('div');
  modal.id = 'insufficient-points-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:99999;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:var(--bg2,#1a1a2e);border-radius:16px;padding:32px 28px;max-width:360px;width:90%;text-align:center;box-shadow:0 8px 40px rgba(0,0,0,.5);">
      <div style="font-size:48px;margin-bottom:12px;">💎</div>
      <h3 style="margin:0 0 8px;font-size:18px;color:var(--t1,#fff);">积分不足</h3>
      <p style="color:var(--t2,#aaa);font-size:14px;margin:0 0 20px;line-height:1.6;">
        本次生成需要 <strong style="color:#a78bfa;">${required} 积分</strong>，<br>
        当前余额 <strong style="color:#f87171;">${balance} 积分</strong>。
      </p>
      <div style="display:flex;gap:10px;justify-content:center;">
        <button onclick="document.getElementById('insufficient-points-modal').remove()" style="padding:9px 20px;border-radius:8px;border:1px solid var(--border,#444);background:none;color:var(--t2,#aaa);cursor:pointer;font-size:14px;">取消</button>
        <button onclick="document.getElementById('insufficient-points-modal').remove();_scrollToPricing()" style="padding:9px 20px;border-radius:8px;border:none;background:linear-gradient(135deg,#7c3aed,#4f46e5);color:#fff;cursor:pointer;font-size:14px;font-weight:600;">去充值</button>
      </div>
    </div>
  `;
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  document.body.appendChild(modal);
}

window._scrollToPricing = function() {
  const el = document.querySelector('#pricing, [data-section="pricing"]');
  if (el) el.scrollIntoView({ behavior: 'smooth' });
};
function closeAuthModal() { if (authModal) authModal.classList.remove('open'); }

function switchAuthTab(tab) {
  document.querySelectorAll('.auth-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.auth-form').forEach(f => f.classList.toggle('active', f.id === tab + 'Form'));
}

async function doEmailLogin() {
  const loginEmail = document.getElementById('loginEmail');
  const loginPassword = document.getElementById('loginPassword');
  const errorEl = document.getElementById('loginError');
  const btn = document.getElementById('loginBtn');
  
  if (!loginEmail || !loginPassword || !errorEl || !btn) return;
  
  const email = loginEmail.value.trim();
  const password = loginPassword.value;

  if (!email || !password) { errorEl.textContent = t('auth.fillAll'); errorEl.style.display = 'block'; return; }

  btn.disabled = true; btn.textContent = t('auth.processing'); errorEl.style.display = 'none';

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || t('auth.loginFailed'));

    handleAuthSuccess(data);
  } catch (e) {
    errorEl.textContent = e.message;
    errorEl.style.display = 'block';
    btn.disabled = false; btn.textContent = t('auth.loginBtn');
  }
}

async function doRegister() {
  const regEmail = document.getElementById('regEmail');
  const regName = document.getElementById('regName');
  const regPassword = document.getElementById('regPassword');
  const regConfirmPassword = document.getElementById('regConfirmPassword');
  const agreeTerms = document.getElementById('agreeTerms');
  const errorEl = document.getElementById('registerError');
  const btn = document.getElementById('registerBtn');
  
  if (!regEmail || !regPassword || !regConfirmPassword || !agreeTerms || !errorEl || !btn) return;
  
  const email = regEmail.value.trim();
  const displayName = regName ? regName.value.trim() : '';
  const password = regPassword.value;
  const confirmPassword = regConfirmPassword.value;
  const agreeTermsChecked = agreeTerms.checked;

  if (!email || !password) { errorEl.textContent = t('auth.fillAll'); errorEl.style.display = 'block'; return; }
  if (password !== confirmPassword) { errorEl.textContent = t('auth.passwordMismatch'); errorEl.style.display = 'block'; return; }
  if (password.length < 6) { errorEl.textContent = t('auth.passwordTooShort'); errorEl.style.display = 'block'; return; }
  if (!agreeTermsChecked) { errorEl.textContent = t('auth.agreeRequired'); errorEl.style.display = 'block'; return; }

  btn.disabled = true; btn.textContent = t('auth.processing'); errorEl.style.display = 'none';

  try {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, display_name: displayName || email.split('@')[0] }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || t('auth.registerFailed'));

    handleAuthSuccess(data);
  } catch (e) {
    errorEl.textContent = e.message;
    errorEl.style.display = 'block';
    btn.disabled = false; btn.textContent = t('auth.registerBtn');
  }
}

function doGoogleLogin() {
  const clientId = 'YOUR_GOOGLE_CLIENT_ID';
  const redirectUri = encodeURIComponent(window.location.origin + '/auth/callback');
  const scope = encodeURIComponent('email profile');
  window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${clientId}&redirect_uri=${redirectUri}&response_type=code&scope=${scope}`;
}

function handleAuthSuccess(data) {
  authToken = data.access_token;
  currentUser = data.user;
  localStorage.setItem('sdToken', authToken);
  localStorage.setItem('sdUser', JSON.stringify(currentUser));
  closeAuthModal();
  updateUserUI();
}

function updateUserUI() {
  if (currentUser) {
    if (signinBtn) signinBtn.style.display = 'none';
    if (signupBtn) signupBtn.style.display = 'none';
    if (userBtn) userBtn.style.display = 'flex';
    if (userName) userName.textContent = currentUser.display_name || currentUser.email.split('@')[0];
    if (userAvatar) userAvatar.textContent = (currentUser.display_name || currentUser.email)[0].toUpperCase();
    const dropdownEmail = document.getElementById('dropdownEmail');
    if (dropdownEmail) dropdownEmail.textContent = currentUser.email;
    const dropdownPoints = document.getElementById('dropdownPoints');
    if (dropdownPoints) dropdownPoints.textContent = t('user.points') + ': ' + (currentUser.points_balance || 0);
  } else {
    if (signinBtn) signinBtn.style.display = 'block';
    if (signupBtn) signupBtn.style.display = 'block';
    if (userBtn) userBtn.style.display = 'none';
  }
}

function doLogout() {
  authToken = '';
  currentUser = null;
  localStorage.removeItem('sdToken');
  localStorage.removeItem('sdUser');
  localStorage.removeItem('sdApiKey');
  if (userDropdown) userDropdown.classList.remove('open');
  updateUserUI();
}

function showApiKeys() {
  if (userDropdown) userDropdown.classList.remove('open');
  alert(t('user.apiKeyHint'));
}

function showSubscription() {
  if (userDropdown) userDropdown.classList.remove('open');
  if (currentUser && currentUser.subscription) {
    alert(t('user.currentSub') + ': ' + currentUser.subscription.plan_name);
  } else {
    alert(t('user.noSub'));
  }
}

if (signinBtn) signinBtn.addEventListener('click', openAuthModal);
const signupBtn = document.getElementById('sign-up-btn');
signupBtn?.addEventListener('click', openAuthModal);
if (userBtn) userBtn.addEventListener('click', openProfile);
document.addEventListener('click', () => { if (userDropdown) userDropdown.classList.remove('open'); });

// Restore session on load
(async function initAuth() {
  await loadAuthConfig();
  if (authToken) {
    try {
      const res = await fetch('/api/auth/me', { headers: { 'Authorization': 'Bearer ' + authToken } });
      if (res.ok) {
        currentUser = await res.json();
        localStorage.setItem('sdUser', JSON.stringify(currentUser));
        updateUserUI();
      } else {
        doLogout();
      }
    } catch (e) { doLogout(); }
  }
})();

function apiKey() {
  return localStorage.getItem('sdApiKey') || localStorage.getItem('sdToken') || authToken;
}

// ── Mode tabs ──────────────────────────────────────────────────
let currentMode = 'video-agent';

document.querySelectorAll('.mode-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.mode-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentMode = tab.dataset.mode;
    updateGenUI();
  });
});

function updateGenUI() {
  const genCard = document.querySelector('.gen-card');
  const controls = document.querySelector('.gen-controls');
  const uploadRow = document.querySelector('.gen-upload-row');
  const toggleRow = document.querySelector('.toggle-row');
  const genBtn = document.getElementById('gen-btn');
  
  if (currentMode === 'ai-image') {
    if (controls) controls.style.display = 'none';
    if (uploadRow) uploadRow.style.display = 'none';
    if (toggleRow) toggleRow.style.display = 'none';
    if (genBtn) genBtn.textContent = '🎨 ' + t('js.generate_image');
    loadEndpoints('image');
  } else if (currentMode === 'video-agent' || currentMode === 'ai-video') {
    if (controls) controls.style.display = 'flex';
    if (uploadRow) uploadRow.style.display = 'flex';
    if (toggleRow) toggleRow.style.display = 'flex';
    if (genBtn) genBtn.textContent = t('js.generate');
    loadEndpoints('video');
  } else {
    if (controls) controls.style.display = 'flex';
    if (uploadRow) uploadRow.style.display = 'flex';
    if (toggleRow) toggleRow.style.display = 'flex';
    if (genBtn) genBtn.textContent = t('js.generate');
    loadEndpoints('video');
  }
}

// ── Upload zone ──────────────────────────────────────────────────
const fileInput = document.getElementById('file-input-video');
const uploadZone = document.getElementById('upload-zone-video');
const uploadCount = document.querySelector('.upload-count');

if (uploadZone && fileInput) {
  // handled by initUploadZone
}

if (fileInput) {
  fileInput.addEventListener('change', async e => {
  const files = Array.from(e.target.files);
  if (!files.length) return;
  if (uploadedFiles.length + files.length > 12) { alert(t('js.max_files')); return; }

  const uploadingText = t('js.uploading');
  uploadZone.innerHTML = `<span>📎</span> ${uploadingText}`;
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch('/api/files/upload', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + apiKey() },
        body: fd,
      });
      const data = await res.json();
      if (data.success) {
        uploadedFiles.push({ name: file.name, file_id: data.data.id, url: data.data.url, type: file.type.startsWith('video') ? 'video' : (file.type.startsWith('audio') ? 'audio' : 'image') });
      } else {
        alert(t('js.upload_failed') + (data.message || t('js.unknown_error')));
      }
    } catch (err) {
      alert(t('js.upload_error') + err.message);
    }
  }
  const n = uploadedFiles.length;
  uploadZone.innerHTML = `<span>📎</span> ${n}` + t('js.attached');
  updateUploadCountDisplay();
  fileInput.value = '';
  updatePromptTags();
});
}

function updatePromptTags() {
  const ta = document.getElementById('prompt-video');
  if (!ta) return;
  let tags = uploadedFiles.map((f, i) => f.type === 'video' ? `@video${i+1}` : (f.type === 'audio' ? `@audio${i+1}` : `@image${i+1}`)).join(' ');
  if (tags && !ta.value.includes('@')) ta.placeholder = `${t('gen.prompt_eg')} ${tags} ${t('gen.prompt_example')}`;
}

function showVideoResult(url) {
  if (!url) return;
  const existing = document.getElementById('result-area');
  if (existing) existing.remove();
  const div = document.createElement('div');
  div.id = 'result-area';
  div.style.cssText = 'margin-top:16px;border-radius:12px;overflow:hidden;border:1px solid rgba(91,110,245,.4);';
  div.innerHTML = `<video src="${url}" controls autoplay style="width:100%;display:block;border-radius:12px;"></video>
    <div style="padding:8px 14px;background:rgba(251,191,36,.08);border-top:1px solid rgba(251,191,36,.2);display:flex;align-items:center;gap:6px;">
      <span style="font-size:13px;">⚠️</span>
      <span style="font-size:12px;color:#fbbf24;">视频链接仅保留 12 小时，请尽快下载保存！</span>
    </div>
    <div style="padding:10px 14px;display:flex;gap:10px;">
      <a href="${url}" download style="font-size:13px;color:#a5b4fc;text-decoration:none;">${t('js.download')}</a>
    </div>`;
  const container = document.querySelector('.gen-input-area');
  if (container) container.appendChild(div);
}

function showImageResult(url) {
  if (!url) return;
  const existing = document.getElementById('result-area');
  if (existing) existing.remove();
  const div = document.createElement('div');
  div.id = 'result-area';
  div.style.cssText = 'margin-top:16px;border-radius:12px;overflow:hidden;border:1px solid rgba(91,110,245,.4);';
  div.innerHTML = `<img src="${url}" style="width:100%;display:block;border-radius:12px;" alt="Generated image">
    <div style="padding:10px 14px;display:flex;gap:10px;">
      <a href="${url}" download style="font-size:13px;color:#a5b4fc;text-decoration:none;">${t('js.download')}</a>
    </div>`;
  const container = document.querySelector('.gen-input-area');
  if (container) container.appendChild(div);
}

async function loadEndpoints(endpointType = null) {
  try {
    let url = '/api/tasks/endpoints';
    if (endpointType) {
      url += `?type=${endpointType}`;
    }
    const res = await fetch(url);
    const data = await res.json();
    const select = document.getElementById('modelSelect');
    if (!select) return;
    select.innerHTML = '';
    
    if (data.endpoints && data.endpoints.length > 0) {
      data.endpoints.forEach(ep => {
        const option = document.createElement('option');
        option.value = ep.endpoint_id;
        option.textContent = `${ep.endpoint_name || ep.endpoint_id} (${ep.channel_name})`;
        if (ep.is_default) {
          option.selected = true;
        }
        select.appendChild(option);
      });
    } else {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = t('js.no_endpoints');
      select.appendChild(option);
    }
  } catch (err) {
    console.error('Failed to load endpoints:', err);
    const select = document.getElementById('modelSelect');
    select.innerHTML = `<option value="">${t('js.load_failed')}</option>`;
  }
}

// 初始加载视频类型接入点
loadEndpoints('video');

async function loadDramaEndpoints() {
  try {
    const res = await fetch('/api/tasks/endpoints?type=video');
    const data = await res.json();
    const select = document.getElementById('modelSelect-drama');
    if (!select || !data.endpoints || data.endpoints.length === 0) {
      updateDramaCostDisplay();
      return;
    }
    select.innerHTML = '';
    data.endpoints.forEach(ep => {
      const option = document.createElement('option');
      option.value = ep.endpoint_id;
      // Clean endpoint name for display
      const name = (ep.endpoint_name || ep.endpoint_id).replace(/_/g, ' ');
      // Add badge for default model
      const label = ep.is_default ? `${name} ⭐` : name;
      option.textContent = label;
      if (ep.is_default) option.selected = true;
      select.appendChild(option);
    });
    // Recalculate cost after populating
    updateDramaCostDisplay();
  } catch (err) {
    console.error('Failed to load drama endpoints:', err);
    updateDramaCostDisplay();
  }
}

// 用户中心相关函数
function openProfile() {
  window.location.href = '/pages/profile.html';
}

// ── Video & Image Generation API Integration ───────────────────────────
// Global variables
let currentTasks = [];
let pollingIntervals = {};
let taskStartTimes = {}; // taskId -> timestamp ms, for fake progress animation

// Get current mode
function getCurrentMode() {
  const activeTab = document.querySelector('.mode-tab.active:not(.disabled)');
  return activeTab ? activeTab.dataset.mode : 'video-agent';
}

// Get selected parameters for video generation
function getVideoParams(prefix = '') {
  const model = document.getElementById('modelSelect' + prefix).value || '';
  const ratioBtn = document.getElementById('ratioDropdown' + prefix);
  const ratio = ratioBtn ? ratioBtn.textContent.trim().replace(/[▢◎▭▯◻▮▰⬌⬍]/g, '').trim() : '16:9';
  const resBtn = document.getElementById('resDropdown' + prefix);
  const resolution = resBtn ? resBtn.textContent.trim().replace(/[▢◎▭▯◻▮▰⬌⬍]/g, '').trim() : '480p';
  const durBtn = document.getElementById('durDropdown' + prefix);
  const duration = durBtn ? durBtn.textContent.trim().replace(/[▢◎▭▯◻▮▰⬌⬍]/g, '').trim() : '60s';
  
  // 真人素材参数 - 参考 BytePlus 文档：https://docs.byteplus.com/en/docs/ModelArk/2333589
  const avatarId = document.getElementById('avatar-id' + prefix)?.value || '';
  const portraitId = document.getElementById('real-human-portrait-id' + prefix)?.value || '';
  const actionId = document.getElementById('action-id' + prefix)?.value || '';
  const backgroundId = document.getElementById('background-id' + prefix)?.value || '';
  const voiceId = document.getElementById('voice-id' + prefix)?.value || '';
  
  // 获取复选框状态（优先使用复选框明确设置）
  const useRealPeopleCheckbox = document.getElementById('use-real-people-video');
  const useRealPeopleRefCheckbox = document.getElementById('use-real-people-ref-video');
  
  // 获取参考图片数量
  const refImages = referenceFiles['video'] || [];
  const hasRefImages = refImages.some(f => f.type === 'image');
  
  // 判断是否使用真人素材：只根据复选框状态决定
  const useRealPeople = useRealPeopleCheckbox?.checked || false;
  
  return { 
    model, 
    ratio, 
    resolution, 
    duration: parseInt(duration) || 60,
    use_real_people: useRealPeople,
    avatar_id: avatarId || undefined,
    real_human_portrait_id: portraitId || undefined,
    action_id: actionId || undefined,
    background_id: backgroundId || undefined,
    voice_id: voiceId || undefined
  };
}

async function _getPointsPerSec() {
  try {
    const res = await fetch('/api/public/points-per-sec');
    _pointsPerSecCache = await res.json();
    return _pointsPerSecCache;
  } catch (e) {
    console.error('Failed to load points per sec config:', e);
    return {};
  }
}

// 刷新积分配置缓存（用于管理员修改配置后）
async function refreshPointsConfig() {
  const results = await Promise.allSettled([_getPointsPerSec(), _getImageCosts()]);
  return results;
}

async function _getImageCosts() {
  try {
    const res = await fetch('/api/public/image-costs');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    _imageCostsCache = await res.json();
    console.log('[image-costs] Loaded from API:', JSON.stringify(_imageCostsCache));
    return _imageCostsCache;
  } catch (e) {
    console.error('Failed to load image costs:', e);
    _imageCostsCache = {};  // clear on error so fallback is consistent
    return {};
  }
}

// 计算视频生成的积分消耗（使用后台配置）
function calculateVideoPointsCost(prefix = '') {
  const params = getVideoParams(prefix);
  const { resolution, duration } = params;
  const model = document.getElementById('modelSelect' + prefix)?.value || '';

  // 只使用后台配置，不使用硬编码默认值
  const config = _pointsPerSecCache || {};
  const table = config[model] || {};
  
  // 检查模型是否支持所选分辨率，如果不支持则回退
  let effectiveResolution = resolution;
  if (!table[resolution]) {
    // 模型不支持所选分辨率，按优先级回退
    if (table['720p']) effectiveResolution = '720p';
    else if (table['480p']) effectiveResolution = '480p';
    else if (table['1080p']) effectiveResolution = '1080p';
    else {
      // 如果该模型没有任何配置，尝试使用其他模型的配置
      for (const [, modelConfig] of Object.entries(config)) {
        if (modelConfig[resolution]) {
          return Math.max(0.1, Math.round(modelConfig[resolution] * duration * 10) / 10);
        } else if (modelConfig['720p']) {
          return Math.max(0.1, Math.round(modelConfig['720p'] * duration * 10) / 10);
        }
      }
      // 如果完全没有配置，返回0表示无法计算
      return 0;
    }
  }
  
  const perSec = table[effectiveResolution];
  return perSec ? Math.max(0.1, Math.round(perSec * duration * 10) / 10) : 0;
}

// 获取模型的成本系数
function getModelCostMultiplier(_model) {
  return 1;
}

// 更新视频生成界面的积分消耗显示
function updateVideoCostDisplay() {
  const costDisplay = document.getElementById('cost-display-video');
  if (!costDisplay) return;
  
  const cost = calculateVideoPointsCost('-video');
  const costValue = costDisplay.querySelector('.cost-value');
  if (costValue) {
    costValue.textContent = cost;
  }
}

function updateDramaCostDisplay() {
  const costDisplay = document.getElementById('cost-display-drama');
  if (!costDisplay) return;
  const costValue = costDisplay.querySelector('.cost-value');
  if (!costValue) return;

  // Get params from drama control panel
  var modelSelect = document.getElementById('modelSelect-drama');
  var resDropdown = document.getElementById('resDropdown-drama');
  var durDropdown = document.getElementById('durDropdown-drama');
  var epCount = document.getElementById('dramaEpisodeCount');

  var model = modelSelect ? modelSelect.value : '';
  var resolution = resDropdown ? resDropdown.textContent.trim().replace(/[▢◎▭▯◻▮▰⬌⬍]/g, '').trim() : '720p';
  var durationText = durDropdown ? durDropdown.textContent.trim().replace(/[▢◎▭▯◻▮▰⬌⬍]/g, '').trim() : '60s';
  var totalEpisodes = _dramaIsSingleEpisode ? 1 : (epCount ? parseInt(epCount.value) : 10);

  // Parse duration: "60s" → 60, "auto" → estimate 60s per episode
  var totalSeconds = 0;
  if (durationText === 'auto' || durationText.toLowerCase() === 'auto') {
    // Estimate: 8 scenes × 5s per scene × episodes = 40s per episode
    totalSeconds = 40 * totalEpisodes;
  } else {
    var match = durationText.match(/(\d+)/);
    var perEpisodeSeconds = match ? parseInt(match[1]) : 60;
    totalSeconds = perEpisodeSeconds * totalEpisodes;
  }

  // Calculate using points config
  var config = _pointsPerSecCache || {};
  var table = config[model] || {};

  // Fallback: if model not found in cache (e.g. "" placeholder), use first available model
  if (!table || Object.keys(table).length === 0) {
    for (var key of Object.keys(config)) {
      if (typeof config[key] === 'object' && config[key] !== null && key !== 'label') {
        table = config[key];
        break;
      }
    }
  }

  var perSec = table[resolution] || table['720p'] || 0;

  // Second fallback: try any model's pricing
  if (perSec === 0) {
    for (var key of Object.keys(config)) {
      var t = config[key];
      if (typeof t === 'object' && t !== null) {
        perSec = t[resolution] || t['720p'] || 0;
        if (perSec > 0) break;
      }
    }
  }

  // Final hardcoded fallback: if all else fails, use default Seedance 2.0 pricing
  if (perSec === 0) {
    var defaultPricing = { '480p': 2, '720p': 4, '1080p': 9 };
    perSec = defaultPricing[resolution] || defaultPricing['720p'] || 4;
  }

  if (perSec > 0) {
    var cost = Math.max(0.1, Math.round(perSec * totalSeconds * 10) / 10);
    costValue.textContent = cost;
    costDisplay.title = perSec + ' 积分/秒 × ' + totalSeconds + 's = ' + cost + ' 积分';
  } else {
    costValue.textContent = '?';
    costDisplay.title = '';
  }
}

// Get selected parameters for image generation
function getImageParams() {
  const model = document.getElementById('modelSelect-image').value || '';
  const ratioBtn = document.getElementById('ratioDropdown-image');
  const ratio = ratioBtn ? ratioBtn.textContent.trim().replace(/[▢◎▭▯◻▮▰]/g, '').trim() : '16:9';
  const resBtn = document.getElementById('resDropdown-image');
  const resolution = resBtn ? resBtn.textContent.trim().replace(/[▢◎▭▯◻▮▰]/g, '').trim() : '720p';
  
  return { model, ratio, resolution };
}

// 计算图片生成的积分消耗（支持小数点1位）
function calculateImagePointsCost() {
  const params = getImageParams();
  const { resolution, model } = params;

  // 优先使用后台配置（按模型查找）
  const config = _imageCostsCache || {};
  var cost;
  
  // 1. 模型特定定价
  if (model && config[model] && config[model][resolution] !== undefined) {
    cost = config[model][resolution];
  }
  // 2. 默认定价
  else if (config["default"] && config["default"][resolution] !== undefined) {
    cost = config["default"][resolution];
  }
  // 3. 旧格式兼容（flat 对象）
  else if (config[resolution] !== undefined) {
    cost = config[resolution];
  }
  
  console.log('[image-cost] model=' + model + ' resolution=' + resolution + ' cache=' + JSON.stringify(_imageCostsCache) + ' cost=' + cost);
  
  if (cost === undefined || cost === null) {
    console.warn('[image-cost] Missing key in cache, using default 5');
    cost = 5;
  }
  return Math.max(0.1, Math.round(cost * 10) / 10);
}

// 更新图片生成界面的积分消耗显示
function updateImageCostDisplay() {
  const costDisplay = document.getElementById('cost-display-image');
  if (!costDisplay) return;
  
  const cost = calculateImagePointsCost();
  const costValue = costDisplay.querySelector('.cost-value');
  if (costValue) {
    costValue.textContent = cost;
  }
}

// Create task card
function createTaskCard(task) {
  const isImageTask = task.is_image || (!task.video_url && !!task.image_url);
  const mediaUrl = isImageTask ? task.image_url : task.video_url;
  const isTerminalFail = task.status === 'FAILED' || task.status === 'CANCELLED' || task.status === 'ERROR';

  const tid = `'${task.id}'`;
  return `
    <div class="task-card" onclick="openTaskDetail(${tid})">
      <div class="task-preview">
        ${(task.status === 'PROCESSING' || task.status === 'PENDING') ? `
          <div style="text-align:center;">
            <div class="task-placeholder">${isImageTask ? '🖼️' : '⏳'}</div>
            <div style="font-size:12px;color:var(--t3);margin-top:8px;">
              ${task.is_composition && task.total_segments
                ? `片段 ${task.completed_segments || 0}/${task.total_segments} · ${task.progress || 0}%`
                : `${task.progress || 0}%`}
            </div>
            <div class="progress-bar"><div class="progress-fill animating" style="width:${task.progress || 0}%"></div></div>
          </div>
        ` : task.status === 'SUCCESS' && mediaUrl ? `
          ${isImageTask
            ? `<img src="${mediaUrl}" alt="Generated" style="width:100%;height:100%;object-fit:cover;">`
            : `<video src="${mediaUrl}" preload="auto" muted playsinline data-task-id="${task.id}"></video>`}
        ` : isTerminalFail ? `
          <div style="text-align:center;padding:16px 12px;">
            <div style="font-size:28px;opacity:0.7;">✕</div>
            ${task.error_msg ? `<div class="task-error-box">${task.error_msg}</div>` : ''}
          </div>
        ` : `
          <div class="task-placeholder">❌</div>
        `}
      </div>
      <div class="task-info">
        <div class="task-prompt">${task.prompt || t('js.no_description')}</div>
        <div class="task-meta">
          <span>${formatTime(task.created_at)}</span>
          <span class="task-status status-${task.status.toLowerCase()}">${getStatusText(task.status)}</span>
        </div>
        <div style="display:flex;gap:6px;margin-top:4px;">
          <button class="retry-btn" style="background:rgba(239,68,68,.15);color:#f87171;border-color:rgba(239,68,68,.3);" onclick="event.stopPropagation();deleteTask(${tid},${isImageTask})">🗑 删除</button>
        </div>
      </div>
    </div>
  `;
}

function captureVideoThumbnails(container) {
  container.querySelectorAll('video[data-task-id]').forEach(video => {
    // Seek to first frame; browser renders it without needing canvas or CORS
    const seek = () => {
      video.currentTime = 0.001;
    };
    if (video.readyState >= 1) {
      seek();
    } else {
      video.addEventListener('loadedmetadata', seek, { once: true });
    }
  });
}

// Get status text
function getStatusText(status) {
  const map = {
    'PROCESSING': t('js.status_processing'),
    'SUCCESS': t('js.status_success'),
    'FAILED': t('js.status_failed'),
    'PENDING': t('js.status_pending'),
    'CANCELLED': t('js.status_cancelled'),
    'ERROR': t('js.status_error'),
  };
  return map[status] || t('js.status_unknown');
}

// Format time
function formatTime(dateStr) {
  if (!dateStr) return t('js.status_unknown');
  // Server returns naive Beijing time strings (no tz suffix); treat as CST (+08:00)
  const normalized = /[Zz]|[+-]\d{2}:?\d{2}$/.test(dateStr) ? dateStr : dateStr + '+08:00';
  const date = new Date(normalized);
  const now = new Date();
  const diff = now - date;
  const lang = window.i18next ? window.i18next.language : 'zh';

  if (diff < 60000) return t('js.time_just_now');
  if (diff < 3600000) return `${Math.floor(diff / 60000)}${t('js.time_minutes_ago')}`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}${t('js.time_hours_ago')}`;
  return date.toLocaleDateString(lang === 'zh' || lang === 'zh-TW' ? 'zh-CN' : 'en-US');
}

// Refresh tasks list
async function refreshTasks() {
  try {
    // 如果用户未登录，直接显示空列表，避免发送请求
    if (!authToken && !currentUser) {
      currentTasks = [];
      renderTaskList();
      return;
    }
    
    const res = await fetch('/api/tasks/', {
      headers: { 'Authorization': `Bearer ${authToken}` }
    });
    if (!res.ok) {
      if (res.status === 401) {
        // 用户未登录，不自动弹出登录窗口
        console.debug('User not logged in, showing empty task list');
        currentTasks = [];
        renderTaskList();
        return;
      }
      throw new Error('Failed to fetch tasks');
    }
    
    const data = await res.json();
    currentTasks = (data.items || []).map(t => ({
      ...t,
      status: (t.status || '').toUpperCase()
    }));
    
    // Also fetch video composition tasks
    try {
      const compRes = await fetch('/api/tasks/compositions', {
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
      if (compRes.ok) {
        const compData = await compRes.json();
        if (compData.items) {
          compData.items.forEach(comp => {
            const converted = {
              id: `comp_${comp.id}`,
              _comp_id: comp.id,
              prompt: comp.prompt,
              status: comp.status.toUpperCase(),
              progress: comp.progress,
              video_url: comp.final_video_url || comp.video_url,
              image_url: null,
              created_at: comp.created_at,
              error_msg: comp.error_msg,
              points_consumed: comp.total_points_consumed || comp.points_consumed,
              total_duration: comp.total_duration,
              completed_segments: comp.completed_segments,
              total_segments: comp.total_segments,
              is_composition: true
            };
            currentTasks.push(converted);
          });
        }
      }
    } catch (e) {
      console.log('No composition endpoint');
    }
    
    // Also fetch image tasks
    try {
      const imageRes = await fetch('/api/images', {
        headers: { 'Authorization': `Bearer ${authToken}` }
      });
      if (imageRes.ok) {
        const imageData = await imageRes.json();
        if (imageData.items) {
          const imageIds = new Set(imageData.items.map(i => i.id));
          // Remove image tasks that were already loaded from /api/tasks/
          currentTasks = currentTasks.filter(t => !imageIds.has(t.id));
          imageData.items.forEach(imgTask => {
            const converted = {
              id: imgTask.id,
              prompt: imgTask.prompt,
              status: (imgTask.status || '').toUpperCase(),
              progress: imgTask.progress,
              image_url: imgTask.image_url,
              video_url: null,
              created_at: imgTask.created_at,
              error_msg: imgTask.error_msg,
              is_image: true
            };
            currentTasks.push(converted);
          });
        }
      }
    } catch (e) {
      console.log('No image tasks endpoint');
    }
    
    // Remove duplicate tasks by id (keep the latest one)
    const seenIds = new Set();
    currentTasks = currentTasks.filter(task => {
      // Skip if already seen
      if (seenIds.has(task.id)) {
        console.log(`[DEBUG] Skipping duplicate task: ${task.id}`);
        return false;
      }
      seenIds.add(task.id);
      return true;
    });
    
    // Filter out cancelled/failed/error tasks that are older than 24 hours (optional cleanup)
    const twentyFourHoursAgo = Date.now() - (24 * 60 * 60 * 1000);
    currentTasks = currentTasks.filter(task => {
      const terminalStatus = ['CANCELLED', 'FAILED', 'ERROR'];
      if (terminalStatus.includes(task.status)) {
        const createdAt = new Date(task.created_at).getTime();
        if (createdAt < twentyFourHoursAgo) {
          console.log(`[DEBUG] Filtering out old terminal task: ${task.id}`);
          return false;
        }
      }
      return true;
    });
    
    // Sort by creation time (newest first)
    currentTasks.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    
    renderTaskList();
  } catch (err) {
    console.error('Failed to refresh tasks:', err);
  }
}

// Render task list
function renderTaskList() {
  const grid = document.getElementById('results-grid');
  const empty = document.getElementById('empty-state');
  const moreBtn = document.getElementById('more-btn');
  
  if (!grid || !empty) return;
  
  // Show max 6 tasks on homepage
  const displayTasks = currentTasks.slice(0, 6);
  const hasMore = currentTasks.length > 6;
  
  if (currentTasks.length === 0) {
    grid.innerHTML = '';
    empty.style.display = 'block';
    if (moreBtn) moreBtn.style.display = 'none';
  } else {
    empty.style.display = 'none';
    grid.innerHTML = displayTasks.map(createTaskCard).join('');
    captureVideoThumbnails(grid);
    
    // Show/hide "more" button
    if (moreBtn) {
      moreBtn.style.display = hasMore ? 'inline-block' : 'none';
    }

    // Start polling for processing tasks
    displayTasks.forEach(task => {
      if ((task.status === 'PROCESSING' || task.status === 'PENDING') && !pollingIntervals[task.id]) {
        if (!taskStartTimes[task.id]) taskStartTimes[task.id] = Date.now();
        if (task.is_image) {
          startPollingImage(task.id);
        } else if (task.is_composition) {
          startPollingComposition(task.id, task._comp_id);
        } else {
          startPolling(task.id);
        }
      }
    });
  }
}

// Start polling for task status
function startPolling(taskId) {
  if (!taskStartTimes[taskId]) taskStartTimes[taskId] = Date.now();
  let failCount = 0;
  pollingIntervals[taskId] = setInterval(async () => {
    try {
      const token = apiKey();
      const authHeader = token ? { 'Authorization': `Bearer ${token}` } : {};

      let res = await fetch(`/api/tasks/${taskId}`, { headers: authHeader });
      let data;

      if (!res.ok) {
        res = await fetch(`/api/tasks/compose/${taskId}`, { headers: authHeader });
        if (!res.ok) {
          stopPolling(taskId);
          return;
        }
        data = await res.json();
        if (data.success) {
          data = {
            id: taskId,
            status: (data.status || '').toUpperCase(),
            progress: data.progress,
            video_url: data.video_url,
            image_url: null,
            error_msg: data.error_msg,
            prompt: '',
            created_at: new Date().toISOString(),
          };
        }
      } else {
        data = await res.json();
        if (data.status) data.status = data.status.toUpperCase();
      }

      failCount = 0;
      const terminal = ['SUCCESS', 'FAILED', 'CANCELLED', 'ERROR'];
      const isTerminal = terminal.includes(data.status);

      // Fake progress: interpolate 0→90% over ~120s when server returns no real progress
      if (!isTerminal && (data.progress == null || data.progress === 0)) {
        const elapsed = (Date.now() - (taskStartTimes[taskId] || Date.now())) / 1000;
        data.progress = Math.min(90, Math.round((elapsed / 120) * 90));
      }
      if (isTerminal && data.status === 'SUCCESS') {
        data.progress = 100;
        delete taskStartTimes[taskId];
      }

      const index = currentTasks.findIndex(t => t.id == taskId);
      if (index !== -1) {
        currentTasks[index] = { ...currentTasks[index], ...data };
        if (isTerminal) stopPolling(taskId);
        renderTaskList();
      }
    } catch (err) {
      console.error('Polling error:', err);
      failCount++;
      if (failCount >= 3) {
        stopPolling(taskId);
        const index = currentTasks.findIndex(t => t.id == taskId);
        if (index !== -1 && currentTasks[index].status !== 'SUCCESS') {
          currentTasks[index].status = 'FAILED';
          currentTasks[index].error_msg = t('js.network_error_retry');
          renderTaskList();
        }
      }
    }
  }, 3000);
}

function startPollingComposition(taskId, compId) {
  const apiId = compId || taskId;
  let failCount = 0;
  pollingIntervals[taskId] = setInterval(async () => {
    try {
      const token = apiKey();
      const res = await fetch(`/api/tasks/compose/${apiId}`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      });
      if (!res.ok) { failCount++; if (failCount >= 3) stopPolling(taskId); return; }
      const data = await res.json();
      if (!data.success) { failCount++; if (failCount >= 3) stopPolling(taskId); return; }
      const st = (data.status || '').toUpperCase();
      const index = currentTasks.findIndex(t => t.id == taskId);
      if (index !== -1) {
        currentTasks[index] = {
          ...currentTasks[index],
          status: st,
          progress: data.progress || 0,
          video_url: data.video_url || null,
          error_msg: data.error_msg || null,
          completed_segments: data.completed_segments ?? currentTasks[index].completed_segments,
          total_segments: data.total_segments ?? currentTasks[index].total_segments,
        };
        if (['SUCCESS', 'FAILED', 'CANCELLED'].includes(st)) stopPolling(taskId);
        renderTaskList();
      }
      failCount = 0;
    } catch (err) {
      failCount++;
      if (failCount >= 3) stopPolling(taskId);
    }
  }, 5000);
}

function startPollingImage(taskId) {
  let failCount = 0;
  pollingIntervals[taskId] = setInterval(async () => {
    try {
      const token = apiKey();
      const res = await fetch(`/api/images/${taskId}`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      });
      if (!res.ok) { failCount++; if (failCount >= 3) stopPolling(taskId); return; }
      const data = await res.json();
      const st = (data.status || '').toUpperCase();
      const index = currentTasks.findIndex(t => t.id == taskId);
      if (index !== -1) {
        currentTasks[index] = { ...currentTasks[index], status: st, progress: data.progress || 0, image_url: data.image_url || null, error_msg: data.error_msg };
        if (['SUCCESS', 'FAILED', 'CANCELLED'].includes(st)) stopPolling(taskId);
        renderTaskList();
      }
      failCount = 0;
    } catch (err) {
      failCount++;
      if (failCount >= 3) stopPolling(taskId);
    }
  }, 3000);
}

// Stop polling
function stopPolling(taskId) {
  if (pollingIntervals[taskId]) {
    clearInterval(pollingIntervals[taskId]);
    delete pollingIntervals[taskId];
  }
}

async function deleteTask(taskId, isImageTask) {
  if (!confirm('确定删除此作品？此操作不可撤销。')) return;
  const token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey') || authToken;
  if (!token) { alert('请先登录'); return; }

  if (String(taskId).startsWith('comp_')) {
    const compId = String(taskId).replace('comp_', '');
    try {
      const res = await fetch(`/api/tasks/compositions/${compId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) { alert('删除失败'); return; }
    } catch (e) { alert('删除失败'); return; }
    stopPolling(taskId);
    currentTasks = currentTasks.filter(t => t.id != taskId);
    renderTaskList();
    return;
  }

  const endpoint = isImageTask ? `/api/images/${taskId}` : `/api/tasks/${taskId}`;
  try {
    const res = await fetch(endpoint, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (res.ok) {
      stopPolling(taskId);
      currentTasks = currentTasks.filter(t => t.id != taskId);
      renderTaskList();
    } else {
      alert('删除失败');
    }
  } catch (e) {
    alert('删除失败');
  }
}

// Open task detail modal
function openTaskDetail(taskId) {
  const task = currentTasks.find(t => t.id == taskId);
  if (!task) return;
  
  const modal = document.getElementById('task-modal');
  const body = document.getElementById('modal-body');
  if (!modal || !body) return;
  
  const lang = window.i18next ? window.i18next.language : 'zh';
  
  const isImageTask = task.is_image || (!task.video_url && task.image_url);
  const mediaUrl = isImageTask ? task.image_url : task.video_url;
  const hasMedia = task.status === 'SUCCESS' && mediaUrl;

  const locale = lang === 'zh' || lang === 'zh-TW' ? 'zh-CN' : 'en-US';

  body.innerHTML = `
    <div class="modal-preview">
      ${hasMedia ? `
        ${isImageTask
          ? `<img src="${mediaUrl}" alt="Generated image" style="max-width:100%;max-height:360px;border-radius:8px;">`
          : `<video controls src="${mediaUrl}" style="max-height:360px;width:100%;border-radius:8px;">Your browser does not support the video tag.</video>
             <div style="padding:6px 12px;background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.2);border-radius:6px;margin-top:8px;font-size:12px;color:#fbbf24;">⚠️ 视频链接仅保留 12 小时，请尽快下载保存！</div>`
        }
      ` : (task.status === 'FAILED' || task.status === 'CANCELLED' || task.status === 'ERROR') ? `
        <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;padding:40px 24px;gap:14px;">
          <div style="width:56px;height:56px;border-radius:50%;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);display:flex;align-items:center;justify-content:center;font-size:24px;">✕</div>
          <p style="color:var(--t2);margin:0;font-weight:500;">${task.status === 'CANCELLED' ? t('js.task_cancelled') : t('js.gen_failed')}</p>
          ${task.error_msg ? `<div class="modal-error-box">${task.error_msg}</div>` : ''}
        </div>
      ` : `
        <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;padding:40px;">
          <div class="task-placeholder">${isImageTask ? '🖼️' : '⏳'}</div>
          <p style="color:var(--t3);margin-top:16px;">${isImageTask ? '图片生成中' : t('js.status_processing')}... ${task.progress || 0}%</p>
          <div class="progress-bar" style="width:200px;margin-top:16px;"><div class="progress-fill animating" style="width:${task.progress || 0}%"></div></div>
        </div>
      `}
    </div>
    <div class="modal-info">
      <div class="modal-label">类型</div>
      <div class="modal-value">${isImageTask ? '🖼️ 图片生成' : '🎬 视频生成'}</div>
      <div class="modal-label">${t('modal.description')}</div>
      <div class="modal-value">${task.prompt || t('js.no_description')}</div>
      <div class="modal-label">${t('modal.status')}</div>
      <div class="modal-value"><span class="task-status status-${task.status.toLowerCase()}">${getStatusText(task.status)}</span></div>
      <div class="modal-label">${t('modal.created_at')}</div>
      <div class="modal-value">${task.created_at ? new Date(/[Zz]|[+-]\d{2}:?\d{2}$/.test(task.created_at) ? task.created_at : task.created_at + '+08:00').toLocaleString(locale) : t('js.status_unknown')}</div>
      ${task.points_consumed !== undefined ? `
        <div class="modal-label">${t('modal.points_consumed')}</div>
        <div class="modal-value">${task.points_consumed}</div>
      ` : ''}
    </div>
    ${hasMedia ? `
      <div class="modal-actions">
        <button class="modal-action-btn secondary" onclick="downloadMedia('${encodeURIComponent(mediaUrl)}', '${encodeURIComponent(isImageTask ? 'image.jpg' : 'video.mp4')}')">
          ${t('js.download')}
        </button>
        <button class="modal-action-btn primary" onclick="copyLink('${encodeURIComponent(mediaUrl)}')">
          ${t('auth.copy_link')}
        </button>
      </div>
    ` : (task.status === 'FAILED' || task.status === 'CANCELLED' || task.status === 'ERROR') ? `
      <div class="modal-actions">
      </div>
    ` : ''}
  `;
  
  modal.classList.add('open');
}

// Close modal
function closeModal() {
  const taskModal = document.getElementById('task-modal');
  if (taskModal) taskModal.classList.remove('open');
}

async function retryTask(taskId) {
  const task = currentTasks.find(t => t.id == taskId);
  if (!task) return;
  if (!apiKey()) { alert(t('js.signin_first')); return; }

  try {
    const res = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + apiKey(), 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: task.model || 'seedance-1.0-fast',
        prompt: task.prompt || '',
        duration_seconds: task.duration_seconds || 5,
        resolution: task.resolution || '720p',
        ratio: task.ratio || '16:9',
      }),
    });
    const data = await res.json();
    if (data.success && data.task_id) {
      await refreshTasks();
      startPolling(data.task_id);
    } else {
      handleGenError(data.detail || data.message);
    }
  } catch (err) {
    alert(t('js.retry_failed') + ': ' + err.message);
  }
}

// Download media
function downloadMedia(url, filename) {
  url = decodeURIComponent(url);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// Copy link
function copyLink(url) {
  url = decodeURIComponent(url);
  navigator.clipboard.writeText(url).then(() => {
    alert(t('auth.link_copied'));
  }).catch(() => {
    // Fallback for older browsers
    const textarea = document.createElement('textarea');
    textarea.value = url;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    alert(t('auth.link_copied'));
  });
}

// 推理模型优化提示词
async function optimizePrompt(prompt, model = '') {
  const token = apiKey();
  if (!token) return prompt;
  
  try {
    const res = await fetch('/api/optimize-prompt', {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      },
      body: JSON.stringify({
        prompt,
        model: model // 使用用户选择的接入点ID
      })
    });
    
    const data = await res.json();
    if (data.success && data.optimized_prompt) {
      return data.optimized_prompt;
    }
  } catch (err) {
    console.warn('Prompt optimization failed, using original prompt:', err);
  }
  
  return prompt;
}

// AI 优化提示词按钮点击处理
async function handleAIEnhanceClick(type) {
  // 检查用户是否登录
  if (!authToken && !currentUser) {
    alert(t('auth.please_login') || '请先登录以使用 AI 优化功能');
    openAuthModal();
    return;
  }
  
  const textareaId = type === 'video' ? 'prompt-video' : 'prompt-image';
  const buttonId = type === 'video' ? 'ai-enhance-video' : 'ai-enhance-image';
  const modelSelectId = type === 'video' ? 'modelSelect-video' : 'modelSelect-image';
  
  const textarea = document.getElementById(textareaId);
  const button = document.getElementById(buttonId);
  const modelSelect = document.getElementById(modelSelectId);
  
  if (!textarea || !button) return;
  
  const originalPrompt = textarea.value.trim();
  if (!originalPrompt) {
    alert(t('gen.please_enter_prompt') || '请先输入提示词');
    return;
  }
  
  // 获取用户选择的推理模型
  const selectedModel = modelSelect ? modelSelect.value : '';
  
  button.disabled = true;
  button.innerHTML = '<span class="loading-spinner"></span> ' + (t('gen.optimizing') || '优化中...');
  
  try {
    const optimizedPrompt = await optimizePrompt(originalPrompt, selectedModel);
    
    // 显示优化提示词框
    const enhancedContainer = document.getElementById(`prompt-enhanced-${type}`);
    const enhancedTextarea = document.getElementById(`prompt-enhanced-text-${type}`);
    const enhancedToggle = document.getElementById(`enhance-toggle-${type}`);
    
    if (enhancedContainer && enhancedTextarea) {
      enhancedTextarea.value = optimizedPrompt;
      enhancedContainer.style.display = 'block';
      
      // 默认启用优化提示词
      if (enhancedToggle) {
        enhancedToggle.classList.add('active');
      }
    }
  } catch (err) {
    console.error('AI enhancement failed:', err);
    alert(t('gen.optimize_fail') || '提示词优化失败，请重试');
  } finally {
    button.disabled = false;
    button.innerHTML = '✨ ' + (t('gen.ai_enhance') || 'AI 优化提示词');
  }
}

// 初始化AI优化提示词框的交互
function initAIEnhancedPrompt() {
  ['video', 'image'].forEach(type => {
    // 清除按钮
    const clearBtn = document.getElementById(`enhance-clear-${type}`);
    const container = document.getElementById(`prompt-enhanced-${type}`);
    const textarea = document.getElementById(`prompt-enhanced-text-${type}`);

    if (clearBtn && container) {
      clearBtn.addEventListener('click', () => {
        container.style.display = 'none';
        if (textarea) textarea.value = '';
      });
    }

    // 使用优化切换按钮
    const toggleBtn = document.getElementById(`enhance-toggle-${type}`);
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => {
        toggleBtn.classList.toggle('active');
      });
    }
  });
}

// 获取最终使用的提示词（优先使用优化提示词）
function getEffectivePrompt(type) {
  const enhancedContainer = document.getElementById(`prompt-enhanced-${type}`);
  const enhancedToggle = document.getElementById(`enhance-toggle-${type}`);
  const enhancedTextarea = document.getElementById(`prompt-enhanced-text-${type}`);
  const originalTextarea = document.getElementById(`prompt-${type}`);
  
  // 如果优化提示词框显示且启用，则使用优化提示词
  if (enhancedContainer && 
      enhancedContainer.style.display !== 'none' && 
      enhancedToggle && 
      enhancedToggle.classList.contains('active') && 
      enhancedTextarea && 
      enhancedTextarea.value.trim()) {
    return enhancedTextarea.value.trim();
  }
  
  // 否则使用原始描述
  return originalTextarea ? originalTextarea.value.trim() : '';
}

// 初始化推理模型按钮事件
function initAIEnhanceButtons() {
  const videoBtn = document.getElementById('ai-enhance-video');
  const imageBtn = document.getElementById('ai-enhance-image');
  
  if (videoBtn) {
    videoBtn.addEventListener('click', () => handleAIEnhanceClick('video'));
  }
  
  if (imageBtn) {
    imageBtn.addEventListener('click', () => handleAIEnhanceClick('image'));
  }
  
  // 初始化优化提示词框交互
  initAIEnhancedPrompt();
}

// Generate video
async function generateVideo() {
  // 获取最终使用的提示词（优先使用优化提示词）
  const effectivePrompt = getEffectivePrompt('video');
  if (!effectivePrompt) {
    alert(t('auth.enter_video_desc'));
    return;
  }
  
  // 获取原始描述
  const originalPrompt = document.getElementById('prompt-video').value.trim();
  
  const params = getVideoParams('-video');
  const btn = document.getElementById('gen-btn-video');
  const originalText = btn.innerHTML;
  
  btn.innerHTML = '⏳';
  btn.disabled = true;

  try {
    // 使用有效的提示词（可能是原始描述或优化后的提示词）
    const prompt = effectivePrompt;
    
    // 根据时长选择不同的API端点
    // 根据模型版本设置单段最大时长：
    // - 2.0 版本：15 秒
    // - 1.5 和 1.0 版本：12 秒
    function getModelMaxDuration(model) {
      if (!model) return 12;
      const modelLower = model.toLowerCase();
      if (modelLower.includes('2.0') || modelLower.includes('seedance2') || modelLower.includes('dreamina-seedance-2')) {
        return 30;
      }
      return 15;
    }
    const maxSingleDuration = getModelMaxDuration(params.model);
    const endpoint = params.duration > maxSingleDuration ? '/api/tasks/compose' : '/api/tasks/';
    const token = apiKey();
    
    if (!token) {
      openAuthModal();
      btn.innerHTML = originalText;
      btn.disabled = false;
      return;
    }
    
    // 构建请求体，包含真人素材参数
      const requestBody = {
        prompt,
        original_prompt: originalPrompt,
        model: params.model || 'ep-20260506113134-gct7l',
        ratio: params.ratio,
        resolution: params.resolution,
        duration: params.duration,
        duration_seconds: params.duration,
        generate_audio: true,
        watermark: false,
        reference_images: (referenceFiles['video'] || []).filter(f => f.type === 'image').map(f => f.url),
        reference_videos: (referenceFiles['video'] || []).filter(f => f.type === 'video').map(f => f.url),
        reference_audios: (referenceFiles['video'] || []).filter(f => f.type === 'audio').map(f => f.url),
      };
      
      // 添加真人素材参数（参考 BytePlus 文档：https://docs.byteplus.com/en/docs/ModelArk/2333589）
      console.log('[DEBUG] params.use_real_people:', params.use_real_people);
      console.log('[DEBUG] referenceFiles[video]:', referenceFiles['video']);
      if (params.use_real_people) {
        requestBody.use_real_people = true;
        console.log('[DEBUG] Added use_real_people=true to requestBody');
        if (params.avatar_id) requestBody.avatar_id = params.avatar_id;
        if (params.real_human_portrait_id) requestBody.real_human_portrait_id = params.real_human_portrait_id;
        if (params.action_id) requestBody.action_id = params.action_id;
        if (params.background_id) requestBody.background_id = params.background_id;
        if (params.voice_id) requestBody.voice_id = params.voice_id;
      }
      
      
      // 校验：音频参考不能是唯一的参考输入
      if ((requestBody.reference_audios || []).length > 0 && (requestBody.reference_images || []).length === 0 && (requestBody.reference_videos || []).length === 0) {
        showNotification('Audio reference must be accompanied by at least one image or video
音频参考必须配合至少一张图片或一段视频使用', 'error');
        btn.innerHTML = originalText;
        btn.disabled = false;
        return;
      }
            const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify(requestBody)
      });
    
    let data;
    try {
      data = await res.json();
    } catch (jsonErr) {
      // Handle non-JSON responses (e.g., server errors)
      console.error('Failed to parse response as JSON:', jsonErr);
      if (res.status === 500) {
        throw new Error(t('js.server_error') || 'Server error');
      }
      throw new Error(t('js.gen_failed') + ': ' + (await res.text()).substring(0, 100));
    }
    
    if (data.success) {
      // 立即创建一个临时任务卡片显示在列表中
      const tempTask = {
        id: data.task_id || `comp_${data.composition_id}`,
        prompt: prompt.substring(0, 100) + (prompt.length > 100 ? '...' : ''),
        status: 'PROCESSING',
        progress: 0,
        created_at: new Date().toISOString(),
        is_image: false
      };
      
      // 添加到当前任务列表开头
      currentTasks.unshift(tempTask);
      
      // 立即渲染任务列表，显示新创建的任务
      renderTaskList();
      
      // Start polling immediately
      if (data.composition_id) {
        const frontendId = `comp_${data.composition_id}`;
        if (!pollingIntervals[frontendId]) {
          taskStartTimes[frontendId] = Date.now();
          startPollingComposition(frontendId, data.composition_id);
        }
      } else if (!pollingIntervals[data.task_id]) {
        taskStartTimes[data.task_id] = Date.now();
        startPolling(data.task_id);
      }
    } else {
      handleGenError(data.detail || data.message);
    }
  } catch (err) {
    console.error('Generate video error:', err);
    if (err.message.includes('401')) {
      openAuthModal();
    } else {
      alert(t('js.gen_failed') + ': ' + err.message);
    }
  } finally {
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

// Generate image
async function generateImage() {
  const originalPrompt = document.getElementById('prompt-image').value.trim();
  if (!originalPrompt) {
    alert(t('auth.enter_image_desc'));
    return;
  }
  
  const params = getImageParams();
  const btn = document.getElementById('gen-btn-image');
  const originalText = btn.innerHTML;
  
  btn.innerHTML = '⏳';
  btn.disabled = true;

  try {
    const prompt = getEffectivePrompt('image') || originalPrompt;
    
    const token = apiKey();
    
    if (!token) {
      openAuthModal();
      btn.innerHTML = originalText;
      btn.disabled = false;
      return;
    }
    
    const res = await fetch('/api/images/generate', {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      },
      body: JSON.stringify({
        prompt,
        original_prompt: originalPrompt,
        endpoint_id: params.model,
        ratio: params.ratio,
        resolution: params.resolution,
        reference_images: (referenceFiles['image'] || []).filter(f => f.type === 'image').map(f => f.url),
      })
    });
    
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch(e) { throw new Error(text.slice(0, 200)); }

    if (res.ok && data.success) {
      const taskId = data.task_id;
      // Add a placeholder task entry so it shows immediately
      currentTasks.unshift({
        id: taskId,
        prompt: originalPrompt,
        status: 'PROCESSING',
        progress: 0,
        image_url: null,
        video_url: null,
        created_at: new Date().toISOString(),
        is_image: true
      });
      renderTaskList();
      if (taskId && !pollingIntervals[taskId]) {
        startPollingImage(taskId);
      }
    } else {
      handleGenError(data.detail || data.message);
    }
  } catch (err) {
    console.error('Generate image error:', err);
    if (err.message.includes('401')) {
      openAuthModal();
    } else {
      alert(t('js.gen_failed') + err.message);
    }
  } finally {
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}

// Bind generate buttons
document.addEventListener('DOMContentLoaded', function() {
  // Video generation
  const videoBtn = document.getElementById('gen-btn-video');
  if (videoBtn) {
    videoBtn.addEventListener('click', generateVideo);
  }
  
  // Image generation
  const imageBtn = document.getElementById('gen-btn-image');
  if (imageBtn) {
    imageBtn.addEventListener('click', generateImage);
  }
  
  // Close modal when clicking overlay
  const taskModal = document.getElementById('task-modal');
  if (taskModal) {
    taskModal.addEventListener('click', function(e) {
      if (e.target === this) {
        closeModal();
      }
    });
  }
  
  // Initial load tasks
  refreshTasks();
});

// Load models from admin config
async function loadVideoEndpoints() {
  try {
    const res = await fetch('/api/public/models');
    const cfg = await res.json();
    _modelsConfigCache = cfg;

    const videoSelect = document.getElementById('modelSelect-video');
    if (videoSelect) {
      videoSelect.innerHTML = '';
      const vModels = (cfg.video || []).filter(m => m.enabled !== false);
      vModels.sort((a,b) => (a.sort||0) - (b.sort||0));
      if (vModels.length > 0) {
        vModels.forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.name || m.id;
          if (m.is_default) opt.selected = true;
          videoSelect.appendChild(opt);
        });
      } else {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = t('js.no_endpoints') || '暂无可用模型';
        videoSelect.appendChild(opt);
      }
      videoSelect.dispatchEvent(new Event('change'));
    }

    const imageSelect = document.getElementById('modelSelect-image');
    if (imageSelect) {
      imageSelect.innerHTML = '';
      const iModels = (cfg.image || []).filter(m => m.enabled !== false);
      iModels.sort((a,b) => (a.sort||0) - (b.sort||0));
      if (iModels.length > 0) {
        iModels.forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.name || m.id;
          if (m.is_default) opt.selected = true;
          imageSelect.appendChild(opt);
        });
      } else {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'Seedream 3.0';
        imageSelect.appendChild(opt);
      }
    }
  } catch (err) {
    console.error('Failed to load models:', err);
  }
}

// Load models on page load
loadVideoEndpoints();

// ── Reference Material Features ───────────────────────────────────

// Storage for uploaded/reference files
const referenceFiles = {
  video: [],
  image: []
};

// Initialize reference upload zones
function initReferenceUploads() {
  // Video mode upload
  initUploadZone('video');
  // Image mode upload
  initUploadZone('image');
  // Drama mode upload
  initUploadZone('drama');
  
  // Asset library buttons
  initAssetLibrary('video');
  initAssetLibrary('image');
  initAssetLibrary('drama');
  
  // Model selection change handlers
  initModelChangeHandlers();
  
  // Reference mode change handlers
  initRefModeChangeHandlers();
}

function getDramaRenderParams() {
  var model = document.getElementById('modelSelect-drama');
  var ratio = document.getElementById('ratioDropdown-drama');
  var res = document.getElementById('resDropdown-drama');
  var dur = document.getElementById('durDropdown-drama');
  var refMode = document.getElementById('refModeDropdown-drama');
  var subtitleRemoval = document.getElementById('subtitle-removal-drama');
  var useRealPeople = document.getElementById('use-real-people-drama');

  // If model select has empty value (not yet populated), use first option
  var modelValue = model ? model.value : '';
  if (!modelValue && model && model.options.length > 0) {
    modelValue = model.options[0].value || '';
  }
  
  return {
    model: modelValue,
    ratio: ratio ? ratio.textContent.trim().replace(/[▢◎▭▯◻▮▰⬌⬍]/g, '').trim() : '9:16',
    resolution: res ? res.textContent.trim().replace(/[▢◎▭▯◻▮▰⬌⬍]/g, '').trim() : '720p',
    duration: dur ? dur.textContent.trim().replace(/[▢◎▭▯◻▮▰⬌⬍]/g, '').trim() : '60s',
    ref_mode: refMode ? (refMode.querySelector('[data-value]') ? refMode.querySelector('[data-value]').getAttribute('data-value') : 'text2vid') : 'text2vid',
    subtitle_removal: subtitleRemoval ? subtitleRemoval.checked : false,
    use_real_people: useRealPeople ? useRealPeople.checked : false,
  };
}

function initUploadZone(mode) {
  const uploadZone = document.getElementById(`upload-zone-${mode}`);
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.id = `file-input-${mode}`;
  fileInput.multiple = true;
  fileInput.accept = mode === 'video' ? 'image/*,video/*' : 'image/*';
  fileInput.style.display = 'none';
  if (uploadZone) {
    uploadZone.appendChild(fileInput);
  } else {
    document.body.appendChild(fileInput);
  }

  if (uploadZone) {
    uploadZone.addEventListener('click', (e) => {
      if (e.target === fileInput) return;
      if (!apiKey()) { alert(t('js.signin_first')); return; }
      if (fileInput._busy) return;
      fileInput.click();
    });
  }

  fileInput.addEventListener('click', e => e.stopPropagation());

  fileInput.addEventListener('change', async e => {
    e.stopPropagation();
    const files = Array.from(e.target.files);
    fileInput.value = '';
    if (!files.length) return;
    fileInput._busy = true;
    
    const maxFiles = mode === 'video' ? 9 : 14;
    if (referenceFiles[mode].length + files.length > maxFiles) {
      alert(t('js.max_files') || `最多支持 ${maxFiles} 个文件`);
      return;
    }
    
    const uploadingText = t('js.uploading') || '上传中...';
    uploadZone.innerHTML = `<span class="ref-icon">📤</span><span class="ref-label">${uploadingText}</span>`;
    
    for (const file of files) {
      const fd = new FormData();
      fd.append('file', file);
      try {
        const res = await fetch('/api/files/upload', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + apiKey() },
          body: fd,
        });
        const data = await res.json();
        if (data.success) {
          const fileUrl = data.data.local_url || data.data.url;
          const isVideo=file.type.startsWith("video");
          const isAudio=file.type.startsWith("audio");
          let thumbUrl = isVideo ? null : fileUrl;
          if (isVideo) {
            thumbUrl = await new Promise(resolve => {
              const v = document.createElement('video');
              v.src = fileUrl;
              v.currentTime = 0.1;
              v.muted = true;
              v.onloadeddata = () => {
                const c = document.createElement('canvas');
                c.width = 80; c.height = 45;
                c.getContext('2d').drawImage(v, 0, 0, 80, 45);
                resolve(c.toDataURL('image/jpeg', 0.7));
              };
              v.onerror = () => resolve(null);
            });
          }
          referenceFiles[mode].push({
            name: file.name,
            file_id: data.data.id,
            url: fileUrl,
            thumbUrl,
            type:isVideo?"video":(isAudio?"audio":"image"),
            index: referenceFiles[mode].length + 1
          });
        } else {
          alert(t('js.upload_failed') + (data.message || t('js.unknown_error')));
        }
      } catch (err) {
        alert((t('js.upload_error') || '上传失败: ') + err.message);
      }
    }
    
    uploadZone.innerHTML = `<span class="ref-icon">📤</span><span class="ref-label">${t('gen.upload') || '上传文件'}</span>`;
    updateReferenceFilesList(mode);
    updateReferenceTags(mode);
    fileInput._busy = false;
  });
}

function initAssetLibrary(mode) {
  const libraryBtn = document.getElementById(`library-btn-${mode}`);
  if (!libraryBtn) return;
  
  libraryBtn.addEventListener('click', () => {
    if (!apiKey()) { alert(t('js.signin_first')); return; }
    openAssetLibrary(mode);
  });
}

function openAssetLibrary(mode) {
  const modalId = 'ref-file-library-modal';
  let modal = document.getElementById(modalId);
  if (!modal) {
    modal = document.createElement('div');
    modal.id = modalId;
    modal.className = 'asset-library-modal';
    modal.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div class="library-modal-content" style="background:var(--bg2,#1a1a2e);border-radius:12px;padding:24px;max-width:720px;width:92%;max-height:85vh;display:flex;flex-direction:column;gap:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <h3 style="margin:0;font-size:16px;">${t('gen.asset_library')}</h3>
          <button onclick="document.getElementById('${modalId}').style.display='none'" style="background:none;border:none;color:var(--t2);font-size:20px;cursor:pointer;">&times;</button>
        </div>
        <div id="ref-lib-tabs" style="display:flex;gap:8px;border-bottom:1px solid var(--border,#333);padding-bottom:8px;">
          <button class="ref-lib-tab active" data-src="uploads" style="padding:5px 14px;border-radius:6px;border:none;background:var(--accent,#7c3aed);color:#fff;cursor:pointer;font-size:13px;">我的上传</button>
        </div>
        <div id="ref-library-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:12px;overflow-y:auto;flex:1;min-height:200px;"></div>
        <div style="display:flex;justify-content:flex-end;gap:8px;">
          <button onclick="document.getElementById('${modalId}').style.display='none'" style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:none;color:var(--t2);cursor:pointer;">${t('js.cancel')}</button>
          <button id="ref-library-confirm" style="padding:8px 16px;border-radius:6px;border:none;background:var(--accent,#7c3aed);color:#fff;cursor:pointer;">${t('js.confirm')}</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    modal.querySelector('#ref-lib-tabs').addEventListener('click', e => {
      const tab = e.target.closest('.ref-lib-tab');
      if (!tab) return;
      modal.querySelectorAll('.ref-lib-tab').forEach(t => {
        t.style.background = 'none';
        t.style.color = 'var(--t2)';
        t.style.border = '1px solid var(--border,#444)';
        t.classList.remove('active');
      });
      tab.style.background = 'var(--accent,#7c3aed)';
      tab.style.color = '#fff';
      tab.style.border = 'none';
      tab.classList.add('active');
      modal._src = tab.dataset.src;
      _loadRefLibrary(modal._src);
    });

    document.getElementById('ref-library-confirm').addEventListener('click', () => {
      const selected = modal.querySelectorAll('.ref-lib-item.selected');
      const existingIds = new Set((referenceFiles[modal._mode] || []).map(f => f.file_id));
      selected.forEach(item => {
        if (existingIds.has(item.dataset.id)) return;
        const ftype = item.dataset.ftype === 'video' ? 'video' : 'image';
        referenceFiles[modal._mode] = referenceFiles[modal._mode] || [];
        referenceFiles[modal._mode].push({ name: item.dataset.name, file_id: item.dataset.id, url: item.dataset.url, type: ftype });
      });
      updateReferenceFilesList(modal._mode);
      updateReferenceTags(modal._mode);
      modal.style.display = 'none';
    });
  }
  modal._mode = mode;
  modal._src = 'uploads';
  // Reset tabs
  modal.querySelectorAll('.ref-lib-tab').forEach((tab, i) => {
    if (i === 0) { tab.style.background = 'var(--accent,#7c3aed)'; tab.style.color = '#fff'; tab.style.border = 'none'; tab.classList.add('active'); }
    else { tab.style.background = 'none'; tab.style.color = 'var(--t2)'; tab.style.border = '1px solid var(--border,#444)'; tab.classList.remove('active'); }
  });
  modal.style.display = 'flex';
  _loadRefLibrary('uploads');
}

function _loadRefLibrary(src) {
  const grid = document.getElementById('ref-library-grid');
  grid.innerHTML = '<div style="color:var(--t3);text-align:center;padding:24px;grid-column:1/-1;">加载中...</div>';

  if (src === 'uploads') {
    fetch('/api/files/list', { headers: { 'Authorization': 'Bearer ' + apiKey() } })
      .then(r => r.json())
      .then(data => {
        const files = data.data || [];
        if (!files.length) {
          grid.innerHTML = '<div style="color:var(--t3);text-align:center;padding:24px;grid-column:1/-1;">暂无上传文件</div>';
          return;
        }
        grid.innerHTML = files.map(f => {
          const mime = f.mime_type || '';
          const assetType = f.asset_type || '';
          const isImg = assetType === 'Image' || mime.startsWith('image/') || /\.(jpg|jpeg|png|webp|gif)$/i.test(f.filename || '');
          const isVid = assetType === 'Video' || mime.startsWith('video/') || /\.(mp4|mov|webm|avi|mkv)$/i.test(f.filename || '');
          const url = f.url || '';
          const fid = f.file_id || f.id || '';
          const statusLabel = f.status && f.status !== 'active' ? `<div style="position:absolute;bottom:22px;left:0;right:0;text-align:center;font-size:9px;color:#f59e0b;background:rgba(0,0,0,.6);padding:1px 0;">${f.status}</div>` : '';
          let preview = '';
          if (isImg && url) {
            preview = `<img src="${url}" style="width:100%;height:80%;object-fit:cover;border-radius:4px;" loading="lazy" onerror="this.parentNode.querySelector('.fb-icon').style.display='block';this.style.display='none'">`;
          } else if (isVid && url) {
            preview = `<img class="ref-lib-vid-thumb" data-src="${url}" style="width:100%;height:80%;object-fit:cover;border-radius:4px;display:none;">`;
          }
          const icon = `<div class="fb-icon" style="font-size:28px;${isImg&&url?'display:none':'display:block'}">${isVid ? '🎬' : isImg ? '🖼️' : '📄'}</div>`;
          const delBtn = `<button class="ref-lib-del" data-fid="${fid}" onclick="event.stopPropagation();_deleteUploadedFile('${fid}',this)" title="删除" style="position:absolute;top:3px;right:3px;background:rgba(220,38,38,.85);border:none;border-radius:4px;color:#fff;font-size:11px;line-height:1;padding:2px 5px;cursor:pointer;z-index:2;">✕</button>`;
          return `<div class="ref-lib-item" data-id="${fid}" data-url="${url}" data-name="${f.filename||fid}" data-ftype="${isImg?'image':isVid?'video':'file'}"
            style="border:2px solid transparent;border-radius:8px;overflow:hidden;cursor:pointer;aspect-ratio:1;background:var(--bg3,#111);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;padding:8px;position:relative;">
            ${delBtn}${preview}${icon}${statusLabel}
            <div style="font-size:10px;color:var(--t3);text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;width:100%;">${(f.filename||fid||'').slice(-20)}</div>
          </div>`;
        }).join('');
        _attachRefLibClicks(grid);
        // Generate video thumbnails via canvas
        grid.querySelectorAll('.ref-lib-vid-thumb').forEach(imgEl => {
          const videoSrc = imgEl.dataset.src;
          const v = document.createElement('video');
          v.muted = true;
          v.playsInline = true;
          v.preload = 'metadata';
          const tryCapture = () => {
            const c = document.createElement('canvas');
            c.width = 120; c.height = 120;
            try {
              c.getContext('2d').drawImage(v, 0, 0, 120, 120);
              imgEl.src = c.toDataURL('image/jpeg', 0.75);
              imgEl.style.display = '';
              const icon = imgEl.parentNode.querySelector('.fb-icon');
              if (icon) icon.style.display = 'none';
            } catch(e) {}
          };
          v.onseeked = tryCapture;
          v.onloadedmetadata = () => { v.currentTime = 0.5; };
          v.onloadeddata = () => { if (v.currentTime > 0) tryCapture(); };
          v.src = videoSrc;
        });
      })
      .catch(() => { grid.innerHTML = '<div style="color:var(--t3);text-align:center;padding:24px;grid-column:1/-1;">加载失败</div>'; });
  } else {
    // portraits or avatars — call real BytePlus API
    fetch(`/api/assets/byteplus/${src}?page=1&page_size=40`, { headers: { 'Authorization': 'Bearer ' + apiKey() } })
      .then(r => r.json())
      .then(data => {
        const assets = data.data || [];
        if (data.error && !assets.length) {
          grid.innerHTML = `<div style="color:var(--t3);text-align:center;padding:24px;grid-column:1/-1;">暂无资产（${data.error}）</div>`;
          return;
        }
        if (!assets.length) {
          grid.innerHTML = '<div style="color:var(--t3);text-align:center;padding:24px;grid-column:1/-1;">素材库暂无资产</div>';
          return;
        }
        grid.innerHTML = assets.map(a => {
          const thumb = a.url || a.thumbnail_url || '';
          const label = (a.name || a.id || '').slice(-20);
          return `<div class="ref-lib-item" data-id="asset://${a.id}" data-url="${thumb}" data-name="${a.name||a.id}" data-ftype="image"
            style="border:2px solid transparent;border-radius:8px;overflow:hidden;cursor:pointer;aspect-ratio:1;background:var(--bg3,#111);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;padding:6px;">
            ${thumb ? `<img src="${thumb}" style="width:100%;height:80%;object-fit:cover;border-radius:4px;">` : `<div style="font-size:28px;">🧑</div>`}
            <div style="font-size:10px;color:var(--t3);text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;width:100%;">${label}</div>
          </div>`;
        }).join('');
        _attachRefLibClicks(grid);
      })
      .catch(() => { grid.innerHTML = '<div style="color:var(--t3);text-align:center;padding:24px;grid-column:1/-1;">加载失败，请检查网络</div>'; });
  }
}

function _attachRefLibClicks(grid) {
  grid.querySelectorAll('.ref-lib-item').forEach(item => {
    item.addEventListener('click', () => {
      item.classList.toggle('selected');
      item.style.borderColor = item.classList.contains('selected') ? 'var(--accent,#7c3aed)' : 'transparent';
    });
  });
}

window._deleteUploadedFile = async function(fileId, btnEl) {
  if (!confirm('确认删除该文件？')) return;
  if (btnEl) { btnEl.disabled = true; btnEl.textContent = '…'; }
  try {
    const resp = await fetch(`/api/files/${encodeURIComponent(fileId)}`, {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + apiKey() }
    });
    if (resp.ok) {
      // Remove from referenceFiles for all modes and update tags
      ['video', 'image'].forEach(mode => {
        const before = referenceFiles[mode].length;
        referenceFiles[mode] = referenceFiles[mode].filter(f => f.file_id !== fileId);
        if (referenceFiles[mode].length !== before) {
          referenceFiles[mode].forEach((f, i) => { f.index = i + 1; });
          updateReferenceFilesList(mode);
          updateReferenceTags(mode);
        }
      });
      // Remove card from DOM immediately
      const card = btnEl && btnEl.closest('.ref-lib-item');
      if (card) card.remove();
      // If grid is empty after removal, show empty hint
      const grid = document.getElementById('ref-library-grid');
      if (grid && !grid.querySelector('.ref-lib-item')) {
        grid.innerHTML = '<div style="color:var(--t3);text-align:center;padding:24px;grid-column:1/-1;">暂无上传文件</div>';
      }
    } else {
      let msg = '未知错误';
      try { const d = await resp.json(); msg = d.message || d.detail || d.error || msg; } catch(_) {}
      alert('删除失败: ' + msg);
      if (btnEl) { btnEl.disabled = false; btnEl.textContent = '✕'; }
    }
  } catch (e) {
    alert('删除失败: ' + e.message);
    if (btnEl) { btnEl.disabled = false; btnEl.textContent = '✕'; }
  }
};

function updateReferenceFilesList(mode) {
  const listContainer = document.getElementById(`ref-files-${mode}`);
  if (!listContainer) return;
  listContainer.innerHTML = '';
}

window.removeReferenceFile = function(mode, index) {
  referenceFiles[mode].splice(index, 1);
  // Update indices
  referenceFiles[mode].forEach((file, i) => {
    file.index = i + 1;
  });
  updateReferenceFilesList(mode);
  updateReferenceTags(mode);
}

function updateReferenceTags(mode) {
  const tagsContainer = document.getElementById(`ref-tags-${mode}`);
  const textarea = document.getElementById(`prompt-${mode}`);

  if (!tagsContainer) return;

  if (referenceFiles[mode].length === 0) {
    tagsContainer.innerHTML = '';
    return;
  }

  tagsContainer.innerHTML = referenceFiles[mode].map((file, index) => {
    const tag = file.type==="video"?`@video${index+1}`:(file.type==="audio"?`@audio${index+1}`:`@image${index+1}`);
    const thumb = file.thumbUrl
      ? `<img class="ref-tag-thumb" src="${file.thumbUrl}" alt="${tag}">`
      : '';
    return `
      <span class="ref-tag">
        ${thumb}
        ${tag}
        <span class="ref-tag-remove" onclick="removeReferenceTag('${mode}', ${index})">✕</span>
      </span>
    `;
  }).join('');

  if (textarea) {
    // rebuild all tags from current referenceFiles state
    const allTags = referenceFiles[mode].map((f, i) => f.type==="video"?`@video${i+1}`:(f.type==="audio"?`@audio${i+1}`:`@image${i+1}`));
    // remove old @imageN/@videoN tokens from textarea, then prepend fresh ones
    let text = textarea.value.replace(/@(image|video|audio)\d+/g, '').replace(/^\s+/, '');
    const prefix = allTags.join(' ');
    textarea.value = prefix ? prefix + (text ? ' ' + text : '') : text;
  }
}

window.removeReferenceTag = function(mode, index) {
  window.removeReferenceFile(mode, index);
}

function initModelChangeHandlers() {
  // Video mode model select
  const videoModelSelect = document.getElementById('modelSelect-video');
  if (videoModelSelect) {
    videoModelSelect.addEventListener('change', (e) => {
      const selectedModel = e.target.value;
      showReferenceModeSelector('video', selectedModel);
    });
  }
  
  // Drama mode model select
  const dramaModelSelect = document.getElementById('modelSelect-drama');
  if (dramaModelSelect) {
    dramaModelSelect.addEventListener('change', (e) => {
      const selectedModel = e.target.value;
      showReferenceModeSelector('drama', selectedModel);
      updateDramaCostDisplay();
    });
  }
  
  // Image mode model select
  const imageModelSelect = document.getElementById('modelSelect-image');
  if (imageModelSelect) {
    imageModelSelect.addEventListener('change', (e) => {
      const selectedModel = e.target.value;
      // Image mode may have different logic for reference modes
    });
  }
}

function showReferenceModeSelector(mode, model) {
  const refModeSelector = document.getElementById(`ref-mode-${mode}`);
  
  if (!refModeSelector) return;
  
  // Show reference mode selector for certain models
  if (model === 'omni' || model === '') {
    refModeSelector.style.display = 'flex';
  } else {
    refModeSelector.style.display = 'none';
  }
}

function initRefModeChangeHandlers() {
  ['video', 'drama'].forEach(function(mode) {
    var refModeMenu = document.getElementById('refModeMenu-' + mode);
    if (refModeMenu) {
      var menuItems = refModeMenu.querySelectorAll('.dropdown-item');
      menuItems.forEach(function(item) {
        item.addEventListener('click', function() {
          var value = item.getAttribute('data-value');
          updateRefModeHint(mode, value);
          updateRefMaterialOptions(value);
        });
      });
    }
  });
}

function updateRefModeHint(mode, refMode) {
  const hintElement = document.getElementById(`ref-mode-hint-${mode}`);
  if (!hintElement) return;
  
  const hintTextElement = hintElement.querySelector('.hint-text');
  if (!hintTextElement) return;
  
  const hints = {
    'text2vid': t('gen.ref_hint_text2vid') || '当前模式为文生视频，不需要参考图。',
    'first_last_frame': t('gen.ref_hint_first_last_frame') || '当前模式按顺序使用首帧、尾帧参考。',
    'multi_ref': t('gen.ref_hint_multi_ref') || '当前模式最多支持 9 张图片参考。'
  };
  
  hintTextElement.textContent = hints[refMode] || hints['text2vid'];
}

function updateRefMaterialOptions(refMode) {
  const advancedPanel = document.getElementById('advanced-panel-video');
  if (advancedPanel) advancedPanel.style.display = refMode === 'text2vid' ? 'none' : 'block';

  // hide/show the left reference upload panel for both video and drama
  ['video', 'drama'].forEach(function(mode) {
    const uploadZoneEl = document.getElementById('upload-zone-' + mode);
    const leftPanel = uploadZoneEl ? uploadZoneEl.closest('.gen-left-panel') : null;
    if (leftPanel) leftPanel.style.display = refMode === 'text2vid' ? 'none' : '';
  });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  initReferenceUploads();
  
  // Initialize reference mode to text2vid by default
  updateRefMaterialOptions('text2vid');
  updateRefModeHint('video', 'text2vid');
});