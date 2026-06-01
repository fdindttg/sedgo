const API_BASE = '/api/admin';
let authToken = localStorage.getItem('admin_token');
let currentPage = 'dashboard';

async function api(path, opts={}) {
  const url = API_BASE + path;
  const res = await fetch(url, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + (authToken || ''),
      ...(opts.headers || {})
    }
  });
  if (res.status === 401) {
    localStorage.removeItem('admin_token');
    showLogin();
    throw new Error('未登录');
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || '请求失败');
  }
  return res.json();
}

function showToast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast toast-' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 3000);
}

function showLogin() {
  document.body.classList.add('login-mode');
  document.getElementById('loginPage').style.display = 'flex';
  document.getElementById('appMain').style.display = 'none';
}

function showApp() {
  document.body.classList.remove('login-mode');
  document.getElementById('loginPage').style.display = 'none';
  document.getElementById('appMain').style.display = 'block';
  loadDashboard();
}

document.getElementById('loginBtn').addEventListener('click', async () => {
  const username = document.getElementById('loginEmail').value;
  const pwd = document.getElementById('loginPwd').value;
  const btn = document.getElementById('loginBtn');
  btn.disabled = true;
  
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: username, password: pwd })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '登录失败');
    if (data.user.role !== 'admin') throw new Error('非管理员账户');
    authToken = data.access_token;
    localStorage.setItem('admin_token', authToken);
    document.getElementById('sidebarUser').textContent = data.user.display_name || '管理员';
    showApp();
  } catch (e) {
    document.getElementById('loginError').textContent = e.message;
    document.getElementById('loginError').style.display = 'block';
  } finally {
    btn.disabled = false;
  }
});

function doLogout() {
  localStorage.removeItem('admin_token');
  authToken = null;
  showLogin();
}

// 移动端侧边栏切换
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  sidebar.classList.toggle('open');
  overlay.classList.toggle('show');
}

function switchPage(page) {
  currentPage = page;
  // 移动端切换页面时关闭侧边栏
  if (window.innerWidth <= 768) {
    toggleSidebar();
  }
  document.querySelectorAll('.page-content').forEach(el => el.classList.remove('active'));
  // 确保 page-endpoints 也被隐藏（它用独立逻辑显示）
  document.getElementById('page-endpoints').classList.remove('active');
  const target = document.getElementById('page-' + page);
  if (target) target.classList.add('active');
  document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('active'));
  const sitem = document.querySelector('.sidebar-item[data-page="' + page + '"]');
  if (sitem) sitem.classList.add('active');
  const titles = { dashboard:'仪表盘', users:'用户管理', plans:'套餐管理', subscriptions:'订阅记录', channels:'渠道管理', points:'积分配置', tasks:'任务监控', billing:'账单管理', payments:'支付与设置', contacts:'工单管理' };
  document.getElementById('topbarTitle').textContent = titles[page] || page;

  if (page === 'dashboard') loadDashboard();
  else if (page === 'users') loadUsers();
  else if (page === 'plans') loadPlans();
  else if (page === 'subscriptions') loadSubscriptions();
  else if (page === 'channels') loadChannels();
  else if (page === 'points') { loadPricingConfig(); }
  else if (page === 'tasks') loadTasks(1);
  else if (page === 'billing') loadBilling(1);
  else if (page === 'payments') { loadUsdtConfig(); loadSiteConfig(); loadPaymentOrders(1); }
  else if (page === 'contacts') loadContactMessages(1);
}

// Dashboard
async function loadDashboard() {
  try {
    const d = await api('/dashboard');
    document.getElementById('dashStats').innerHTML = `
      <div class="stat-card"><div class="stat-label">总用户数</div><div class="stat-value">${d.total_users}</div></div>
      <div class="stat-card"><div class="stat-label">总任务数</div><div class="stat-value">${d.total_tasks}</div></div>
      <div class="stat-card"><div class="stat-label">积分消耗</div><div class="stat-value">${(d.total_points_consumed || 0).toLocaleString()}</div></div>
      <div class="stat-card"><div class="stat-label">今日活跃</div><div class="stat-value">${d.active_users_today}</div></div>
    `;
    renderChart('taskChart', d.task_trend || []);
    renderChart('userChart', d.user_trend || []);
    if (d.task_by_status) {
      const labels = { pending:'⏳ 待处理', processing:'🔄 处理中', success:'✅ 成功', failed:'❌ 失败', cancelled:'🚫 已取消' };
      const colors = { pending:'var(--t2)', processing:'var(--accent)', success:'var(--green)', failed:'var(--red)', cancelled:'var(--t3)' };
      let html = '';
      for (const [k, v] of Object.entries(d.task_by_status)) {
        html += `<div class="status-card"><div class="status-label">${labels[k] || k}</div><div class="status-value" style="color:${colors[k] || 'var(--t1)'}">${v}</div></div>`;
      }
      document.getElementById('taskStatusGrid').innerHTML = html;
    }
  } catch (e) { console.error(e); }
}

function renderChart(elId, data) {
  const el = document.getElementById(elId);
  if (!data.length) { el.innerHTML = '<div style="color:var(--t3);text-align:center;width:100%;">暂无数据</div>'; return; }
  const maxVal = Math.max(...data.map(d => d.count), 1);
  let html = '';
  data.forEach(d => {
    const h = Math.max((d.count / maxVal) * 120, 4);
    const label = (d.date || '').slice(-5);
    html += `<div class="chart-bar-wrap"><div class="chart-bar" style="height:${h}px;" title="${d.date}: ${d.count}"></div><div class="chart-bar-label">${label}</div></div>`;
  });
  el.innerHTML = html;
}

// Users
let userPage = 1;
async function loadUsers(page) {
  if (page) userPage = page;
  const search = document.getElementById('userSearch').value.trim();
  try {
    const d = await api(`/users?page=${userPage}&page_size=20&search=${encodeURIComponent(search)}`);
    let html = '';
    d.items.forEach(u => {
      const statusBadge = { active:'badge-success', inactive:'badge-warning', banned:'badge-danger' }[u.status] || 'badge-neutral';
      const statusText = { active:'正常', inactive:'停用', banned:'封禁' }[u.status] || u.status;
      const roleBadge = u.role === 'admin' ? 'badge-info' : 'badge-neutral';
      const roleText = u.role === 'admin' ? '管理员' : '用户';
      html += `<tr>
        <td>${u.id}</td><td>${u.email || '-'}</td><td>${u.display_name || '-'}</td>
        <td><span class="badge ${roleBadge}">${roleText}</span></td>
        <td><span class="badge ${statusBadge}">${statusText}</span></td>
        <td>${u.points_balance || 0}</td>
        <td>${u.subscription?.plan_name || '-'}</td>
        <td>${(u.created_at || '').slice(0,10)}</td>
        <td>
          <a class="action-link" onclick="openPointsModal(${u.id}, ${u.points_balance || 0})">积分</a>
          <a class="action-link" onclick="openSubscriptionModal(${u.id})">订阅</a>
          <a class="action-link" onclick="toggleUserStatus(${u.id},'${u.status}','${u.status==='active'?'inactive':'active'}')">${u.status==='active'?'停用':'启用'}</a>
          <a class="action-link danger" onclick="toggleUserStatus(${u.id},'${u.status}','banned')">封禁</a>
          <a class="action-link" onclick="toggleUserRole(${u.id},'${u.role}')">${u.role==='admin'?'降级':'提升'}</a>
        </td>
      </tr>`;
    });
    if (!html) html = '<tr><td colspan="9" class="empty-state"><div class="empty-state-text">暂无用户数据</div></td></tr>';
    document.getElementById('userTableBody').innerHTML = html;
    renderPagination('userPagination', d.total, userPage, 20, loadUsers);
  } catch (e) { console.error(e); }
}

async function toggleUserStatus(id, curStatus, newStatus) {
  if (newStatus === 'banned' && !confirm('确认封禁该用户？')) return;
  try {
    await api(`/users/${id}`, { method: 'PUT', body: JSON.stringify({ status: newStatus }) });
    showToast('操作成功', 'success');
    loadUsers();
  } catch (e) { showToast(e.message, 'error'); }
}

async function toggleUserRole(id, curRole) {
  const newRole = curRole === 'admin' ? 'user' : 'admin';
  try {
    await api(`/users/${id}`, { method: 'PUT', body: JSON.stringify({ role: newRole }) });
    showToast('操作成功', 'success');
    loadUsers();
  } catch (e) { showToast(e.message, 'error'); }
}

function renderPagination(elId, total, page, pageSize, loadFn) {
  const totalPages = Math.ceil(total / pageSize) || 1;
  let html = `<button onclick="${loadFn.name}(${page-1})" ${page<=1?'disabled':''}>上一页</button>`;
  html += `<span>${page} / ${totalPages}</span>`;
  html += `<button onclick="${loadFn.name}(${page+1})" ${page>=totalPages?'disabled':''}>下一页</button>`;
  document.getElementById(elId).innerHTML = html;
}

