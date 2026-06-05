const apiKey = () => localStorage.getItem('sdToken');

function goHome() {
  window.location.href = '/';
}

async function doLogout() {
  if (confirm(t('profile.logout_confirm') || '确定要登出吗？')) {
    localStorage.removeItem('sdToken');
    localStorage.removeItem('sdUser');
    window.location.href = '/';
  }
}

function switchPage(page) {
  document.querySelectorAll('.page-content').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.sidebar-menu a').forEach(a => a.classList.remove('active'));

  document.getElementById('page-' + page).style.display = 'block';
  const link = document.querySelector(`.sidebar-menu a[data-page="${page}"]`);
  if (link) link.classList.add('active');

  const pageTitles = {
    works: { title: t('profile.page.works.title') || '我的创作', desc: t('profile.page.works.desc') || '管理和浏览您所有已生成的影片和图片' },
    subscription: { title: t('profile.page.subscription.title') || '订阅', desc: t('profile.page.subscription.desc') || '管理您的订阅方案和账单信息' },
    credits: { title: t('profile.page.credits.title') || '积分历史', desc: t('profile.page.credits.desc') || '查看所有积分获取和使用记录' },
    orders: { title: t('profile.page.orders.title') || '订单记录', desc: t('profile.page.orders.desc') || '查看所有付款订单的历史记录' },
    profile: { title: t('profile.page.profile.title') || '个人资料', desc: t('profile.page.profile.desc') || '管理您的账户信息和偏好设置' },
    contact: { title: t('profile.page.contact.title') || '提交工单', desc: t('profile.page.contact.desc') || '遇到问题或有建议？提交工单，我们将尽快处理。' },
    dramas: { title: '我的短剧', desc: '浏览和管理您所有已生成的短剧作品' },
  };

  const info = pageTitles[page] || { title: page, desc: '' };
  document.getElementById('pageTitle').textContent = info.title;
  document.getElementById('pageDesc').textContent = info.desc;

  if (page === 'works') loadWorks();
  if (page === 'credits') loadCredits(1);
  if (page === 'orders') loadOrders(1);
  if (page === 'subscription') loadSubscription();
  if (page === 'dramas') loadDramaWorks();
  if (page === 'contact' && window._currentUser) {
    const el = document.getElementById('contactEmail');
    if (el && !el.value) el.value = window._currentUser.email || '';
    loadContactHistory();
  }
  if (typeof applyTranslations === 'function') applyTranslations();
}

async function loadUserData() {
  try {
    const res = await fetch('/api/auth/me', { headers: { 'Authorization': 'Bearer ' + apiKey() } });
    if (!res.ok) { window.location.href = '/'; return; }

    const user = await res.json();
    window._currentUser = user;

    document.getElementById('userName').textContent = user.display_name || user.email.split('@')[0];
    document.getElementById('userEmail').textContent = user.email;

    const initials = (user.display_name || user.email)[0].toUpperCase();
    ['userAvatar', 'profileAvatar'].forEach(id => {
      const el = document.getElementById(id);
      if (user.avatar_url) {
        el.style.backgroundImage = `url(${user.avatar_url})`;
        el.style.backgroundSize = 'cover';
        el.textContent = '';
      } else {
        el.textContent = initials;
      }
    });

    document.getElementById('profileUsername').value = user.display_name || '';
    document.getElementById('profileEmail').value = user.email;

    if (user.points_balance !== undefined) {
      const el = document.getElementById('sidebarPoints');
      if (el) el.textContent = user.points_balance + ' ' + (t('js.points_unit') || '积分');
    }
  } catch (err) {
    window.location.href = '/';
  }
}

// ── Works ──────────────────────────────────────────────────────────────

let _worksTab = 'video';

async function loadWorks() {
  if (_worksTab === 'video') await loadVideoWorks();
  else await loadImageWorks();
}

async function loadVideoWorks() {
  const container = document.getElementById('worksGrid');
  if (!container) return;
  container.innerHTML = '<div style="text-align:center;padding:40px;color:var(--t3)">' + (t('profile.loading') || '加载中...') + '</div>';
  try {
    const headers = { 'Authorization': 'Bearer ' + apiKey() };
    const [taskRes, compRes] = await Promise.all([
      fetch('/api/tasks/?page=1&page_size=100', { headers }),
      fetch('/api/tasks/compositions?page=1&page_size=100', { headers }),
    ]);
    const taskData = await taskRes.json();
    const compData = compRes.ok ? await compRes.json() : { items: [] };

    const videoItems = (taskData.items || []).map(item => ({ ...item, _type: 'video' }));
    const compItems = (compData.items || []).map(c => ({
      id: `comp_${c.id}`,
      _comp_id: c.id,
      _type: 'composition',
      status: c.status,
      prompt: c.prompt,
      video_url: c.final_video_url || c.video_url,
      duration_seconds: c.total_duration,
      ratio: '',
      resolution: '',
      created_at: c.created_at,
      completed_segments: c.completed_segments,
      total_segments: c.total_segments,
      progress: c.progress,
      error_msg: c.error_msg,
    }));

    const all = [...videoItems, ...compItems].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    if (all.length === 0) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📭</div>
        <div class="empty-state-title">${t('profile.empty.works.title') || '没有找到影片'}</div>
        <div class="empty-state-desc">${t('profile.empty.works.desc') || '您尚未生成任何影片，开始创建您的第一部影片吧！'}</div></div>`;
      return;
    }
    container.style.display = 'grid';
    container.innerHTML = all.map(item => renderTaskCard(item, false)).join('');
  } catch (e) {
    container.innerHTML = '<div style="text-align:center;padding:40px;color:var(--t3)">' + (t('profile.load_fail') || '加载失败') + '</div>';
  }
}

async function loadImageWorks() {
  const container = document.getElementById('worksGrid');
  if (!container) return;
  container.innerHTML = '<div style="text-align:center;padding:40px;color:var(--t3)">' + (t('profile.loading') || '加载中...') + '</div>';
  try {
    const res = await fetch('/api/images?page=1&page_size=100', { headers: { 'Authorization': 'Bearer ' + apiKey() } });
    const data = await res.json();
    if (!data.items || data.items.length === 0) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">🖼️</div>
        <div class="empty-state-title">${t('profile.empty.image_title') || '暂无图片记录'}</div>
        <div class="empty-state-desc">${t('profile.empty.image_desc') || '图片生成记录将在此显示'}</div></div>`;
      return;
    }
    container.style.display = 'grid';
    container.innerHTML = data.items.map(item => renderTaskCard(item, true)).join('');
  } catch (e) {
    container.innerHTML = '<div style="text-align:center;padding:40px;color:var(--t3)">' + (t('profile.load_fail') || '加载失败') + '</div>';
  }
}

