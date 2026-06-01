const btn = document.getElementById('btn');
const msg = document.getElementById('msg');
const dbg = document.getElementById('dbg');

function log(s) { dbg.style.display='block'; dbg.textContent += s + '\n'; }

btn.addEventListener('click', async () => {
  const email = document.getElementById('e').value.trim();
  const password = document.getElementById('p').value;
  
  if (!email || !password) { showMsg('请输入邮箱和密码', 'info'); return; }
  
  btn.disabled = true;
  btn.textContent = '登录中...';
  showMsg('正在请求 /api/auth/login ...', 'info');
  log('POST /api/auth/login');
  log('Body: ' + JSON.stringify({email, password}));
  
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email, password})
    });
    log('Status: ' + res.status);
    
    const text = await res.text();
    log('Response: ' + text.substring(0, 200));
    
    let data;
    try { data = JSON.parse(text); } catch(e) { data = {raw: text}; }
    
    if (!res.ok) {
      showMsg('❌ ' + (data.detail || 'HTTP ' + res.status), 'error');
    } else if (!data.access_token) {
      showMsg('❌ 响应无 access_token', 'error');
    } else {
      log('Token: ' + data.access_token.substring(0, 30) + '...');
      log('Role: ' + (data.user ? data.user.role : 'N/A'));
      
      if (data.user && data.user.role === 'admin') {
        showMsg('✅ 登录成功！角色: ' + data.user.role, 'success');
        localStorage.setItem('sd_admin_token', data.access_token);
        // Redirect to admin dashboard
        setTimeout(() => { window.location.href = '/admin.html'; }, 800);
      } else {
        showMsg('❌ 不是管理员 (role=' + (data.user?data.user.role:'N/A') + ')', 'error');
      }
    }
  } catch(e) {
    log('ERROR: ' + e.message);
    showMsg('❌ 网络错误: ' + e.message, 'error');
  }
  
  btn.disabled = false;
  btn.textContent = '登 录';
});

function showMsg(txt, cls) {
  msg.textContent = txt;
  msg.className = cls;
}