// Plans
async function loadPlans() {
  try {
    const data = await api('/plans');
    let html = '';
    data.forEach(p => {
      html += `<tr>
        <td>${p.id}</td><td>${p.name}</td><td>${(p.price_cents/100).toFixed(2)}</td><td>${p.duration_days}</td>
        <td>${p.points_per_month}</td><td>${p.max_batch_size}</td><td>${p.max_resolution}</td>
        <td><span class="badge ${p.is_active?'badge-success':'badge-neutral'}">${p.is_active?'启用':'停用'}</span></td>
        <td>${p.sort_order}</td>
        <td>
          <a class="action-link" onclick='editPlan(${p.id}, decodeURIComponent("${encodeURIComponent(JSON.stringify(p))}"))'>编辑</a>
          <a class="action-link danger" onclick="deletePlan(${p.id})">删除</a>
        </td>
      </tr>`;
    });
    if (!html) html = '<tr><td colspan="10" class="empty-state"><div class="empty-state-text">暂无套餐</div></td></tr>';
    document.getElementById('planTableBody').innerHTML = html;
  } catch (e) { console.error(e); }
}

let _usdToPointsRate = 100; // 默认汇率

// 加载汇率配置
async function loadUsdToPointsRate() {
  try {
    const cfg = await api('/pricing-config');
    _usdToPointsRate = cfg.usd_to_points || 100;
  } catch (e) {
    console.error('Failed to load USD to points rate:', e);
  }
}

// 根据价格计算积分
function calculatePointsFromPrice(priceCents) {
  const priceUsd = priceCents / 100;
  return Math.round(priceUsd * _usdToPointsRate);
}

function openPlanModal(plan) {
  document.getElementById('planModal').classList.add('open');
  if (plan) {
    document.getElementById('planModalTitle').textContent = '编辑套餐';
    document.getElementById('planEditId').value = plan.id;
    document.getElementById('planName').value = plan.name || '';
    document.getElementById('planDesc').value = plan.description || '';
    document.getElementById('planPrice').value = plan.price_cents || 0;
    document.getElementById('planDays').value = plan.duration_days || 30;
    document.getElementById('planPoints').value = plan.points_per_month || 0;
    document.getElementById('planBatch').value = plan.max_batch_size || 1;
    document.getElementById('planConcurrent').value = plan.max_concurrent_tasks || 1;
    document.getElementById('planRes').value = plan.max_resolution || '720p';
    document.getElementById('planSort').value = plan.sort_order || 0;
  } else {
    document.getElementById('planModalTitle').textContent = '新建套餐';
    document.getElementById('planEditId').value = '';
    document.getElementById('planName').value = '';
    document.getElementById('planDesc').value = '';
    document.getElementById('planPrice').value = 0;
    document.getElementById('planDays').value = 30;
    document.getElementById('planPoints').value = 0;
    document.getElementById('planBatch').value = 1;
    document.getElementById('planConcurrent').value = 1;
    document.getElementById('planRes').value = '720p';
    document.getElementById('planSort').value = 0;
  }
}

function closePlanModal() { document.getElementById('planModal').classList.remove('open'); }

async function savePlan() {
  const id = document.getElementById('planEditId').value;
  const body = {
    name: document.getElementById('planName').value,
    description: document.getElementById('planDesc').value,
    price_cents: parseInt(document.getElementById('planPrice').value) || 0,
    duration_days: parseInt(document.getElementById('planDays').value) || 30,
    max_batch_size: parseInt(document.getElementById('planBatch').value) || 1,
    max_concurrent_tasks: parseInt(document.getElementById('planConcurrent').value) || 1,
    max_resolution: document.getElementById('planRes').value,
    sort_order: parseInt(document.getElementById('planSort').value) || 0,
    is_active: true,
  };
  try {
    if (id) {
      await api(`/plans/${id}`, { method: 'PUT', body: JSON.stringify(body) });
    } else {
      await api('/plans', { method: 'POST', body: JSON.stringify(body) });
    }
    showToast(id ? '套餐已更新' : '套餐已创建', 'success');
    closePlanModal();
    loadPlans();
  } catch (e) { showToast(e.message, 'error'); }
}

function editPlan(id, str) {
  const p = JSON.parse(str);
  p.id = id;
  openPlanModal(p);
}

async function deletePlan(id) {
  if (!confirm('确认删除该套餐？')) return;
  try {
    await api(`/plans/${id}`, { method: 'DELETE' });
    showToast('套餐已删除', 'success');
    loadPlans();
  } catch (e) { showToast(e.message, 'error'); }
}

// Subscriptions
let subPage = 1;
async function loadSubscriptions(page) {
  if (page) subPage = page;
  try {
    const d = await api(`/subscriptions?page=${subPage}&page_size=20`);
    let html = '';
    d.items.forEach(s => {
      const statusBadge = { active:'badge-success', expired:'badge-warning', cancelled:'badge-neutral', trial:'badge-info' }[s.status] || 'badge-neutral';
      const statusText = { active:'有效', expired:'已过期', cancelled:'已取消', trial:'试用' }[s.status] || s.status;
      html += `<tr>
        <td>${s.id}</td><td>${s.user_email || s.user_id}</td><td>${s.plan_name || '-'}</td>
        <td><span class="badge ${statusBadge}">${statusText}</span></td>
        <td>${(s.started_at||'').slice(0,10)}</td><td>${(s.expires_at||'').slice(0,10)}</td>
        <td>${s.auto_renew ? '是' : '否'}</td>
        <td>
          ${s.status==='active' ? `<a class="action-link danger" onclick="cancelSub(${s.id})">取消</a>` : '-'}
        </td>
      </tr>`;
    });
    if (!html) html = '<tr><td colspan="8" class="empty-state"><div class="empty-state-text">暂无订阅记录</div></td></tr>';
    document.getElementById('subTableBody').innerHTML = html;
    renderPagination('subPagination', d.total, subPage, 20, loadSubscriptions);
  } catch (e) { console.error(e); }
}

async function openSubModal() {
  document.getElementById('subModal').classList.add('open');
  const plans = await api('/plans');
  let opts = '<option value="">选择套餐</option>';
  plans.filter(p => p.is_active).forEach(p => {
    opts += `<option value="${p.id}">${p.name} (${p.duration_days}天)</option>`;
  });
  document.getElementById('subPlanId').innerHTML = opts;
}
function closeSubModal() { document.getElementById('subModal').classList.remove('open'); }

function openPointsModal(userId, balance) {
  document.getElementById('pointsUserId').value = userId;
  document.getElementById('pointsCurrent').value = balance;
  document.getElementById('pointsAmount').value = '';
  document.getElementById('pointsReason').value = '';
  document.getElementById('pointsModal').classList.add('open');
}

function closePointsModal() { document.getElementById('pointsModal').classList.remove('open'); }

async function savePoints() {
  const userId = parseInt(document.getElementById('pointsUserId').value);
  const amount = parseInt(document.getElementById('pointsAmount').value);
  const reason = document.getElementById('pointsReason').value;
  
  if (!userId || amount === undefined || amount === null) {
    showToast('请填写调整金额', 'error');
    return;
  }
  
  if (amount === 0) {
    showToast('调整金额不能为0', 'error');
    return;
  }
  
  try {
    const body = { amount };
    if (reason) body.reason = reason;
    await api(`/users/${userId}/points`, { method: 'POST', body: JSON.stringify(body) });
    showToast(`积分已调整 ${amount > 0 ? '+' : ''}${amount}`, 'success');
    closePointsModal();
    loadUsers();
  } catch (e) { showToast(e.message, 'error'); }
}

async function openSubscriptionModal(userId) {
  document.getElementById('userSubUserId').value = userId;
  document.getElementById('userSubDuration').value = '';
  
  try {
    const plans = await api('/plans');
    let opts = '<option value="">选择套餐</option>';
    plans.filter(p => p.is_active).forEach(p => {
      opts += `<option value="${p.id}">${p.name} (${p.duration_days}天)</option>`;
    });
    document.getElementById('userSubPlanId').innerHTML = opts;
  } catch (e) {
    console.error('Failed to load plans:', e);
  }
  
  document.getElementById('userSubModal').classList.add('open');
}

function closeUserSubModal() { document.getElementById('userSubModal').classList.remove('open'); }

async function saveUserSub() {
  const userId = parseInt(document.getElementById('userSubUserId').value);
  const planId = parseInt(document.getElementById('userSubPlanId').value);
  const billingCycle = document.getElementById('userSubCycle').value;
  const duration = parseInt(document.getElementById('userSubDuration').value);
  const status = document.getElementById('userSubStatus').value;
  
  if (!userId) {
    showToast('用户ID无效', 'error');
    return;
  }
  
  try {
    const body = {};
    if (planId) body.plan_id = planId;
    if (billingCycle) body.billing_cycle = billingCycle;
    if (duration) body.duration = duration;
    if (status) body.status = status;
    
    await api(`/users/${userId}/subscription`, { method: 'PUT', body: JSON.stringify(body) });
    showToast('订阅已更新', 'success');
    closeUserSubModal();
    loadUsers();
  } catch (e) { showToast(e.message, 'error'); }
}