function renderTaskCard(task, isImage) {
  const statusColors = { success: '#4ade80', completed: '#4ade80', failed: '#f87171', processing: '#fbbf24', pending: '#94a3b8', cancelled: '#94a3b8' };
  const statusLabels = {
    success: t('js.status_success') || '已完成',
    completed: t('js.status_success') || '已完成',
    failed: t('js.status_failed') || '失败',
    processing: t('js.status_processing') || '生成中',
    pending: t('js.status_pending') || '等待中',
    cancelled: t('js.status_cancelled') || '已取消',
  };
  const status = (task.status || '').toLowerCase();
  const color = statusColors[status] || '#94a3b8';
  const label = statusLabels[status] || task.status;
  const mediaUrl = isImage ? task.image_url : task.video_url;
  const isComp = task._type === 'composition';
  const tid = String(task.id);

  let progressBar = '';
  if (status === 'processing' || status === 'pending') {
    const pct = task.progress || 0;
    const segInfo = isComp && task.total_segments
      ? (t('js.segment_progress') || '片段 {done}/{total} · {pct}%').replace('{done}', task.completed_segments || 0).replace('{total}', task.total_segments).replace('{pct}', pct)
      : `${pct}%`;
    progressBar = `<div style="margin-top:6px;">
      <div style="font-size:11px;color:var(--t3);margin-bottom:3px;">${segInfo}</div>
      <div style="height:4px;background:var(--bg4);border-radius:2px;">
        <div style="height:100%;width:${pct}%;background:var(--primary);border-radius:2px;transition:width .3s;"></div>
      </div>
    </div>`;
  }

  let preview;
  if (isImage) {
    preview = mediaUrl
      ? `<img src="${mediaUrl}" style="width:100%;height:140px;object-fit:cover;border-radius:8px;" onerror="this.outerHTML='<div style=\\'width:100%;height:140px;background:var(--bg3);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:32px;\\'>🖼️</div>'">`
      : `<div style="width:100%;height:140px;background:var(--bg3);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:32px;">${status === 'processing' ? '⏳' : status === 'failed' ? '❌' : '🖼️'}</div>`;
  } else {
    preview = mediaUrl
      ? `<video src="${mediaUrl}" style="width:100%;height:140px;object-fit:cover;border-radius:8px;" preload="none" controls onerror="this.outerHTML='<div style=\\'width:100%;height:140px;background:var(--bg3);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:32px;\\'>🎬</div>'"></video>`
      : `<div style="width:100%;height:140px;background:var(--bg3);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:32px;">${status === 'processing' || status === 'pending' ? '⏳' : status === 'failed' ? '❌' : '🎬'}</div>`;
  }
  const promptText = (task.prompt || (t('js.no_description') || '无描述')).replace(/"/g, '&quot;');
  const typeLabel = isImage ? (t('js.type_image') || '🖼️ 图片') : isComp ? (t('js.type_long_video') || '🎬 长视频') : (t('js.type_video') || '🎬 视频');
  const durationText = task.duration_seconds ? task.duration_seconds + 's' : '';
  return `<div style="background:var(--bg2);border-radius:12px;padding:16px;border:1px solid var(--bg4);">
    ${preview}
    ${progressBar}
    <div style="margin-top:10px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <span style="font-size:11px;color:var(--t3);">${typeLabel}</span>
        <span style="font-size:12px;color:${color};font-weight:600;">${label}</span>
      </div>
      <div style="font-size:12px;color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${promptText}">${task.prompt || (t('js.no_description') || '无描述')}</div>
      <div style="font-size:11px;color:var(--t3);margin-top:4px;">${task.resolution || ''} ${durationText} ${task.ratio || ''}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:8px;">
        ${mediaUrl ? `<a href="${mediaUrl}" target="_blank" download style="font-size:12px;color:var(--primary);text-decoration:none;">${t('js.download') || '↓ 下载'}</a>` : ''}
        <button onclick="deleteWork('${tid}',${isImage})" style="font-size:12px;color:#f87171;background:none;border:none;cursor:pointer;padding:0;">${t('js.delete') || '🗑 删除'}</button>
      </div>
    </div>
  </div>`;
}

async function deleteWork(taskId, isImage) {
  if (!confirm(t('profile.delete_confirm') || '确定删除此作品？此操作不可撤销。')) return;
  let endpoint;
  if (String(taskId).startsWith('comp_')) {
    endpoint = `/api/tasks/compositions/${String(taskId).replace('comp_', '')}`;
  } else {
    endpoint = isImage ? `/api/images/${taskId}` : `/api/tasks/${taskId}`;
  }
  try {
    const res = await fetch(endpoint, {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + apiKey() }
    });
    if (res.ok) {
      loadWorks();
    } else {
      alert(t('profile.delete_fail') || '删除失败');
    }
  } catch (e) {
    alert(t('profile.delete_fail') || '删除失败');
  }
}

// ── Credits ────────────────────────────────────────────────────────────

let _creditsPage = 1;
const _creditsPageSize = 20;

async function loadCredits(page) {
  _creditsPage = page;
  const tbody = document.getElementById('creditsTbody');
  const pageInfo = document.getElementById('creditsPageInfo');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--t3)">' + (t('profile.loading') || '加载中...') + '</td></tr>';
  try {
    const res = await fetch(`/api/points/history?page=${page}&page_size=${_creditsPageSize}`, {
      headers: { 'Authorization': 'Bearer ' + apiKey() }
    });
    const data = await res.json();
    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--t3)">' + (t('profile.credits_empty') || '未找到积分记录') + '</td></tr>';
    } else {
      const typeLabels = {
        consume: t('js.type_consume') || '消耗',
        earn: t('js.type_earn') || '获取',
        subscription: t('js.type_subscription') || '订阅',
        admin_adjust: t('js.type_admin_adjust') || '管理员调整',
      };
      tbody.innerHTML = data.items.map(r => {
        const sign = r.points > 0 ? '+' : '';
        const color = r.points > 0 ? '#4ade80' : '#f87171';
        return `<tr>
          <td>${r.created_at ? r.created_at.replace('T', ' ').slice(0, 16) : '-'}</td>
          <td>${typeLabels[r.type] || r.type}</td>
          <td style="color:var(--t2);">${r.description || '-'}</td>
          <td style="color:${color};font-weight:600;">${sign}${r.points}</td>
        </tr>`;
      }).join('');
    }
    const total = data.total || 0;
    const totalPages = Math.ceil(total / _creditsPageSize) || 1;
    if (pageInfo) pageInfo.textContent = (t('profile.credits_records') || '共 {total} 条记录，第 {page}/{totalPages} 页').replace('{total}', total).replace('{page}', page).replace('{totalPages}', totalPages);
    document.getElementById('creditsPrevBtn').disabled = page <= 1;
    document.getElementById('creditsNextBtn').disabled = page >= totalPages;
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--t3)">' + (t('profile.load_fail') || '加载失败') + '</td></tr>';
  }
}

// ── Orders ─────────────────────────────────────────────────────────────