async function saveSub() {
  const user_id = parseInt(document.getElementById('subUserId').value);
  const plan_id = parseInt(document.getElementById('subPlanId').value);
  const duration_days = parseInt(document.getElementById('subDaysDays').value) || undefined;
  if (!user_id || !plan_id) { showToast('请填写用户ID和选择套餐', 'error'); return; }
  try {
    const body = { user_id, plan_id };
    if (duration_days) body.duration_days = duration_days;
    await api('/subscriptions', { method: 'POST', body: JSON.stringify(body) });
    showToast('订阅已创建', 'success');
    closeSubModal();
    loadSubscriptions();
  } catch (e) { showToast(e.message, 'error'); }
}

async function cancelSub(id) {
  if (!confirm('确认取消该订阅？')) return;
  try {
    await api(`/subscriptions/${id}/cancel`, { method: 'POST' });
    showToast('订阅已取消', 'success');
    loadSubscriptions();
  } catch (e) { showToast(e.message, 'error'); }
}

// Channels
async function loadChannels() {
  try {
    const data = await api('/channels');
    let html = '';
    data.forEach(c => {
      html += `<tr>
        <td>${c.id}</td><td>${c.name}</td><td>${c.provider}</td>
        <td>${c.api_base_url || '-'}</td>
        <td>${c.project_id || '-'}</td>
        <td>${c.priority}</td>
        <td><span class="badge ${c.is_active?'badge-success':'badge-neutral'}">${c.is_active?'启用':'停用'}</span></td>
        <td>
          <a class="action-link" onclick='editChannel(${c.id}, decodeURIComponent("${encodeURIComponent(JSON.stringify(c))}"))'>编辑</a>
          <a class="action-link" onclick="toggleChannelActive(${c.id},${c.is_active})">${c.is_active?'停用':'启用'}</a>
          <a class="action-link" onclick="manageEndpoints(${c.id},'${c.name}')">接入点</a>
          <a class="action-link danger" onclick="deleteChannel(${c.id})">删除</a>
        </td>
      </tr>`;
    });
    if (!html) html = '<tr><td colspan="8" class="empty-state"><div class="empty-state-text">暂无渠道</div></td></tr>';
    document.getElementById('channelTableBody').innerHTML = html;
  } catch (e) { console.error(e); }
}

function openChannelModal(ch) {
  document.getElementById('channelModal').classList.add('open');
  if (ch) {
    document.getElementById('channelModalTitle').textContent = '编辑渠道';
    document.getElementById('channelEditId').value = ch.id;
    document.getElementById('chName').value = ch.name || '';
    document.getElementById('chProvider').value = ch.provider || 'byteplus';
    document.getElementById('chApiBase').value = ch.api_base_url || '';
    document.getElementById('chFileUrl').value = ch.file_url || '';
    document.getElementById('chTaskUrl').value = ch.task_url || '';
    document.getElementById('chAk').value = '';
    document.getElementById('chSk').value = '';
    document.getElementById('chApiKey').value = '';
    document.getElementById('chProjectId').value = ch.project_id || '';
    document.getElementById('chPortraitGroupId').value = ch.portrait_group_id || '';
    document.getElementById('chPublicBaseUrl').value = ch.public_base_url || '';
    document.getElementById('chPriority').value = ch.priority || 0;
  } else {
    document.getElementById('channelModalTitle').textContent = '新建渠道';
    document.getElementById('channelEditId').value = '';
    document.getElementById('chName').value = '';
    document.getElementById('chProvider').value = 'byteplus';
    document.getElementById('chApiBase').value = '';
    document.getElementById('chFileUrl').value = '';
    document.getElementById('chTaskUrl').value = '';
    document.getElementById('chAk').value = '';
    document.getElementById('chSk').value = '';
    document.getElementById('chApiKey').value = '';
    document.getElementById('chProjectId').value = '';
    document.getElementById('chPortraitGroupId').value = '';
    document.getElementById('chPublicBaseUrl').value = '';
    document.getElementById('chPriority').value = 0;
  }
}
function closeChannelModal() { document.getElementById('channelModal').classList.remove('open'); }

async function saveChannel() {
  const id = document.getElementById('channelEditId').value;
  const body = {
    name: document.getElementById('chName').value,
    provider: document.getElementById('chProvider').value,
    api_base_url: document.getElementById('chApiBase').value,
    file_url: document.getElementById('chFileUrl').value,
    task_url: document.getElementById('chTaskUrl').value,
    ak: document.getElementById('chAk').value,
    sk: document.getElementById('chSk').value,
    api_key: document.getElementById('chApiKey').value,
    project_id: document.getElementById('chProjectId').value,
    portrait_group_id: document.getElementById('chPortraitGroupId').value,
    public_base_url: document.getElementById('chPublicBaseUrl').value,
    priority: parseInt(document.getElementById('chPriority').value) || 0,
    is_active: true,
  };
  try {
    if (id) {
      await api(`/channels/${id}`, { method: 'PUT', body: JSON.stringify(body) });
    } else {
      await api('/channels', { method: 'POST', body: JSON.stringify(body) });
    }
    showToast(id ? '渠道已更新' : '渠道已创建', 'success');
    closeChannelModal();
    loadChannels();
  } catch (e) {
    showToast('保存失败: ' + (e.message || e), 'error');
  }
}

function editChannel(id, str) {
  let c;
  if (typeof str === 'string') {
    c = JSON.parse(str.replace(/&quot;/g, '"'));
  } else {
    c = str;
  }
  c.id = id;
  openChannelModal(c);
}

async function toggleChannelActive(id, isActive) {
  try {
    await api(`/channels/${id}`, { method: 'PUT', body: JSON.stringify({ is_active: !isActive }) });
    showToast(isActive ? '渠道已停用' : '渠道已启用', 'success');
    loadChannels();
  } catch (e) { showToast(e.message, 'error'); }
}

async function deleteChannel(id) {
  if (!confirm('确认删除该渠道？')) return;
  try {
    await api(`/channels/${id}`, { method: 'DELETE' });
    showToast('渠道已删除', 'success');
    loadChannels();
  } catch (e) { showToast(e.message, 'error'); }
}

// Endpoints
let currentChannelId = 0;
let currentChannelName = '';

function goBackToChannels() {
  document.getElementById('page-endpoints').classList.remove('active');
  document.getElementById('page-channels').classList.add('active');
}

async function manageEndpoints(channelId, channelName) {
  currentChannelId = channelId;
  currentChannelName = channelName;
  document.getElementById('currentChannelInfo').innerHTML = `
    <strong>当前渠道:</strong> ${channelName} (ID: ${channelId})
  `;
  document.getElementById('page-channels').classList.remove('active');
  document.getElementById('page-endpoints').classList.add('active');
  await loadEndpoints();
  await loadModelsConfig();
}

async function loadEndpoints() {
  try {
    const data = await api(`/channels/${currentChannelId}/endpoints`);
    
    // 类型名称映射
    const typeNames = {
      'default': '通用',
      'video': '视频生成',
      'image': '图片生成',
      'inference': '推理'
    };
    
    let html = '';
    data.forEach(e => {
      const typeName = typeNames[e.type] || e.type;
      const badgeClass = e.type === 'video' ? 'badge-primary' : 
                      e.type === 'image' ? 'badge-success' : 
                      e.type === 'inference' ? 'badge-warning' : 'badge-neutral';
      
      html += `<tr>
        <td>${e.id}</td><td>${e.endpoint_id}</td><td>${e.endpoint_name || '-'}</td>
        <td><span class="badge ${badgeClass}">${typeName}</span></td>
        <td>${e.is_default?'是':'否'}</td>
        <td><span class="badge ${e.is_active?'badge-success':'badge-neutral'}">${e.is_active?'启用':'停用'}</span></td>
        <td>
          <a class="action-link" onclick='editEndpoint(${e.id}, decodeURIComponent("${encodeURIComponent(JSON.stringify(e))}"))'>编辑</a>
          <a class="action-link" onclick="testEndpoint(${e.id})">测试</a>
          <a class="action-link" onclick="toggleEndpointActive(${e.id},${e.is_active})">${e.is_active?'停用':'启用'}</a>
          <a class="action-link danger" onclick="deleteEndpoint(${e.id})">删除</a>
        </td>
      </tr>`;
    });
    if (!html) html = '<tr><td colspan="7" class="empty-state"><div class="empty-state-text">暂无接入点，点击上方按钮添加</div></td></tr>';
    document.getElementById('endpointTableBody').innerHTML = html;
  } catch (e) { console.error(e); }
}

async function testEndpoint(endpointId) {
  const button = event.target;
  const originalText = button.textContent;
  button.textContent = '测试中...';
  button.style.opacity = '0.6';
  
  try {
    const result = await api(`/channels/${currentChannelId}/test`, {
      method: 'POST',
      body: JSON.stringify({ endpoint_id: endpointId })
    });
    
    if (result.success) {
      let msg = `测试成功！\n接入点: ${result.endpoint}\n延迟: ${result.latency.toFixed(2)}ms`;
      if (result.task_id) msg += `\n任务ID: ${result.task_id}`;
      showToast(msg, 'success');
    } else {
      showToast(result.error || '测试失败', 'error');
    }
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    button.textContent = originalText;
    button.style.opacity = '1';
  }
}

function openEndpointModal(ep) {
  document.getElementById('endpointModal').classList.add('open');
  if (ep) {
    document.getElementById('endpointModalTitle').textContent = '编辑接入点';
    document.getElementById('endpointEditId').value = ep.id;
    document.getElementById('endpointChannelId').value = ep.channel_id;
    document.getElementById('epEndpointId').value = ep.endpoint_id || '';
    document.getElementById('epEndpointName').value = ep.endpoint_name || '';
    document.getElementById('epType').value = ep.type || 'default';
    document.getElementById('epIsDefault').checked = ep.is_default || false;
    document.getElementById('epModels').value = ep.models ? JSON.stringify(ep.models) : '';
  } else {
    document.getElementById('endpointModalTitle').textContent = '新建接入点';
    document.getElementById('endpointEditId').value = '';
    document.getElementById('endpointChannelId').value = currentChannelId;
    document.getElementById('epEndpointId').value = '';
    document.getElementById('epEndpointName').value = '';
    document.getElementById('epType').value = 'default';
    document.getElementById('epIsDefault').checked = false;
    document.getElementById('epModels').value = '';
  }
}
function closeEndpointModal() { document.getElementById('endpointModal').classList.remove('open'); }

async function saveEndpoint() {
  const id = document.getElementById('endpointEditId').value;
  const channelId = document.getElementById('endpointChannelId').value;
  const endpointId = document.getElementById('epEndpointId').value.trim();
  const endpointName = document.getElementById('epEndpointName').value.trim();
  const type = document.getElementById('epType').value;
  const isDefault = document.getElementById('epIsDefault').checked;
  const modelsStr = document.getElementById('epModels').value.trim();
  
  if (!endpointId) { showToast('请输入接入点ID', 'error'); return; }
  
  let models = [];
  if (modelsStr) {
    try { models = JSON.parse(modelsStr); } catch (e) { showToast('模型格式错误，应为JSON数组', 'error'); return; }
  }
  
  const body = {
    endpoint_id: endpointId,
    endpoint_name: endpointName || null,
    type: type,
    is_default: isDefault,
    models: models,
    is_active: true,
  };
  
  try {
    if (id) {
      await api(`/channels/${channelId}/endpoints/${id}`, { method: 'PUT', body: JSON.stringify(body) });
      showToast('接入点已更新', 'success');
    } else {
      await api(`/channels/${channelId}/endpoints`, { method: 'POST', body: JSON.stringify(body) });
      showToast('接入点已创建', 'success');
    }
    closeEndpointModal();
    loadEndpoints();
  } catch (e) { showToast(e.message, 'error'); }
}

function editEndpoint(id, str) {
  let e;
  if (typeof str === 'string') {
    e = JSON.parse(str.replace(/&quot;/g, '"'));
  } else if (typeof str === 'object') {
    e = str;
  } else {
    console.error('Invalid parameter type for editEndpoint:', typeof str);
    return;
  }
  e.id = id;
  openEndpointModal(e);
}

async function toggleEndpointActive(id, isActive) {
  try {
    await api(`/channels/${currentChannelId}/endpoints/${id}`, { method: 'PUT', body: JSON.stringify({ is_active: !isActive }) });
    showToast(isActive ? '接入点已停用' : '接入点已启用', 'success');
    loadEndpoints();
  } catch (e) { showToast(e.message, 'error'); }
}

async function deleteEndpoint(id) {
  if (!confirm('确认删除该接入点？')) return;
  try {
    await api(`/channels/${currentChannelId}/endpoints/${id}`, { method: 'DELETE' });
    showToast('接入点已删除', 'success');
    loadEndpoints();
  } catch (e) { showToast(e.message, 'error'); }
}

// Points Management
function switchPointsTab(tab) {
  document.querySelectorAll('.points-tab').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('[id^="points-tab-"]').forEach(el => el.style.display = 'none');
  event.target.classList.add('active');
  document.getElementById('points-tab-' + tab).style.display = 'block';

  if (tab === 'records') loadPointsRecords();
  else if (tab === 'stats') loadPointsStats();
  else if (tab === 'config') loadPricingConfig();
  else if (tab === 'packages') loadPackagesConfig();
}

const RESOLUTIONS = ['480p', '720p', '1080p'];
const IMAGE_SIZES = ['small', 'medium', 'large'];