async function loadOrders(page) {
  const tbody = document.getElementById('ordersTbody');
  const pageInfo = document.getElementById('ordersPageInfo');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--t3)">' + (t('profile.loading') || '加载中...') + '</td></tr>';
  try {
    const res = await fetch('/api/subscriptions/my', { headers: { 'Authorization': 'Bearer ' + apiKey() } });
    const data = await res.json();
    const sub = data.subscription;
    if (!sub) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--t3)">' + (t('profile.orders_empty') || '暂无订单记录') + '</td></tr>';
      if (pageInfo) pageInfo.textContent = t('profile.orders_count') || '0 笔订单';
      return;
    }
    const statusMap = {
      active: t('js.sub_active') || '有效',
      expired: t('js.sub_expired') || '已过期',
      cancelled: t('js.sub_cancelled') || '已取消',
      pending: t('js.sub_pending') || '待处理',
    };
    const cycleMap = {
      monthly: t('js.billing_monthly') || '月付',
      annual: t('js.billing_annual') || '年付',
    };
    tbody.innerHTML = `<tr>
      <td>${sub.created_at ? sub.created_at.replace('T', ' ').slice(0, 10) : '-'}</td>
      <td>${sub.plan_name || sub.plan_id || '-'}</td>
      <td>${cycleMap[sub.billing_cycle] || sub.billing_cycle || (t('js.billing_monthly') || '月付')}</td>
      <td><span style="color:${sub.status === 'active' ? '#4ade80' : '#f87171'}">${statusMap[sub.status] || sub.status}</span></td>
      <td>${sub.price_cents ? '$' + (sub.price_cents / 100).toFixed(2) : '-'}</td>
    </tr>`;
    if (pageInfo) pageInfo.textContent = t('profile.orders_one') || '1 笔订单';
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--t3)">' + (t('profile.load_fail') || '加载失败') + '</td></tr>';
  }
}

// ── Subscription ───────────────────────────────────────────────────────

async function loadSubscription() {
  const container = document.getElementById('subscriptionContent');
  if (!container) return;
  try {
    const [subRes, plansRes] = await Promise.all([
      fetch('/api/subscriptions/my', { headers: { 'Authorization': 'Bearer ' + apiKey() } }),
      fetch('/api/subscriptions/plans'),
    ]);
    const subData = await subRes.json();
    const plans = await plansRes.json();
    const sub = subData.subscription;
    const user = window._currentUser || {};

    let currentHtml = '';
    if (sub && sub.status === 'active') {
      currentHtml = `<div style="background:var(--bg2);border-radius:12px;padding:20px;border:1px solid var(--bg4);margin-bottom:24px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-size:16px;font-weight:700;color:var(--t1);">${t('js.current_plan') || '当前方案'}：${sub.plan_name || (t('js.unknown') || '未知')}</div>
            <div style="font-size:13px;color:var(--t3);margin-top:4px;">${t('js.expires_at') || '有效期至'}：${sub.expires_at ? sub.expires_at.slice(0, 10) : '-'}</div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:24px;font-weight:700;color:var(--primary);">${user.points_balance || 0}</div>
            <div style="font-size:12px;color:var(--t3);">${t('js.remaining_points') || '剩余积分'}</div>
          </div>
        </div>
      </div>`;
    } else {
      currentHtml = `<div style="background:var(--bg2);border-radius:12px;padding:20px;border:1px solid var(--bg4);margin-bottom:24px;text-align:center;">
        <div style="font-size:32px;margin-bottom:8px;">👑</div>
        <div style="font-size:15px;font-weight:600;color:var(--t1);margin-bottom:4px;">${t('profile.subscription.no_plan') || '您目前没有订阅任何方案'}</div>
        <div style="font-size:13px;color:var(--t3);">${t('js.upgrade_hint') || '立即升级以获取更多积分和功能'}</div>
      </div>`;
    }

    const plansHtml = plans.filter(p => p.price_cents > 0).map(p => {
      const monthlyPrice = (p.price_cents / 100).toFixed(0);
      const annualTotalCents = p.annual_discount > 0
        ? Math.round(p.price_cents * 12 * (100 - p.annual_discount) / 100)
        : null;
      const annualMonthly = annualTotalCents ? (annualTotalCents / 100 / 12).toFixed(0) : null;
      const isCurrent = sub && sub.plan_id == p.id;
      return `<div style="background:var(--bg2);border-radius:12px;padding:20px;border:2px solid ${isCurrent ? 'var(--primary)' : 'var(--bg4)'};flex:1;min-width:200px;max-width:280px;">
        <div style="font-size:15px;font-weight:700;color:var(--t1);margin-bottom:8px;">${p.name}</div>
        <div style="font-size:28px;font-weight:700;color:var(--primary);">$${monthlyPrice}<span style="font-size:13px;color:var(--t3);">/mo</span></div>
        ${annualMonthly ? `<div style="font-size:12px;color:#4ade80;margin-top:2px;">Annual $${annualMonthly}/mo（Save ${p.annual_discount}%）</div>` : ''}
        <div style="font-size:13px;color:var(--t2);margin:12px 0;">${p.points_per_month} ${t('profile.subscription.points_per_month') || '积分/月'}</div>
        <div style="font-size:12px;color:var(--t3);margin-bottom:4px;">${t('profile.subscription.max_resolution') || '最高分辨率'}：${p.max_resolution}</div>
        <div style="font-size:12px;color:var(--t3);margin-bottom:16px;">${t('profile.subscription.concurrent_tasks') || '并发任务'}：${p.max_concurrent_tasks}</div>
        ${isCurrent
          ? `<button class="btn-secondary" style="width:100%;font-size:13px;" disabled>${t('profile.subscription.current_plan_btn') || '当前方案'}</button>`
          : `<button class="btn-primary" style="width:100%;font-size:13px;" onclick="subscribePlan(${p.id},'monthly')">${t('profile.subscription.monthly_subscribe') || '月付订阅'}</button>
             ${annualMonthly ? `<button class="btn-secondary" style="width:100%;font-size:13px;margin-top:8px;" onclick="subscribePlan(${p.id},'annual')">${t('profile.subscription.annual_subscribe') || '年付订阅'}</button>` : ''}`
        }
      </div>`;
    }).join('');

    container.innerHTML = currentHtml + `<h3 style="font-size:15px;font-weight:600;margin-bottom:16px;">${t('profile.choose_plan') || '选择方案'}</h3>
      <div style="display:flex;gap:16px;flex-wrap:wrap;">${plansHtml}</div>`;
  } catch (e) {
    if (container) container.innerHTML = '<div style="color:var(--t3)">' + (t('profile.load_fail') || '加载失败') + '</div>';
  }
}

async function subscribePlan(planId, billingCycle) {
  openPaymentModal('subscription', { plan_id: planId, billing_cycle: billingCycle });
}

// ── Profile ────────────────────────────────────────────────────────────

function uploadAvatar() {
  document.getElementById('avatarInput').click();
}