async function loadPointsConfig() {
  try {
    const cfg = await api('/api/admin/points-per-5s');
    let rows = '';
    for (const [key, val] of Object.entries(cfg)) {
      rows += `<tr>
        <td style="padding:8px 12px;font-size:13px;color:var(--t2);white-space:nowrap;">${val.label || key}</td>
        <td style="padding:6px 8px;"><input type="number" min="0" step="0.1" data-key="${key}" data-res="480p" value="${val['480p'] ?? ''}" style="width:70px;background:var(--bg3);border:1px solid var(--border2);border-radius:6px;color:var(--t1);padding:5px 8px;text-align:center;" /></td>
        <td style="padding:6px 8px;"><input type="number" min="0" step="0.1" data-key="${key}" data-res="720p" value="${val['720p'] ?? ''}" style="width:70px;background:var(--bg3);border:1px solid var(--border2);border-radius:6px;color:var(--t1);padding:5px 8px;text-align:center;" /></td>
        <td style="padding:6px 8px;"><input type="number" min="0" step="0.1" data-key="${key}" data-res="1080p" value="${val['1080p'] ?? ''}" style="width:70px;background:var(--bg3);border:1px solid var(--border2);border-radius:6px;color:var(--t1);padding:5px 8px;text-align:center;" /></td>
      </tr>`;
    }
    document.getElementById('pointsConfigArea').innerHTML = `
      <p style="font-size:13px;color:var(--t3);margin-bottom:16px;">设置每种模型在不同分辨率下，每 <strong>秒</strong> 消耗的积分数。</p>
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr>
            <th style="padding:8px 12px;text-align:left;font-size:13px;color:var(--t3);border-bottom:1px solid var(--border);">模型</th>
            <th style="padding:8px 12px;text-align:center;font-size:13px;color:var(--t3);border-bottom:1px solid var(--border);">480p（积分/秒）</th>
            <th style="padding:8px 12px;text-align:center;font-size:13px;color:var(--t3);border-bottom:1px solid var(--border);">720p（积分/秒）</th>
            <th style="padding:8px 12px;text-align:center;font-size:13px;color:var(--t3);border-bottom:1px solid var(--border);">1080p（积分/秒）</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
    document.getElementById('pointsConfigArea')._rawCfg = cfg;
  } catch (e) { console.error(e); }
}

// 模型定价配置相关函数
let videoModels = [];
let imageModels = [];
let modelPricingConfigs = {};

async function loadModelsAndPricingConfig() {
  try {
    // 加载模型配置
    const modelsConfig = await api('/models-config');
    videoModels = modelsConfig.video || [];
    imageModels = modelsConfig.image || [];
    
    // 加载模型定价配置
    modelPricingConfigs = await api('/model-pricing-config');
    
    renderModelPricingConfig();
  } catch (e) { 
    console.error('Failed to load models and pricing config:', e); 
  }
}

function renderModelPricingConfig() {
  // 渲染视频模型成本配置
  let videoHtml = '';
  if (videoModels.length === 0) {
    videoHtml = '<div style="color:var(--t3);font-size:13px;padding:12px;">暂无视频模型配置</div>';
  } else {
    videoModels.forEach(model => {
      const modelConfig = modelPricingConfigs.video?.[model.id] || {};
      videoHtml += `
        <div style="background:var(--bg3);border-radius:8px;padding:12px;margin-bottom:8px;">
          <div style="font-size:13px;font-weight:600;color:var(--t1);margin-bottom:8px;">${model.name}</div>
          <div style="display:flex;gap:12px;flex-wrap:wrap;">
            ${RESOLUTIONS.map(res => `
              <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:12px;color:var(--t3);width:50px;">${res}:</span>
                <input type="number" min="0" 
                       data-model-type="video" 
                       data-model-id="${model.id}" 
                       data-resolution="${res}"
                       value="${modelConfig[res] || ''}" 
                       placeholder="默认"
                       style="width:70px;background:var(--bg2);border:1px solid var(--border2);border-radius:6px;color:var(--t1);padding:5px 8px;text-align:center;font-size:12px;" />
              </div>
            `).join('')}
            ${modelConfig && Object.keys(modelConfig).length > 0 ? `
              <button onclick="clearModelPricing('video', '${model.id}')" 
                      style="padding:4px 8px;font-size:12px;color:var(--red);background:none;border:1px solid var(--border2);border-radius:4px;cursor:pointer;">
                清除
              </button>
            ` : ''}
          </div>
        </div>
      `;
    });
  }
  document.getElementById('videoModelCostsList').innerHTML = videoHtml;
  
  // 渲染图片模型成本配置
  let imageHtml = '';
  if (imageModels.length === 0) {
    imageHtml = '<div style="color:var(--t3);font-size:13px;padding:12px;">暂无图片模型配置</div>';
  } else {
    imageModels.forEach(model => {
      const modelConfig = modelPricingConfigs.image?.[model.id] || {};
      imageHtml += `
        <div style="background:var(--bg3);border-radius:8px;padding:12px;margin-bottom:8px;">
          <div style="font-size:13px;font-weight:600;color:var(--t1);margin-bottom:8px;">${model.name}</div>
          <div style="display:flex;gap:12px;flex-wrap:wrap;">
            ${IMAGE_SIZES.map(size => `
              <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:12px;color:var(--t3);width:60px;">${size}:</span>
                <input type="number" min="0" 
                       data-model-type="image" 
                       data-model-id="${model.id}" 
                       data-size="${size}"
                       value="${modelConfig[size] || ''}" 
                       placeholder="默认"
                       style="width:70px;background:var(--bg2);border:1px solid var(--border2);border-radius:6px;color:var(--t1);padding:5px 8px;text-align:center;font-size:12px;" />
              </div>
            `).join('')}
            ${modelConfig && Object.keys(modelConfig).length > 0 ? `
              <button onclick="clearModelPricing('image', '${model.id}')" 
                      style="padding:4px 8px;font-size:12px;color:var(--red);background:none;border:1px solid var(--border2);border-radius:4px;cursor:pointer;">
                清除
              </button>
            ` : ''}
          </div>
        </div>
      `;
    });
  }
  document.getElementById('imageModelCostsList').innerHTML = imageHtml;
}

async function saveModelPricingConfig() {
  const msgEl = document.getElementById('modelPricingMsg');
  msgEl.style.display = 'none';
  
  try {
    // 收集视频模型配置
    const videoInputs = document.querySelectorAll('input[data-model-type="video"]');
    const videoConfigs = {};
    
    videoInputs.forEach(inp => {
      const modelId = inp.dataset.modelId;
      const resolution = inp.dataset.resolution;
      const value = parseInt(inp.value);
      
      if (!isNaN(value) && value >= 0) {
        if (!videoConfigs[modelId]) videoConfigs[modelId] = {};
        videoConfigs[modelId][resolution] = value;
      }
    });
    
    // 保存视频模型配置
    for (const [modelId, costs] of Object.entries(videoConfigs)) {
      await api(`/model-pricing-config/video/${modelId}`, {
        method: 'PUT',
        body: JSON.stringify(costs)
      });
    }
    
    // 收集图片模型配置
    const imageInputs = document.querySelectorAll('input[data-model-type="image"]');
    const imageConfigs = {};
    
    imageInputs.forEach(inp => {
      const modelId = inp.dataset.modelId;
      const size = inp.dataset.size;
      const value = parseInt(inp.value);
      
      if (!isNaN(value) && value >= 0) {
        if (!imageConfigs[modelId]) imageConfigs[modelId] = {};
        imageConfigs[modelId][size] = value;
      }
    });
    
    // 保存图片模型配置
    for (const [modelId, costs] of Object.entries(imageConfigs)) {
      await api(`/model-pricing-config/image/${modelId}`, {
        method: 'PUT',
        body: JSON.stringify(costs)
      });
    }
    
    msgEl.textContent = '模型定价配置已保存';
    msgEl.style.display = 'block';
    setTimeout(() => msgEl.style.display = 'none', 3000);
    
    // 重新加载配置
    modelPricingConfigs = await api('/model-pricing-config');
  } catch (e) {
    showToast('保存失败: ' + (e.message || e), 'error');
  }
}

async function clearModelPricing(modelType, modelId) {
  if (!confirm(`确认清除 ${modelType === 'video' ? '视频' : '图片'}模型 "${modelId}" 的自定义成本配置？`)) return;
  
  try {
    await api(`/model-pricing-config/${modelType}/${modelId}`, {
      method: 'DELETE'
    });
    
    // 清空输入框
    document.querySelectorAll(`input[data-model-type="${modelType}"][data-model-id="${modelId}"]`).forEach(inp => {
      inp.value = '';
    });
    
    // 重新加载配置
    modelPricingConfigs = await api('/model-pricing-config');
    showToast('配置已清除', 'success');
  } catch (e) {
    showToast('清除失败: ' + (e.message || e), 'error');
  }
}

async function savePointsConfig() {
  const area = document.getElementById('pointsConfigArea');
  const cfg = area._rawCfg;
  if (!cfg) return;
  const inputs = area.querySelectorAll('input[data-key]');
  inputs.forEach(inp => {
    const key = inp.dataset.key;
    const res = inp.dataset.res;
    const v = parseFloat(inp.value);
    if (!isNaN(v)) cfg[key][res] = v;
  });
  try {
    await api('/api/admin/points-per-5s', { method: 'PUT', body: JSON.stringify(cfg) });
    showToast('配置已保存', 'success');
    // 通知其他页面刷新积分配置
    if (window.BroadcastChannel) {
      const channel = new BroadcastChannel('pointsConfig');
      channel.postMessage({ type: 'refresh' });
      channel.close();
    }
  } catch (e) { showToast(e.message, 'error'); }
}

let pointsRecordPage = 1;
async function loadPointsRecords(page) {
  if (page) pointsRecordPage = page;
  const search = document.getElementById('pointsRecordSearch').value.trim();
  let url = `/points/records?page=${pointsRecordPage}&page_size=20`;
  if (search && !isNaN(search)) {
    url += `&user_id=${search}`;
  }
  try {
    const d = await api(url);
    let html = '';
    const typeLabels = { earn:'获取', consume:'消耗', expire:'过期', admin_adjust:'管理员调整', subscription:'订阅' };
    const typeBadges = { earn:'badge-success', consume:'badge-danger', expire:'badge-warning', admin_adjust:'badge-info', subscription:'badge-info' };
    d.items.forEach(r => {
      const isPositive = r.points > 0;
      html += `<tr>
        <td>${r.id}</td>
        <td>${r.user_email || r.user_id}</td>
        <td style="color:${isPositive?'var(--green)':'var(--red)'}">${isPositive?'+' : ''}${r.points}</td>
        <td>${r.balance_after}</td>
        <td><span class="badge ${typeBadges[r.type] || 'badge-neutral'}">${typeLabels[r.type] || r.type}</span></td>
        <td>${r.description || '-'}</td>
        <td>${(r.created_at || '').slice(0,19)}</td>
      </tr>`;
    });
    if (!html) html = '<tr><td colspan="7" class="empty-state"><div class="empty-state-text">暂无积分记录</div></td></tr>';
    document.getElementById('pointsRecordTableBody').innerHTML = html;
    renderPagination('pointsRecordPagination', d.total, pointsRecordPage, 20, loadPointsRecords);
  } catch (e) { console.error(e); }
}

async function loadPointsStats() {
  const days = document.getElementById('pointsStatsDays').value;
  try {
    const d = await api(`/points/stats?days=${days}`);
    document.getElementById('pointsStatsGrid').innerHTML = `
      <div class="stat-card"><div class="stat-label">总获取</div><div class="stat-value" style="color:var(--green)">+${d.total_earned}</div></div>
      <div class="stat-card"><div class="stat-label">总消耗</div><div class="stat-value" style="color:var(--red)">-${d.total_consumed}</div></div>
      <div class="stat-card"><div class="stat-label">管理员调整</div><div class="stat-value" style="color:var(--accent)">${d.total_adjusted > 0 ? '+' : ''}${d.total_adjusted}</div></div>
      <div class="stat-card"><div class="stat-label">订阅赠送</div><div class="stat-value" style="color:var(--green)">+${d.total_subscription}</div></div>
    `;
    
    const chartData = d.daily_stats.map(ds => ({
      date: ds.date,
      count: ds.earned - ds.consumed
    }));
    renderChart('pointsStatsChart', chartData);
  } catch (e) { console.error(e); }
}

// Tasks
let taskPage = 1;
async function loadTasks(page) {
  if (page) taskPage = page;
  const status = document.getElementById('taskStatusFilter').value;
  try {
    const d = await api(`/tasks?page=${taskPage}&page_size=20&status=${status}`);
    let html = '';
    d.items.forEach(t => {
      const statusBadge = { pending:'badge-warning', processing:'badge-info', success:'badge-success', failed:'badge-danger', cancelled:'badge-neutral' }[t.status] || 'badge-neutral';
      const statusText = { pending:'待处理', processing:'处理中', success:'成功', failed:'失败', cancelled:'已取消' }[t.status] || t.status;
      html += `<tr>
        <td>${t.id}</td><td>${t.user_email || t.user_id}</td><td>${t.model}</td>
        <td><span class="badge ${statusBadge}">${statusText}</span></td>
        <td>${t.progress || 0}%</td><td>${t.points_cost || 0}</td>
        <td>${(t.created_at||'').slice(0,10)}</td>
        <td>
          ${t.status === 'failed' ? `<a class="action-link" onclick="retryTask(${t.id})">重试</a> ` : ''}
          <a class="action-link" style="color:#f87171" onclick="forceDeleteTask(${t.id})">强制删除</a>
        </td>
      </tr>`;
    });
    if (!html) html = '<tr><td colspan="8" class="empty-state"><div class="empty-state-text">暂无任务数据</div></td></tr>';
    document.getElementById('taskTableBody').innerHTML = html;
    renderPagination('taskPagination', d.total, taskPage, 20, loadTasks);
  } catch (e) { console.error(e); }
}

async function retryTask(id) {
  try {
    await api(`/tasks/${id}/retry`, { method: 'POST' });
    showToast('任务已重试', 'success');
    loadTasks();
  } catch (e) { showToast(e.message, 'error'); }
}

async function forceDeleteTask(id) {
  if (!confirm(`确定强制删除任务 #${id}？若为合成任务的子片段，整个合成任务也会被删除。此操作不可撤销。`)) return;
  try {
    await api(`/tasks/${id}`, { method: 'DELETE' });
    showToast('任务已删除', 'success');
    loadTasks();
  } catch (e) { showToast(e.message, 'error'); }
}

// Init
document.addEventListener('DOMContentLoaded', async () => {
  if (authToken) {
    showApp();
    await loadUsdToPointsRate();
    
    // 绑定价格输入变化事件，实时计算积分
    const priceInput = document.getElementById('planPrice');
    if (priceInput) {
      priceInput.addEventListener('input', () => {
        const priceCents = parseInt(priceInput.value) || 0;
        document.getElementById('planPoints').value = calculatePointsFromPrice(priceCents);
      });
    }
  } else {
    showLogin();
  }
});

// Billing
let billingPage = 1;

async function loadBilling(page) {
  billingPage = page || 1;
  const search = (document.getElementById('billingSearch') || {}).value || '';
  try {
    const d = await api(`/billing?page=${billingPage}&page_size=20`);
    const statusMap = { active: '有效', expired: '已过期', cancelled: '已取消', pending: '待处理' };
    const cycleMap = { monthly: '月付', annual: '年付' };
    let items = d.items || [];
    if (search) items = items.filter(b => (b.user_email || '').includes(search));
    let html = '';
    items.forEach(b => {
      const statusCls = b.status === 'active' ? 'badge-success' : 'badge-error';
      html += `<tr>
        <td>${b.id}</td>
        <td><div>${b.user_email || ''}</div><div style="font-size:11px;color:var(--t3)">${b.user_name || ''}</div></td>
        <td>${b.plan_name || ''}</td>
        <td>${cycleMap[b.billing_cycle] || b.billing_cycle || '-'}</td>
        <td><span class="badge ${statusCls}">${statusMap[b.status] || b.status}</span></td>
        <td>${b.price_cents ? '¥' + (b.price_cents / 100).toFixed(2) : '-'}</td>
        <td>${b.points_per_month || 0}</td>
        <td>${(b.started_at || '').slice(0, 10) || '-'}</td>
        <td>${(b.expires_at || '').slice(0, 10) || '-'}</td>
      </tr>`;
    });
    if (!html) html = '<tr><td colspan="9" class="empty-state"><div class="empty-state-text">暂无账单数据</div></td></tr>';
    document.getElementById('billingTableBody').innerHTML = html;
    renderPagination('billingPagination', d.total, billingPage, 20, loadBilling);
  } catch (e) { console.error(e); }
}

// 窗口大小变化时关闭侧边栏
window.addEventListener('resize', () => {
  if (window.innerWidth > 768) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
  }
});

// ── USDT 支付管理 ───────────────────────────────────────────────────

async function loadUsdtConfig() {
  try {
    const res = await fetch('/api/payments/admin/config', { headers: { 'Authorization': 'Bearer ' + authToken } });
    if (!res.ok) return;
    const cfg = await res.json();
    document.getElementById('usdtAddresses').value = (cfg.addresses || []).join('\n');
    document.getElementById('usdtRate').value = cfg.usd_to_usdt_rate ?? 1.0;
    document.getElementById('usdtEnabled').value = cfg.enabled ? 'true' : 'false';
  } catch (e) { console.error(e); }
}

async function saveUsdtConfig() {
  const addresses = document.getElementById('usdtAddresses').value
    .split('\n').map(s => s.trim()).filter(Boolean);
  const rate = parseFloat(document.getElementById('usdtRate').value) || 1.0;
  const enabled = document.getElementById('usdtEnabled').value === 'true';

  try {
    const res = await fetch('/api/payments/admin/config', {
      method: 'PUT',
      headers: { 'Authorization': 'Bearer ' + authToken, 'Content-Type': 'application/json' },
      body: JSON.stringify({ addresses, usd_to_usdt_rate: rate, enabled }),
    });
    const data = await res.json();
    const msg = document.getElementById('usdtConfigMsg');
    if (res.ok && data.success) {
      msg.textContent = '配置已保存';
      msg.style.color = '#4ade80';
    } else {
      msg.textContent = '保存失败：' + (data.detail || '未知错误');
      msg.style.color = '#f87171';
    }
    msg.style.display = 'block';
    setTimeout(() => { msg.style.display = 'none'; }, 3000);
  } catch (e) { console.error(e); }
}

// ── 积分汇率配置 ───────────────────────────────────────────────────

async function loadPricingConfig() {
  try {
    const res = await fetch('/api/admin/pricing-config', { headers: { 'Authorization': 'Bearer ' + authToken } });
    if (!res.ok) return;
    const cfg = await res.json();
    document.getElementById('pointsRate').value = cfg.usd_to_points ?? 100;
    
    // 加载模型定价配置
    await loadModelsAndPricingConfig();
  } catch (e) { console.error(e); }
}

async function savePricingConfig() {
  const configData = {
    usd_to_points: parseInt(document.getElementById('pointsRate').value) || 100,
  };

  try {
    const res = await fetch('/api/admin/pricing-config', {
      method: 'PUT',
      headers: { 'Authorization': 'Bearer ' + authToken, 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: configData }),
    });
    const result = await res.json();
    const msg = document.getElementById('pricingConfigMsg');
    if (res.ok && result.success) {
      msg.textContent = '配置已保存，不同分辨率/尺寸的生成成本已更新';
      msg.style.color = '#4ade80';
    } else {
      msg.textContent = '保存失败：' + (result.detail || '未知错误');
      msg.style.color = '#f87171';
    }
    msg.style.display = 'block';
    setTimeout(() => { msg.style.display = 'none'; }, 3000);
  } catch (e) { console.error(e); }
}

let _paymentOrdersPage = 1;

async function loadPaymentOrders(page) {
  _paymentOrdersPage = page;
  const status = document.getElementById('paymentStatusFilter')?.value || '';
  const tbody = document.getElementById('paymentOrdersBody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--t3)">加载中...</td></tr>';
  try {
    let url = `/api/payments/admin/orders?page=${page}&page_size=20`;
    if (status) url += `&status=${status}`;
    const res = await fetch(url, { headers: { 'Authorization': 'Bearer ' + authToken } });
    const d = await res.json();
    const statusColors = { pending: '#fbbf24', completed: '#4ade80', expired: '#94a3b8', cancelled: '#f87171', confirming: '#60a5fa' };
    const statusLabels = { pending: '待付款', completed: '已完成', expired: '已过期', cancelled: '已取消', confirming: '确认中' };
    const typeLabels = { subscription: '购买套餐', points: '充值积分' };
    let html = '';
    for (const o of (d.items || [])) {
      const sc = statusColors[o.status] || '#94a3b8';
      const sl = statusLabels[o.status] || o.status;
      const txShort = o.tx_hash ? o.tx_hash.slice(0, 12) + '…' : '-';
      const addrShort = o.receive_address ? o.receive_address.slice(0, 10) + '…' : '-';
      html += `<tr>
        <td style="font-size:11px;font-family:monospace;">${o.order_no}</td>
        <td>${o.user_id}</td>
        <td>${typeLabels[o.payment_type] || o.payment_type}</td>
        <td style="color:#fbbf24;font-weight:600;">${o.amount_usdt} USDT</td>
        <td title="${o.receive_address}" style="font-size:11px;font-family:monospace;">${addrShort}</td>
        <td title="${o.tx_hash || ''}" style="font-size:11px;font-family:monospace;">${txShort}</td>
        <td><span style="color:${sc};font-weight:600;">${sl}</span></td>
        <td style="font-size:11px;">${o.created_at ? o.created_at.replace('T',' ').slice(0,16) : '-'}</td>
        <td>
          ${o.status === 'pending' ? `<button class="action-btn" onclick="adminConfirmOrder('${o.order_no}')">手动确认</button>` : ''}
        </td>
      </tr>`;
    }
    if (!html) html = '<tr><td colspan="9" class="empty-state"><div class="empty-state-text">暂无支付订单</div></td></tr>';
    tbody.innerHTML = html;
    renderPagination('paymentOrdersPagination', d.total, page, 20, loadPaymentOrders);
  } catch (e) { console.error(e); tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--t3)">加载失败</td></tr>'; }
}

async function adminConfirmOrder(orderNo) {
  const txHash = prompt('请输入交易哈希（tx_hash）：');
  if (!txHash) return;
  try {
    const res = await fetch(`/api/payments/admin/orders/${orderNo}/confirm?tx_hash=${encodeURIComponent(txHash)}`, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + authToken },
    });
    const data = await res.json();
    if (res.ok && data.success) {
      alert('订单已手动确认完成');
      loadPaymentOrders(_paymentOrdersPage);
    } else {
      alert('操作失败：' + (data.detail || '未知错误'));
    }
  } catch (e) { alert('请求失败'); }
}
// ── Contact Messages ─────────────────────────────────────────────────────