async function saveProfile() {
  const username = document.getElementById('profileUsername').value.trim();
  if (!username) { alert(t('profile.enter_username') || '请输入用户名'); return; }

  const oldPw = document.getElementById('oldPassword').value;
  const newPw = document.getElementById('newPassword').value;
  const confirmPw = document.getElementById('confirmPassword').value;

  try {
    const profileRes = await fetch('/api/auth/profile', {
      method: 'PUT',
      headers: { 'Authorization': 'Bearer ' + apiKey(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: username }),
    });
    if (!profileRes.ok) {
      const err = await profileRes.json();
      alert((t('profile.update_fail') || '更新失败') + '：' + (err.detail || (t('js.unknown_error') || '未知错误')));
      return;
    }

    if (newPw) {
      if (newPw !== confirmPw) { alert(t('profile.pw_mismatch') || '两次密码不一致'); return; }
      if (newPw.length < 6) { alert(t('profile.pw_too_short') || '新密码至少6位'); return; }
      const pwRes = await fetch('/api/auth/password', {
        method: 'PUT',
        headers: { 'Authorization': 'Bearer ' + apiKey(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      });
      if (!pwRes.ok) {
        const err = await pwRes.json();
        alert((t('profile.pw_update_fail') || '密码修改失败') + '：' + (err.detail || (t('js.unknown_error') || '未知错误')));
        return;
      }
      document.getElementById('oldPassword').value = '';
      document.getElementById('newPassword').value = '';
      document.getElementById('confirmPassword').value = '';
    }

    document.getElementById('userName').textContent = username;
    document.getElementById('userAvatar').textContent = username[0].toUpperCase();
    document.getElementById('profileAvatar').textContent = username[0].toUpperCase();
    alert(t('profile.profile_success') || '资料更新成功');
  } catch (e) {
    alert(t('profile.save_fail') || '保存失败');
  }
}

function createNewWork() {
  window.location.href = '/';
}

function initProfile() {
  document.getElementById('avatarInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('avatar', file);
    try {
      const res = await fetch('/api/auth/profile/avatar', {
        method: 'PUT',
        headers: { 'Authorization': 'Bearer ' + apiKey() },
        body: formData,
      });
      if (res.ok) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          ['userAvatar', 'profileAvatar'].forEach(id => {
            const el = document.getElementById(id);
            el.style.backgroundImage = `url(${ev.target.result})`;
            el.style.backgroundSize = 'cover';
            el.textContent = '';
          });
        };
        reader.readAsDataURL(file);
        alert(t('profile.avatar_success') || '头像更新成功');
      } else {
        alert(t('profile.avatar_fail') || '头像更新失败');
      }
    } catch (err) {
      alert(t('profile.avatar_fail') || '头像更新失败');
    }
  });

  document.querySelectorAll('.sidebar-menu a').forEach(link => {
    link.addEventListener('click', (e) => {
      if (link.classList.contains('logout')) return;
      e.preventDefault();
      switchPage(link.dataset.page);
    });
  });

  // Works tab switching
  document.querySelectorAll('.works-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.works-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      _worksTab = tab.dataset.tab;
      loadWorks();
    });
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  if (typeof initI18n === 'function') {
    await initI18n();
    if (typeof applyTranslations === 'function') applyTranslations();
    if (typeof setupLanguageChangeListener === 'function') setupLanguageChangeListener();
    if (typeof setupLangMenuListeners === 'function') setupLangMenuListeners();
  }

  initProfile();
  await loadUserData();
  loadTelegramConfig();

  const activeLink = document.querySelector('.sidebar-menu a.active');
  if (activeLink) switchPage(activeLink.dataset.page);
});

// ── USDT 支付弹窗 ─────────────────────────────────────────────────────

let _cachedPackages = null;

async function _getPointsPackages() {
  if (_cachedPackages) return _cachedPackages;
  try {
    const res = await fetch('/api/payments/packages');
    const data = await res.json();
    _cachedPackages = data.packages || [];
  } catch (e) {
    _cachedPackages = [];
  }
  return _cachedPackages;
}

let _paymentModal = null;
let _paymentOrderNo = null;
let _paymentPollTimer = null;
let _countdownTimer = null;

function _ensurePaymentModal() {
  if (_paymentModal) return _paymentModal;
  const el = document.createElement('div');
  el.id = 'paymentModal';
  el.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;align-items:center;justify-content:center;';
  el.innerHTML = `
    <div style="background:var(--bg2,#1a1a2e);border-radius:16px;padding:28px;max-width:420px;width:90%;border:1px solid var(--bg4,#333);position:relative;">
      <button onclick="closePaymentModal()" style="position:absolute;top:12px;right:16px;background:none;border:none;color:var(--t2,#aaa);font-size:20px;cursor:pointer;">×</button>
      <div style="font-size:18px;font-weight:700;margin-bottom:4px;" id="pmTitle">USDT 支付</div>
      <div style="font-size:13px;color:var(--t3,#888);margin-bottom:20px;" id="pmSubtitle">请在30分钟内完成转账</div>

      <div id="pmPackages" style="display:none;margin-bottom:16px;">
        <div style="font-size:13px;color:var(--t3);margin-bottom:8px;" id="pmPackagesLabel">${t('js.choose_topup') || '选择充值套餐'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;" id="pmPackageGrid"></div>
      </div>

      <!-- 金额 -->
      <div style="text-align:center;margin:16px 0;">
        <div style="font-size:13px;color:var(--t3);">需转账金额</div>
        <div style="font-size:32px;font-weight:700;color:#fbbf24;" id="pmAmount">-- USDT</div>
        <div style="font-size:12px;color:var(--t3);">TRC20 网络</div>
      </div>

      <!-- 地址 -->
      <div style="background:var(--bg3,#111);border-radius:8px;padding:12px;margin-bottom:12px;">
        <div style="font-size:11px;color:var(--t3);margin-bottom:4px;">收款地址（TRC20）</div>
        <div style="display:flex;align-items:center;gap:8px;">
          <div style="font-size:12px;font-family:monospace;word-break:break-all;flex:1;color:var(--t1);" id="pmAddress">-</div>
          <button onclick="copyPaymentAddress()" style="background:var(--bg4);border:none;color:var(--t2);padding:4px 8px;border-radius:6px;cursor:pointer;font-size:12px;white-space:nowrap;">${t('profile.payment.copy_address') || '复制'}</button>
        </div>
      </div>

      <!-- 二维码 -->
      <div style="text-align:center;margin-bottom:12px;">
        <div id="pmQrDiv" style="background:#fff;padding:6px;border-radius:8px;display:inline-block;"></div>
      </div>

      <!-- 状态 -->
      <div id="pmStatus" style="text-align:center;font-size:13px;color:var(--t3);margin-bottom:12px;">${t('profile.payment.waiting') || '等待转账...'}</div>
      <div id="pmTimer" style="text-align:center;font-size:12px;color:var(--t3);margin-bottom:12px;"></div>

      <div id="pmSuccess" style="display:none;text-align:center;padding:16px;">
        <div style="font-size:32px;margin-bottom:8px;">✅</div>
        <div style="font-size:16px;font-weight:600;color:#4ade80;">${t('js.payment_success') || '支付成功！'}</div>
        <div style="font-size:13px;color:var(--t3);margin-top:4px;">${t('js.payment_success_desc') || '积分/订阅已到账'}</div>
        <button onclick="closePaymentModal()" style="margin-top:16px;padding:8px 24px;background:var(--primary,#7c3aed);border:none;border-radius:8px;color:#fff;cursor:pointer;font-size:14px;">${t('js.confirm') || '确定'}</button>
      </div>

      <div style="font-size:11px;color:var(--t3);text-align:center;margin-top:4px;">⚠️ 请转账精确金额，多付/少付无法自动识别</div>
    </div>`;
  document.body.appendChild(el);
  _paymentModal = el;
  return el;
}