let _contactPage = 1;
let _currentContactId = null;
let _currentContactStatus = 'open';

async function loadContactMessages(page) {
  _contactPage = page;
  const tbody = document.getElementById('contactMessagesBody');
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--t3)">加载中...</td></tr>';
  const unreadOnly = document.getElementById('contactUnreadOnly').checked;
  try {
    const params = new URLSearchParams({ page, page_size: 20 });
    if (unreadOnly) params.set('unread_only', 'true');
    const res = await fetch('/api/admin/contact-messages?' + params, {
      headers: { 'Authorization': 'Bearer ' + authToken }
    });
    const d = await res.json();
    let html = '';
    for (const m of (d.items || [])) {
      const isClosed = m.status === 'closed';
      const statusBadge = isClosed
        ? '<span style="font-size:11px;color:var(--t3);">已关闭</span>'
        : m.reply_count > 0
          ? '<span style="font-size:11px;color:#4ade80;font-weight:600;">已回复</span>'
          : m.is_read
            ? '<span style="font-size:11px;color:var(--t3);">已读</span>'
            : '<span style="font-size:11px;color:#a78bfa;font-weight:600;">未读</span>';
      const shortMsg = m.message.length > 40 ? m.message.slice(0, 40) + '…' : m.message;
      const attCount = (m.attachments || []).length;
      html += `<tr style="${m.is_read || isClosed ? '' : 'background:rgba(167,139,250,.06);'}">
        <td>${m.id}</td>
        <td>${m.email}</td>
        <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${m.subject}">${m.subject}</td>
        <td style="max-width:180px;color:var(--t3);font-size:12px;">${shortMsg}${attCount ? ` <span style="color:var(--accent)">📎${attCount}</span>` : ''}${m.reply_count > 0 ? ` <span style="color:var(--t3)">💬${m.reply_count}</span>` : ''}</td>
        <td>${statusBadge}</td>
        <td style="font-size:11px;">${m.created_at ? m.created_at.replace('T',' ').slice(0,16) : '-'}</td>
        <td>
          <button class="action-btn" onclick="viewContactDetail(${m.id})">查看/回复</button>
          <button class="action-btn danger" onclick="deleteContactMessage(${m.id})">删除</button>
        </td>
      </tr>`;
    }
    if (!html) html = '<tr><td colspan="7" class="empty-state"><div class="empty-state-text">暂无工单</div></td></tr>';
    tbody.innerHTML = html;
    renderPagination('contactMessagesPagination', d.total, page, 20, loadContactMessages);
  } catch (e) {
    console.error(e);
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--t3)">加载失败</td></tr>';
  }
}

function _renderAttachments(attachments) {
  let html = '';
  for (const a of (attachments || [])) {
    if (a.mime_type && a.mime_type.startsWith('image/')) {
      html += `<a href="${a.url}" target="_blank"><img src="${a.url}" style="max-width:80px;max-height:64px;border-radius:6px;object-fit:cover;border:1px solid var(--bg4);"></a>`;
    } else {
      const icon = a.mime_type && a.mime_type.startsWith('video/') ? '🎬' : '📄';
      html += `<a href="${a.url}" target="_blank" style="display:inline-flex;align-items:center;gap:4px;padding:4px 8px;background:var(--bg3);border-radius:6px;font-size:11px;color:var(--accent);">${icon} ${a.filename || '附件'}</a>`;
    }
  }
  return html ? `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;">${html}</div>` : '';
}

async function viewContactDetail(id) {
  _currentContactId = id;
  const res = await fetch(`/api/admin/contact-messages/${id}`, {
    headers: { 'Authorization': 'Bearer ' + authToken }
  });
  if (!res.ok) { alert('加载失败'); return; }
  const m = await res.json();
  _currentContactStatus = m.status;

  document.getElementById('cdEmail').textContent = m.email;
  document.getElementById('cdSubject').textContent = m.subject;

  const isClosed = m.status === 'closed';
  const badge = document.getElementById('cdStatusBadge');
  badge.textContent = isClosed ? '已关闭' : '进行中';
  badge.style.background = isClosed ? 'rgba(107,114,128,.2)' : 'rgba(74,222,128,.15)';
  badge.style.color = isClosed ? 'var(--t3)' : '#4ade80';

  document.getElementById('cdCloseBtn').style.display = isClosed ? 'none' : '';
  document.getElementById('cdReopenBtn').style.display = isClosed ? '' : 'none';
  document.getElementById('cdReplyBtn').disabled = isClosed;
  document.getElementById('cdReplyInput').disabled = isClosed;
  document.getElementById('cdReplyInput').placeholder = isClosed ? '工单已关闭' : '输入回复内容...';

  // 渲染对话线程：首条消息 + 所有回复
  const thread = document.getElementById('cdThread');
  let html = '';

  // 首条消息（用户）
  html += `<div style="display:flex;flex-direction:column;align-items:flex-start;gap:2px;">
    <div style="font-size:11px;color:var(--t3);margin-left:2px;">用户 · ${m.created_at ? m.created_at.replace('T',' ').slice(0,16) : ''}</div>
    <div style="max-width:85%;background:var(--bg3);border-radius:0 10px 10px 10px;padding:10px 12px;font-size:13px;color:var(--t2);white-space:pre-wrap;line-height:1.6;">${escHtml(m.message)}</div>
    ${_renderAttachments(m.attachments)}
  </div>`;

  for (const r of (m.replies || [])) {
    const isAdmin = r.sender === 'admin';
    html += `<div style="display:flex;flex-direction:column;align-items:${isAdmin ? 'flex-end' : 'flex-start'};gap:2px;">
      <div style="font-size:11px;color:var(--t3);margin-${isAdmin ? 'right' : 'left'}:2px;">${isAdmin ? '管理员' : '用户'} · ${r.created_at ? r.created_at.replace('T',' ').slice(0,16) : ''}</div>
      <div style="max-width:85%;background:${isAdmin ? 'rgba(99,102,241,.2)' : 'var(--bg3)'};border-radius:${isAdmin ? '10px 0 10px 10px' : '0 10px 10px 10px'};padding:10px 12px;font-size:13px;color:var(--t1);white-space:pre-wrap;line-height:1.6;">${escHtml(r.content)}</div>
      ${_renderAttachments(r.attachments)}
    </div>`;
  }

  thread.innerHTML = html;
  thread.scrollTop = thread.scrollHeight;

  document.getElementById('cdReplyInput').value = '';
  document.getElementById('contactDetailModal').style.display = 'flex';
  loadContactMessages(_contactPage);
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function closeContactDetail() {
  document.getElementById('contactDetailModal').style.display = 'none';
}

async function submitContactReply() {
  const content = document.getElementById('cdReplyInput').value.trim();
  if (!content) { alert('请输入回复内容'); return; }
  const btn = document.getElementById('cdReplyBtn');
  btn.disabled = true;
  btn.textContent = '发送中...';
  try {
    const res = await fetch(`/api/admin/contact-messages/${_currentContactId}/reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + authToken },
      body: JSON.stringify({ content }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast('回复已发送');
      viewContactDetail(_currentContactId);
    } else {
      alert('发送失败：' + (data.detail || '未知错误'));
      btn.disabled = false;
      btn.textContent = '发送回复';
    }
  } catch (e) { alert('请求失败'); btn.disabled = false; btn.textContent = '发送回复'; }
}

async function closeTicket() {
  if (!confirm('确认关闭该工单？关闭后用户无法继续回复。')) return;
  const res = await fetch(`/api/admin/contact-messages/${_currentContactId}/close`, {
    method: 'PUT',
    headers: { 'Authorization': 'Bearer ' + authToken }
  });
  const data = await res.json();
  if (res.ok && data.success) { showToast('工单已关闭'); viewContactDetail(_currentContactId); }
  else alert('操作失败：' + (data.detail || ''));
}

async function reopenTicket() {
  const res = await fetch(`/api/admin/contact-messages/${_currentContactId}/reopen`, {
    method: 'PUT',
    headers: { 'Authorization': 'Bearer ' + authToken }
  });
  const data = await res.json();
  if (res.ok && data.success) { showToast('工单已重新开启'); viewContactDetail(_currentContactId); }
  else alert('操作失败：' + (data.detail || ''));
}

async function deleteContactMessage(id) {
  if (!confirm('确认删除该工单？')) return;
  try {
    const res = await fetch(`/api/admin/contact-messages/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + authToken }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      loadContactMessages(_contactPage);
    } else {
      alert('删除失败：' + (data.detail || '未知错误'));
    }
  } catch (e) { alert('请求失败'); }
}