async function openPaymentModal(paymentType, opts = {}) {
  const modal = _ensurePaymentModal();

  if (paymentType === 'points') {
    document.getElementById('pmTitle').textContent = t('profile.credits_topup') || '充值积分';
    document.getElementById('pmPackages').style.display = 'block';
    const grid = document.getElementById('pmPackageGrid');
    const packages = await _getPointsPackages();
    grid.innerHTML = packages.map(p => `
      <button onclick="selectPointsPackage('${p.key}')" id="pkg-${p.key}"
        style="padding:10px;background:var(--bg3);border:1px solid var(--bg4);border-radius:8px;color:var(--t1);cursor:pointer;text-align:center;">
        <div style="font-weight:600;">${p.points.toLocaleString()} ${t('js.points_unit') || '积分'}</div>
        <div style="font-size:12px;color:var(--t3);">$${(p.price_cents / 100).toFixed(0)}</div>
      </button>`).join('');
    if (opts.package_key) {
      await selectPointsPackage(opts.package_key);
      return;
    }
  } else {
    document.getElementById('pmTitle').textContent = t('profile.buy_plan') || '购买套餐';
    document.getElementById('pmPackages').style.display = 'none';
  }

  document.getElementById('pmAmount').textContent = t('js.generating') || '生成中...';
  document.getElementById('pmAddress').textContent = '-';
  document.getElementById('pmStatus').textContent = t('profile.payment.generating') || '生成订单中...';
  document.getElementById('pmSuccess').style.display = 'none';
  modal.style.display = 'flex';

  if (paymentType === 'subscription') {
    await _createOrder({ payment_type: 'subscription', plan_id: opts.plan_id, billing_cycle: opts.billing_cycle });
  }
}

let _selectedPkg = null;

async function selectPointsPackage(key) {
  _selectedPkg = key;
  document.querySelectorAll('#pmPackageGrid button').forEach(b => {
    b.style.borderColor = b.id === 'pkg-' + key ? 'var(--primary,#7c3aed)' : 'var(--bg4)';
  });
  await _createOrder({ payment_type: 'points', points_package: key });
}

async function _createOrder(body) {
  _clearPollTimer();
  try {
    const res = await fetch('/api/payments/create', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + apiKey(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById('pmStatus').textContent = (t('profile.payment.create_fail') || '创建失败') + '：' + (data.detail || (t('js.unknown_error') || '未知错误'));
      document.getElementById('pmAmount').textContent = '--';
      return;
    }
    _paymentOrderNo = data.order_no;
    document.getElementById('pmAmount').textContent = data.amount_usdt + ' USDT';
    document.getElementById('pmAddress').textContent = data.receive_address;
    document.getElementById('pmStatus').textContent = t('profile.payment.waiting') || '等待转账...';

    _drawQr(data.qr_data || data.receive_address);
    _startCountdown(new Date(data.expires_at));
    _startPollStatus();
  } catch (e) {
    document.getElementById('pmStatus').textContent = t('profile.payment.net_error') || '网络错误，请重试';
  }
}

function _drawQr(text) {
  const el = document.getElementById('pmQrDiv');
  if (!el) return;
  el.innerHTML = '';
  new QRCode(el, { text, width: 160, height: 160, correctLevel: QRCode.CorrectLevel.M });
}

function _startCountdown(expiresAt) {
  const timerEl = document.getElementById('pmTimer');
  const tick = () => {
    const left = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
    const m = String(Math.floor(left / 60)).padStart(2, '0');
    const s = String(left % 60).padStart(2, '0');
    if (timerEl) timerEl.textContent = `${t('profile.payment.remaining') || '剩余时间'}：${m}:${s}`;
    if (left > 0) _countdownTimer = setTimeout(tick, 1000);
  };
  tick();
}

function _startPollStatus() {
  if (!_paymentOrderNo) return;
  _paymentPollTimer = setInterval(async () => {
    try {
      const res = await fetch('/api/payments/status/' + _paymentOrderNo, {
        headers: { 'Authorization': 'Bearer ' + apiKey() },
      });
      const data = await res.json();
      if (data.status === 'completed') {
        _clearPollTimer();
        document.getElementById('pmStatus').style.display = 'none';
        document.getElementById('pmTimer').style.display = 'none';
        document.getElementById('pmSuccess').style.display = 'block';
        await loadUserData();
        if (typeof loadSubscription === 'function') loadSubscription();
      } else if (data.status === 'expired' || data.status === 'cancelled') {
        _clearPollTimer();
        document.getElementById('pmStatus').textContent = (t('profile.payment.order_status') || '订单已') + (data.status === 'expired' ? (t('profile.payment.expired') || '过期') : (t('profile.payment.cancelled') || '取消'));
      }
    } catch (e) {}
  }, 8000);
}

function _clearPollTimer() {
  if (_paymentPollTimer) { clearInterval(_paymentPollTimer); _paymentPollTimer = null; }
  if (_countdownTimer) { clearTimeout(_countdownTimer); _countdownTimer = null; }
}

function closePaymentModal() {
  _clearPollTimer();
  if (_paymentModal) _paymentModal.style.display = 'none';
}

function copyPaymentAddress() {
  const addr = document.getElementById('pmAddress').textContent;
  navigator.clipboard.writeText(addr).then(() => alert(t('profile.address_copied') || '地址已复制')).catch(() => {});
}

// 积分充值入口（供其他页面调用）
function openTopupModal(packageKey) {
  openPaymentModal('points', packageKey ? { package_key: packageKey } : {});
}

// ── Contact ─────────────────────────────────────────────────────────────

let _contactAttachments = []; // [{url, filename, mime_type}]

function handleContactDrop(e) {
  e.preventDefault();
  document.getElementById('contactDropzone').style.borderColor = 'var(--bg4)';
  handleContactFileSelect(e.dataTransfer.files);
}

async function handleContactFileSelect(files) {
  for (const file of Array.from(files)) {
    await uploadContactAttachment(file);
  }
}

async function uploadContactAttachment(file) {
  const listEl = document.getElementById('contactAttachList');
  const itemId = 'ca-' + Date.now() + Math.random().toString(36).slice(2);
  const isImage = file.type.startsWith('image/');
  const placeholder = document.createElement('div');
  placeholder.id = itemId;
  placeholder.style.cssText = 'position:relative;display:inline-flex;align-items:center;gap:6px;background:var(--bg3);border-radius:8px;padding:6px 10px;font-size:12px;color:var(--t2);';
  placeholder.innerHTML = `<span>⏳</span><span>${file.name}</span>`;
  listEl.appendChild(placeholder);

  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch('/api/contact/upload', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + apiKey() },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.detail || '上传失败');
    const att = { url: data.url, filename: data.filename, mime_type: data.mime_type };
    _contactAttachments.push(att);
    const el = document.getElementById(itemId);
    if (el) {
      const preview = isImage ? `<img src="${data.url}" style="width:48px;height:48px;object-fit:cover;border-radius:6px;">` : `<span style="font-size:20px;">${data.mime_type.startsWith('video') ? '🎬' : '📄'}</span>`;
      el.innerHTML = `${preview}<span style="max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${file.name}</span>
        <button onclick="removeContactAttachment(this,'${data.url}')" style="background:none;border:none;color:var(--t3);cursor:pointer;font-size:14px;padding:0 2px;" title="移除">✕</button>`;
    }
  } catch (err) {
    const el = document.getElementById(itemId);
    if (el) { el.style.borderColor = 'var(--red)'; el.querySelector('span').textContent = '上传失败: ' + err.message; }
  }
}