async function loadSiteConfig() {
  try {
    const res = await fetch('/api/admin/site-config', {
      headers: { 'Authorization': 'Bearer ' + authToken }
    });
    if (!res.ok) return;
    const d = await res.json();
    document.getElementById('settingTelegramUrl').value = d.telegram_url || '';
    document.getElementById('settingTelegramName').value = d.telegram_name || '';
  } catch (e) {}
}

async function saveSiteConfig() {
  const telegram_url = document.getElementById('settingTelegramUrl').value.trim();
  const telegram_name = document.getElementById('settingTelegramName').value.trim();
  try {
    const res = await fetch('/api/admin/site-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + authToken },
      body: JSON.stringify({ telegram_url, telegram_name }),
    });
    const d = await res.json();
    if (res.ok && d.success) showToast('设置已保存');
    else alert('保存失败：' + (d.detail || ''));
  } catch (e) { alert('请求失败'); }
}


// __ Models Management ________________________________________________________

let _modelsCfg = { video: [], image: [] };
let _currentModelTab = 'video';

function switchModelTab(tab) {
  _currentModelTab = tab;
  document.querySelectorAll('[id^="model-tab-content-"]').forEach(el => el.style.display = 'none');
  ['video','image'].forEach(t => {
    const btn = document.getElementById('model-tab-' + t);
    if (btn) btn.classList.remove('active');
  });
  document.getElementById('model-tab-content-' + tab).style.display = '';
  const activeBtn = document.getElementById('model-tab-' + tab);
  if (activeBtn) activeBtn.classList.add('active');
}

async function loadModelsConfig() {
  try {
    _modelsCfg = await api('/models-config');
    renderModelTable('video');
    renderModelTable('image');
  } catch (e) { console.error(e); }
}

const _inpStyle = 'background:var(--bg3);border:1px solid var(--border2);border-radius:6px;color:var(--t1);padding:4px 8px;font-size:12px;';
const _chkStyle = 'width:16px;height:16px;cursor:pointer;';

function renderModelTable(type) {
  const models = (_modelsCfg[type] || []);
  const bodyId = type === 'video' ? 'videoModelBody' : 'imageModelBody';
  const tbody = document.getElementById(bodyId);
  if (!tbody) return;
  let html = '';
  models.forEach((m, idx) => {
    const extraCols = type === 'video'
      ? `<td><input type="text" data-field="resolutions" data-type="${type}" data-idx="${idx}" value="${(m.resolutions||[]).join(',')}" style="${_inpStyle}width:130px;" placeholder="480p,720p,1080p"/></td>`
        + `<td><input type="text" data-field="durations" data-type="${type}" data-idx="${idx}" value="${(m.durations||[]).join(',')}" style="${_inpStyle}width:70px;" placeholder="5,10"/></td>`
      : `<td><input type="text" data-field="sizes" data-type="${type}" data-idx="${idx}" value="${(m.sizes||[]).join(',')}" style="${_inpStyle}width:190px;" placeholder="512x512,1024x1024"/></td>`
        + `<td>-</td>`;
    html += `<tr>
      <td><input type="number" data-field="sort" data-type="${type}" data-idx="${idx}" value="${m.sort!=null?m.sort:idx}" style="${_inpStyle}width:50px;"/></td>
      <td><input type="text" data-field="id" data-type="${type}" data-idx="${idx}" value="${m.id||''}" style="${_inpStyle}width:200px;" placeholder="endpoint-id"/></td>
      <td><input type="text" data-field="name" data-type="${type}" data-idx="${idx}" value="${m.name||''}" style="${_inpStyle}width:130px;" placeholder="显示名称"/></td>
      ${extraCols}
      <td style="text-align:center;"><input type="checkbox" data-field="is_default" data-type="${type}" data-idx="${idx}" ${m.is_default?'checked':''} style="${_chkStyle}"/></td>
      <td style="text-align:center;"><input type="checkbox" data-field="enabled" data-type="${type}" data-idx="${idx}" ${m.enabled!==false?'checked':''} style="${_chkStyle}"/></td>
      <td><a class="action-link danger" onclick="removeModelRow('${type}',${idx})">删除</a></td>
    </tr>`;
  });
  tbody.innerHTML = html || '<tr><td colspan="8" class="empty-state"><div class="empty-state-text">暂无模型</div></td></tr>';
}

function _collectModelTable(type) {
  const bodyId = type === 'video' ? 'videoModelBody' : 'imageModelBody';
  const tbody = document.getElementById(bodyId);
  if (!tbody) return _modelsCfg[type] || [];
  const map = {};
  tbody.querySelectorAll('input[data-field]').forEach(inp => {
    const idx = parseInt(inp.dataset.idx);
    if (!map[idx]) map[idx] = {};
    const field = inp.dataset.field;
    if (inp.type === 'checkbox') {
      map[idx][field] = inp.checked;
    } else if (field === 'resolutions' || field === 'sizes') {
      map[idx][field] = inp.value.split(',').map(s => s.trim()).filter(Boolean);
    } else if (field === 'durations') {
      map[idx][field] = inp.value.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));
    } else if (field === 'sort') {
      map[idx][field] = parseInt(inp.value) || 0;
    } else {
      map[idx][field] = inp.value.trim();
    }
  });
  return Object.keys(map).sort((a,b)=>a-b).map(k => map[k]);
}

function addModelRow(type) {
  _modelsCfg[type] = _collectModelTable(type);
  const m = type === 'video'
    ? { id:'', name:'', enabled:true, is_default:false, resolutions:['480p','720p','1080p'], durations:[5,10], sort:_modelsCfg[type].length }
    : { id:'', name:'', enabled:true, is_default:false, sizes:['512x512','1024x1024','2048x2048'], sort:_modelsCfg[type].length };
  _modelsCfg[type].push(m);
  renderModelTable(type);
}

function removeModelRow(type, idx) {
  _modelsCfg[type] = _collectModelTable(type);
  _modelsCfg[type].splice(idx, 1);
  renderModelTable(type);
}

async function saveModelsConfig(type) {
  _modelsCfg[type] = _collectModelTable(type);
  try {
    await api('/models-config', { method: 'PUT', body: JSON.stringify(_modelsCfg) });
    showToast('模型配置已保存', 'success');
  } catch (e) { showToast(e.message, 'error'); }
}

// __ Points Packages __________________________________________________________

let _pkgList = [];

async function loadPackagesConfig() {
  try {
    _pkgList = await api('/points-packages');
    renderPackagesTable();
  } catch (e) { console.error(e); }
}

function renderPackagesTable() {
  const tbody = document.getElementById('packagesTableBody');
  if (!tbody) return;
  const s = _inpStyle;
  let html = '';
  _pkgList.forEach((pkg, idx) => {
    html += `<tr>
      <td><input type="text" data-field="key" data-idx="${idx}" value="${pkg.key||''}" style="${s}width:80px;" placeholder="small"/></td>
      <td><input type="text" data-field="name" data-idx="${idx}" value="${pkg.name||''}" style="${s}width:110px;" placeholder="套餐名称"/></td>
      <td><input type="number" data-field="points" data-idx="${idx}" value="${pkg.points||0}" style="${s}width:80px;"/></td>
      <td><input type="number" data-field="price_cents" data-idx="${idx}" value="${pkg.price_cents||0}" style="${s}width:80px;"/></td>
      <td style="text-align:center;"><input type="checkbox" data-field="featured" data-idx="${idx}" ${pkg.featured?'checked':''} style="${_chkStyle}"/></td>
      <td><a class="action-link danger" onclick="removePackageRow(${idx})">删除</a></td>
    </tr>`;
  });
  tbody.innerHTML = html || '<tr><td colspan="6" class="empty-state"><div class="empty-state-text">暂无积分包</div></td></tr>';
}

function _collectPkgTable() {
  const tbody = document.getElementById('packagesTableBody');
  if (!tbody) return _pkgList;
  const map = {};
  tbody.querySelectorAll('input[data-field]').forEach(inp => {
    const idx = parseInt(inp.dataset.idx);
    if (!map[idx]) map[idx] = {};
    const field = inp.dataset.field;
    if (inp.type === 'checkbox') map[idx][field] = inp.checked;
    else if (field === 'points' || field === 'price_cents') map[idx][field] = parseInt(inp.value) || 0;
    else map[idx][field] = inp.value.trim();
  });
  return Object.keys(map).sort((a,b)=>a-b).map(k => map[k]);
}

function addPackageRow() {
  _pkgList = _collectPkgTable();
  _pkgList.push({ key:'', name:'', points:0, price_cents:0, featured:false });
  renderPackagesTable();
}

function removePackageRow(idx) {
  _pkgList = _collectPkgTable();
  _pkgList.splice(idx, 1);
  renderPackagesTable();
}

async function savePackagesConfig() {
  _pkgList = _collectPkgTable();
  try {
    await api('/points-packages', { method: 'PUT', body: JSON.stringify(_pkgList) });
    showToast('积分包配置已保存', 'success');
  } catch (e) { showToast(e.message, 'error'); }
}