function removeContactAttachment(btn, url) {
  _contactAttachments = _contactAttachments.filter(a => a.url !== url);
  btn.closest('div').remove();
}

async function submitContact() {
  const email = document.getElementById('contactEmail').value.trim();
  const subject = document.getElementById('contactSubject').value.trim();
  const message = document.getElementById('contactMessage').value.trim();
  if (!email || !subject || !message) { alert(t('profile.contact.fill_all') || '请填写所有字段'); return; }
  const btn = document.getElementById('contactSubmitBtn');
  btn.disabled = true;
  btn.textContent = t('profile.contact.sending') || '发送中...';
  try {
    const res = await fetch('/api/contact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + apiKey() },
      body: JSON.stringify({ email, subject, message, attachments: _contactAttachments }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      alert(t('profile.contact.sent') || '工单已提交，我们会尽快处理！');
      document.getElementById('contactSubject').value = '';
      document.getElementById('contactMessage').value = '';
      document.getElementById('contactAttachList').innerHTML = '';
      _contactAttachments = [];
      loadContactHistory();
    } else {
      alert((t('profile.contact.send_fail') || '发送失败') + ': ' + (data.detail || data.message || (t('js.unknown_error') || '未知错误')));
    }
  } catch (e) {
    alert((t('profile.contact.send_fail') || '发送失败') + ': ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = t('profile.contact.submit') || '发送消息';
  }
}

function _escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _renderContactAtts(attachments) {
  return (attachments || []).map(a => {
    if (a.mime_type && a.mime_type.startsWith('image/'))
      return `<a href="${a.url}" target="_blank"><img src="${a.url}" style="max-width:80px;max-height:60px;border-radius:6px;object-fit:cover;"></a>`;
    return `<a href="${a.url}" target="_blank" style="font-size:12px;color:var(--accent);">${a.filename || '附件'}</a>`;
  }).join('');
}

async function loadContactHistory() {
  const el = document.getElementById('contactHistory');
  if (!el) return;
  try {
    const res = await fetch('/api/contact/my', { headers: { 'Authorization': 'Bearer ' + apiKey() } });
    const data = await res.json();
    const items = data.items || [];
    if (!items.length) { el.innerHTML = '<div style="color:var(--t3);">' + (t('js.no_tickets') || '暂无工单记录') + '</div>'; return; }
    el.innerHTML = items.map(m => {
      const isClosed = m.status === 'closed';
      const atts = _renderContactAtts(m.attachments);

      // 渲染对话气泡
      let threadHtml = `<div style="display:flex;flex-direction:column;align-items:flex-start;gap:2px;margin-top:10px;">
        <div style="font-size:11px;color:var(--t3);">${t('js.me_sender') || '我'} · ${(m.created_at||'').replace('T',' ').slice(0,16)}</div>
        <div style="max-width:90%;background:var(--bg3);border-radius:0 10px 10px 10px;padding:8px 12px;font-size:13px;color:var(--t2);white-space:pre-wrap;line-height:1.6;">${_escHtml(m.message)}</div>
        ${atts ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">${atts}</div>` : ''}
      </div>`;

      for (const r of (m.replies || [])) {
        const isAdmin = r.sender === 'admin';
        const rAtts = _renderContactAtts(r.attachments);
        threadHtml += `<div style="display:flex;flex-direction:column;align-items:${isAdmin ? 'flex-end' : 'flex-start'};gap:2px;margin-top:8px;">
          <div style="font-size:11px;color:var(--t3);margin-${isAdmin?'right':'left'}:2px;">${isAdmin ? (t('js.admin_sender') || '管理员') : (t('js.me_sender') || '我')} · ${(r.created_at||'').replace('T',' ').slice(0,16)}</div>
          <div style="max-width:90%;background:${isAdmin ? 'rgba(99,102,241,.18)' : 'var(--bg3)'};border-radius:${isAdmin ? '10px 0 10px 10px' : '0 10px 10px 10px'};padding:8px 12px;font-size:13px;color:var(--t1);white-space:pre-wrap;line-height:1.6;">${_escHtml(r.content)}</div>
          ${rAtts ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">${rAtts}</div>` : ''}
        </div>`;
      }

      const replyInput = isClosed ? `<div style="font-size:12px;color:var(--t3);margin-top:10px;text-align:center;">${t('js.ticket_closed') || '工单已关闭'}</div>` : `
        <div style="margin-top:12px;border-top:1px solid var(--bg4);padding-top:10px;">
          <textarea id="replyInput_${m.id}" rows="2" style="width:100%;box-sizing:border-box;padding:8px;background:var(--bg3);border:1px solid var(--bg4);border-radius:8px;color:var(--t1);font-size:13px;resize:none;" placeholder="${t('js.ticket_reply_placeholder') || '继续回复...'}"></textarea>
          <div style="text-align:right;margin-top:6px;">
            <button class="btn-secondary" style="font-size:12px;padding:5px 14px;" onclick="userReplyTicket(${m.id})">${t('js.send') || '发送'}</button>
          </div>
        </div>`;

      const statusBadge = isClosed
        ? `<span style="font-size:11px;padding:1px 8px;background:rgba(107,114,128,.2);color:var(--t3);border-radius:20px;">${t('js.ticket_closed_label') || '已关闭'}</span>`
        : `<span style="font-size:11px;padding:1px 8px;background:rgba(74,222,128,.15);color:#4ade80;border-radius:20px;">${t('js.ticket_active') || '进行中'}</span>`;

      return `<div style="background:var(--bg2);border-radius:10px;padding:14px;margin-bottom:12px;border:1px solid var(--bg4);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="font-size:14px;font-weight:600;color:var(--t1);">${_escHtml(m.subject)}</span>
          <div style="display:flex;align-items:center;gap:8px;">
            ${statusBadge}
            <span style="font-size:11px;color:var(--t3);">${(m.created_at||'').replace('T',' ').slice(0,16)}</span>
          </div>
        </div>
        ${threadHtml}
        ${replyInput}
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = '<div style="color:var(--t3);">' + (t('profile.load_fail') || '加载失败') + '</div>'; }
}

async function userReplyTicket(ticketId) {
  const input = document.getElementById(`replyInput_${ticketId}`);
  if (!input) return;
  const content = input.value.trim();
  if (!content) { alert(t('js.reply_empty') || '请输入回复内容'); return; }
  input.disabled = true;
  try {
    const res = await fetch(`/api/contact/${ticketId}/reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + apiKey() },
      body: JSON.stringify({ content }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      loadContactHistory();
    } else {
      alert((t('profile.contact.send_fail') || '发送失败') + '：' + (data.detail || ''));
      input.disabled = false;
    }
  } catch (e) { alert(t('js.request_fail') || '请求失败'); input.disabled = false; }
}


async function loadDramaWorks() {
  const grid = document.getElementById('dramasGrid');
  grid.innerHTML = '<div style="text-align:center;padding:40px;color:var(--t3)">加载中...</div>';
  try {
    const token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
    const headers = {};
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch('/api/drama/projects', { headers });
    if (!res.ok) throw new Error('加载失败');
    const data = await res.json();
    const projects = data.projects || [];
    _dramaProjectsCache = projects;
    if (projects.length === 0) {
      grid.innerHTML =
        '<div class="empty-state">' +
        '<div class="empty-state-icon">🎬</div>' +
        '<div class="empty-state-title">还没有短剧作品</div>' +
        '<div class="empty-state-desc">打开短剧工作室，AI 帮你完成从剧本到成片的全部流程</div>' +
        '</div>';
      return;
    }
    const statusLabels = { draft: '草稿', generating: '生成中', completed: '已完成', failed: '失败' };
    grid.innerHTML = projects.map(function(p) {
      const statusClass = 'status-' + p.status;
      var logline = p.logline || '暂无梗概';
      if (logline.length > 50) logline = logline.substring(0, 50) + '...';
      return '<div class="work-card" style="cursor:pointer;">' +
        '<div class="work-card-header">' +
        '<span style="display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;background:#FF4757;color:#fff;">' + (p.genre || '短剧') + '</span>' +
        '<span class="status-badge ' + statusClass + '">' + (statusLabels[p.status] || p.status) + '</span>' +
        '</div>' +
        '<div style="padding:0 12px 12px;" onclick="openDramaDetailModal(' + p.id + ')">' +
        '<h3 style="margin:0 0 4px;font-size:15px;">' + p.title + '</h3>' +
        '<p style="margin:0 0 8px;font-size:12px;color:var(--t3);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">' + logline + '</p>' +
        '<div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--t3);">' +
        '<span>' + (p.episode_count || 0) + ' / ' + p.total_episodes + ' 集</span>' +
        '</div>' +
        '</div>' +
        '<div style="display:flex;border-top:1px solid var(--border);">' +
        '<button class="drama-action-btn" style="flex:1;padding:8px;border:none;background:none;color:var(--t3);font-size:12px;cursor:pointer;border-right:1px solid var(--border);" onclick="event.stopPropagation();openDramaDetailModal(' + p.id + ')">📋 详情</button>' +
        (p.status === 'draft' || p.status === 'failed' ? '<button class="drama-action-btn" style="flex:1;padding:8px;border:none;background:none;color:#22c55e;font-size:12px;cursor:pointer;border-right:1px solid var(--border);" onclick="event.stopPropagation();continueDramaProject(' + p.id + ')">▶ 继续</button>' : '') +
        '<button class="drama-action-btn" style="flex:1;padding:8px;border:none;background:none;color:var(--t3);font-size:12px;cursor:pointer;border-right:1px solid var(--border);" onclick="event.stopPropagation();editDramaProject(' + p.id + ')">✏️ 编辑</button>' +
        '<button class="drama-action-btn" style="flex:1;padding:8px;border:none;background:none;color:#FF4757;font-size:12px;cursor:pointer;" onclick="event.stopPropagation();deleteDramaProject(' + p.id + ')">🗑️ 删除</button>' +
        '</div></div>';
    }).join('');
  } catch (e) {
    grid.innerHTML = '<div class="empty-state"><p style="color:var(--t3);">加载失败</p></div>';
  }
}

// ═══════════════════════════════════════════════════════════════════
// 短剧详情弹窗
// ═══════════════════════════════════════════════════════════════════
var _dramaProjectsCache = [];

function _findProject(id) {
  return _dramaProjectsCache.find(function(p) { return p.id === id; });
}

async function openDramaDetailModal(projectId) {
  var modal = document.getElementById('dramaDetailModal');
  var content = document.getElementById('dramaDetailContent');
  modal.style.display = 'block';
  content.innerHTML = '<div style="text-align:center;padding:30px;color:var(--t3);">加载中...</div>';

  // Try cache first, then fetch
  var project = _findProject(projectId);
  if (!project) {
    try {
      var token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
      var headers = {};
      if (token) headers['Authorization'] = 'Bearer ' + token;
      var res = await fetch('/api/drama/projects/' + projectId, { headers });
      if (res.ok) project = await res.json();
    } catch (e) {}
  }
  if (!project) {
    content.innerHTML = '<div style="text-align:center;padding:30px;color:#FF4757;">项目不存在</div>';
    return;
  }

  var statusLabels = { draft: '草稿', generating: '生成中', completed: '已完成', failed: '失败' };
  var statusClass = 'status-' + project.status;
  var episodes = project.episodes || [];

  var html = '' +
    '<div style="margin-bottom:20px;">' +
    '<h2 style="margin:0 0 6px;font-size:20px;">' + (project.title || '') + '</h2>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">' +
    '<span style="padding:2px 10px;border-radius:12px;font-size:12px;background:#FF4757;color:#fff;">' + (project.genre || '短剧') + '</span>' +
    '<span class="status-badge ' + statusClass + '">' + (statusLabels[project.status] || project.status) + '</span>' +
    '<span style="font-size:12px;color:var(--t3);padding:2px 0;">' + (project.episode_count || 0) + '/' + project.total_episodes + ' 集</span>' +
    '</div>' +
    '<p style="font-size:13px;color:var(--t2);line-height:1.5;margin:0;">' + (project.logline || '暂无梗概') + '</p>' +
    '</div>';

  // Episodes list with preview & download
  if (episodes.length > 0) {
    var hasVideo = episodes.some(function(ep) { return ep.status === 'completed' || ep.status === 'generating'; });
    html += '<div style="margin-bottom:16px;">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
      '<span style="font-size:13px;font-weight:500;color:var(--t2);">📜 剧集列表</span>' +
      (hasVideo ? '<button onclick="batchDownloadDrama(' + project.id + ')" style="padding:6px 12px;border:none;border-radius:6px;background:#7c3aed;color:#fff;font-size:11px;cursor:pointer;">⬇ 批量下载</button>' : '') +
      '</div>';
    episodes.forEach(function(ep) {
      var epStatus = ep.status || 'draft';
      html += '<div style="background:var(--bg3);border-radius:8px;padding:10px;margin-bottom:8px;font-size:12px;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;">' +
        '<div><strong>' + (ep.title || '第' + ep.episode_number + '集') + '</strong>' +
        '<span style="margin-left:6px;font-size:11px;color:var(--t3);">(' + (ep.scene_count || 0) + ' 个分镜)</span></div>' +
        '<span style="font-size:11px;padding:1px 6px;border-radius:4px;background:rgba(255,255,255,0.08);color:var(--t2);">' + (statusLabels[epStatus] || epStatus) + '</span>' +
        '</div>' +
        (ep.hook ? '<div style="color:var(--t3);margin-top:4px;">🎣 ' + ep.hook + '</div>' : '') +
        // Preview & download for completed episodes
        (epStatus === 'completed' || epStatus === 'generating' ? (
          '<div style="margin-top:8px;display:flex;gap:6px;">' +
          '<button onclick="previewDramaEpisode(' + ep.id + ',' + project.id + ')" style="flex:1;padding:6px;border:none;border-radius:6px;background:rgba(34,197,94,0.15);color:#22c55e;font-size:11px;cursor:pointer;">▶ 预览</button>' +
          '<button onclick="downloadDramaEpisode(' + ep.id + ')" style="flex:1;padding:6px;border:none;border-radius:6px;background:rgba(255,255,255,0.08);color:var(--t1);font-size:11px;cursor:pointer;">⬇ 下载</button>' +
          '</div>'
        ) : '') +
        '</div>';
    });
    html += '</div>';
  }

  // Action buttons
  var continueDisabled = project.status === 'completed';
  html += '<div style="display:flex;gap:8px;margin-top:20px;padding-top:16px;border-top:1px solid var(--border);">' +
    '<button onclick="continueDramaProject(' + project.id + ')" style="flex:1;padding:10px;border:none;border-radius:8px;' + (continueDisabled ? 'background:var(--bg3);color:var(--t3);cursor:not-allowed;' : 'background:#22c55e;color:#fff;cursor:pointer;') + 'font-size:13px;"' + (continueDisabled ? ' disabled' : '') + '>▶ 继续生成</button>' +
    '<button onclick="editDramaProject(' + project.id + ')" style="flex:1;padding:10px;border:none;border-radius:8px;background:var(--bg3);color:var(--t1);font-size:13px;cursor:pointer;">✏️ 编辑</button>' +
    '<button onclick="deleteDramaProject(' + project.id + ')" style="flex:1;padding:10px;border:none;border-radius:8px;background:rgba(255,71,87,0.15);color:#FF4757;font-size:13px;cursor:pointer;">🗑️ 删除</button>' +
    '</div>';

  content.innerHTML = html;
}

function closeDramaDetailModal() {
  document.getElementById('dramaDetailModal').style.display = 'none';
}

// ═══════════════════════════════════════════════════════════════════
// 短剧预览 & 下载
// ═══════════════════════════════════════════════════════════════════

async function previewDramaEpisode(episodeId, projectId) {
  closeDramaDetailModal();
  // Open homepage with episode preview
  window.location.href = '/?drama=' + projectId + '&episode=' + episodeId;
}

async function downloadDramaEpisode(episodeId) {
  try {
    var token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
    var res = await fetch('/api/drama/episodes/' + episodeId + '/export', {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    if (!res.ok) { alert('导出失败'); return; }
    var manifest = await res.json();
    var clips = manifest.clips || [];
    if (clips.length === 0) { alert('该剧集暂无可用视频'); return; }

    // Find the first available video URL
    var videoUrl = clips[0].video_url;
    if (!videoUrl) { alert('暂无视频文件'); return; }

    // Open download in new tab (server should serve the file)
    var a = document.createElement('a');
    a.href = videoUrl;
    a.download = 'episode_' + manifest.episode_number + '_' + (manifest.title || '').replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '_') + '.mp4';
    a.target = '_blank';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  } catch (e) {
    alert('下载失败：' + e.message);
  }
}

async function batchDownloadDrama(projectId) {
  try {
    var token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
    var res = await fetch('/api/drama/projects/' + projectId + '/export', {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    if (!res.ok) { alert('批量导出失败'); return; }
    var data = await res.json();
    var episodes = data.episodes || [];

    // Collect all video URLs
    var allClips = [];
    episodes.forEach(function(ep) {
      (ep.clips || []).forEach(function(c) {
        if (c.video_url) {
          allClips.push({ episode_number: ep.episode_number, title: ep.title, url: c.video_url });
        }
      });
    });

    if (allClips.length === 0) { alert('暂无可用视频'); return; }

    // Generate a JSON manifest file with all URLs
    var manifestContent = JSON.stringify({
      project: data.title,
      total_episodes: data.total_episodes,
      clips: allClips
    }, null, 2);

    // Download the manifest as JSON
    var blob = new Blob([manifestContent], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (data.title || 'drama') + '_export.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    // Also open all video URLs in new tabs (batch download trigger)
    var uniqueUrls = {};
    allClips.forEach(function(c) {
      if (!uniqueUrls[c.url]) {
        uniqueUrls[c.url] = true;
        window.open(c.url, '_blank');
      }
    });

    alert('已导出 ' + allClips.length + ' 个视频文件清单');
  } catch (e) {
    alert('批量下载失败：' + e.message);
  }
}

// Click outside modal to close
document.addEventListener('click', function(e) {
  var modal = document.getElementById('dramaDetailModal');
  if (modal && modal.style.display === 'block' && e.target === modal) {
    closeDramaDetailModal();
  }
});

async function deleteDramaProject(id) {
  if (!confirm('确定要删除这个短剧项目吗？此操作不可恢复。')) return;
  try {
    var token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
    var res = await fetch('/api/drama/projects/' + id, {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + token }
    });
    var data = await res.json();
    if (res.ok) {
      alert('✅ ' + (data.message || '已删除'));
      closeDramaDetailModal();
      loadDramaWorks();
    } else {
      alert('删除失败：' + (data.detail || ''));
    }
  } catch (e) {
    alert('删除失败：' + e.message);
  }
}

function editDramaProject(id) {
  var project = _findProject(id);
  if (!project) return;
  closeDramaDetailModal();
  // Simple inline prompt-based edit
  var newTitle = prompt('修改标题：', project.title || '');
  if (newTitle === null) return;
  var newGenre = prompt('修改类型（逆袭/重生/霸总/甜宠/穿越/古装/悬疑/都市）：', project.genre || '逆袭');
  if (newGenre === null) return;
  var newLogline = prompt('修改梗概：', project.logline || '');
  if (newLogline === null) return;
  doUpdateDramaProject(id, newTitle.trim(), newGenre.trim(), newLogline.trim());
}

async function doUpdateDramaProject(id, title, genre, logline) {
  try {
    var token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
    var res = await fetch('/api/drama/projects/' + id, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ title: title, genre: genre, logline: logline })
    });
    var data = await res.json();
    if (res.ok) {
      alert('✅ 已更新');
      loadDramaWorks();
    } else {
      alert('更新失败：' + (data.detail || ''));
    }
  } catch (e) {
    alert('更新失败：' + e.message);
  }
}

async function continueDramaProject(id) {
  var project = _findProject(id);
  if (!project) return;
  if (project.status === 'completed') {
    alert('该项目已完成生成');
    return;
  }
  closeDramaDetailModal();
  try {
    var token = localStorage.getItem('sdToken') || localStorage.getItem('sdApiKey');
    var res = await fetch('/api/drama/projects/' + id + '/generate-script', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: '{}'
    });
    var data = await res.json();
    if (res.ok) {
      alert('✅ ' + (data.message || '已重新开始生成'));
      loadDramaWorks();
    } else {
      alert('生成失败：' + (data.detail || ''));
    }
  } catch (e) {
    alert('生成失败：' + e.message);
  }
}

async function loadTelegramConfig() {
  try {
    const res = await fetch('/api/public/site-config');
    if (!res.ok) return;
    const d = await res.json();
    const url = d.telegram_url || 'https://t.me/sedgo_support';
    const name = d.telegram_name || '@sedgo_support';
    const el = document.getElementById('profileTelegramLink');
    if (el) { el.href = url; el.textContent = name; }
  } catch (e) {}
}
