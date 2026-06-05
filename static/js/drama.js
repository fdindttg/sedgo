/**
 * 短剧工作室 - 前端控制逻辑
 *
 * 工作流：
 *   创建项目 → 生成剧本（策划Agent）→ 拆解分镜（导演Agent）→ 批量渲染 → 审片 → 成片导出
 */

const API_BASE = '/api/drama';
let currentProjectId = null;
let currentEpisodeId = null;

// ── Auth Helper ──
function getAuthHeaders() {
  const token = localStorage.getItem('token');
  const apiKey = localStorage.getItem('api_key');
  if (token) return { 'Authorization': 'Bearer ' + token };
  if (apiKey) return { 'X-API-Key': apiKey };
  return {};
}

async function api(path, opts = {}) {
  const url = API_BASE + path;
  const res = await fetch(url, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) {
    alert('请先登录');
    window.location.href = '/';
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || '请求失败');
  }
  return res.json();
}

// ── Page Navigation ──
function showProjectList() {
  document.getElementById('projectListView').style.display = 'block';
  document.getElementById('projectDetailView').style.display = 'none';
  currentProjectId = null;
  currentEpisodeId = null;
  loadProjects();
}

function showProjectDetail(projectId) {
  document.getElementById('projectListView').style.display = 'none';
  document.getElementById('projectDetailView').style.display = 'block';
  document.getElementById('scenePanel').style.display = 'none';
  document.getElementById('exportPanel').style.display = 'none';
  currentProjectId = projectId;
  loadProjectDetail(projectId);
}

// ── Modal ──
function showCreateModal() {
  document.getElementById('createModal').classList.add('active');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('active');
}

// ── Project CRUD ──
async function loadProjects() {
  const grid = document.getElementById('projectGrid');
  grid.innerHTML = '<div class="loading"><div class="spinner"></div><p>加载中...</p></div>';

  try {
    const data = await api('/projects');
    const projects = data.projects || [];

    if (projects.length === 0) {
      grid.innerHTML = `<div class="empty-state">
        <div class="icon">🎬</div>
        <h3 style="margin:0 0 8px;">还没有短剧项目</h3>
        <p>创建你的第一个短剧项目，AI 将帮助你完成从剧本到成片的全部流程</p>
      </div>`;
      return;
    }

    grid.innerHTML = projects.map(p => {
      const statusClass = `status-${p.status}`;
      const statusLabels = { draft: '草稿', generating: '生成中', completed: '已完成', failed: '失败' };
      return `<div class="project-card" onclick="showProjectDetail(${p.id})">
        <span class="genre-tag">${p.genre || '短剧'}</span>
        <h3>${p.title || '未命名项目'}</h3>
        <p style="font-size:13px; color:rgba(255,255,255,0.6); margin:4px 0;">${p.logline || '暂无梗概'}</p>
        <div class="meta">${p.episode_count || 0} / ${p.total_episodes} 集</div>
        <span class="status-badge ${statusClass}">${statusLabels[p.status] || p.status}</span>
      </div>`;
    }).join('');
  } catch (e) {
    grid.innerHTML = `<div class="empty-state"><p>加载失败：${e.message}</p></div>`;
  }
}

async function createProject() {
  const title = document.getElementById('newTitle').value.trim();
  const genre = document.getElementById('newGenre').value;
  const logline = document.getElementById('newLogline').value.trim();
  const totalEpisodes = parseInt(document.getElementById('newEpisodes').value) || 10;

  if (!title) {
    alert('请输入项目名称');
    return;
  }

  try {
    await api('/projects', {
      method: 'POST',
      body: JSON.stringify({ title, genre, logline, total_episodes: totalEpisodes }),
    });
    closeModal('createModal');
    document.getElementById('newTitle').value = '';
    document.getElementById('newLogline').value = '';
    loadProjects();
  } catch (e) {
    alert('创建失败：' + e.message);
  }
}

// ── Project Detail ──
let _currentProjectData = null;

async function loadProjectDetail(projectId) {
  const titleEl = document.getElementById('detailTitle');
  const statusEl = document.getElementById('detailStatus');
  const episodeList = document.getElementById('episodeList');
  episodeList.innerHTML = '<div class="loading"><div class="spinner"></div><p>加载中...</p></div>';

  try {
    const project = await api('/projects/' + projectId);
    _currentProjectData = project;

    titleEl.textContent = project.title + (project.genre ? ` (${project.genre})` : '');
    statusEl.textContent = project.status === 'draft' ? '草稿' : project.status === 'generating' ? '生成中' : project.status === 'completed' ? '已完成' : '失败';
    statusEl.className = 'status-badge status-' + project.status;

    if (!project.episodes || project.episodes.length === 0) {
      episodeList.innerHTML = '<div class="empty-state"><p>还没有剧集，点击"生成剧本"开始创作</p></div>';
      return;
    }

    episodeList.innerHTML = project.episodes.map(ep => {
      const epStatus = ep.status === 'draft' ? '📝' : ep.status === 'generating' ? '⏳' : ep.status === 'completed' ? '✅' : '❌';
      return `<div class="episode-card" onclick="showEpisodeDetail(${projectId}, ${ep.id})">
        <div class="ep-num">${epStatus} 第 ${ep.episode_number} 集</div>
        <div class="ep-title">${ep.title || '未命名'}</div>
        ${ep.hook ? `<div class="ep-hook">🎣 ${ep.hook.substring(0, 60)}${ep.hook.length > 60 ? '...' : ''}</div>` : ''}
        <div style="font-size:12px; margin-top:4px; color:rgba(255,255,255,0.4);">
          ${ep.scene_count || 0} 个分镜
          <span style="margin-left:12px;">${ep.cliffhanger ? '🔚 有悬念' : ''}</span>
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    episodeList.innerHTML = `<div class="empty-state"><p>加载失败：${e.message}</p></div>`;
  }
}

// ── Script Generation (Agent 1) ──
async function generateScript() {
  if (!currentProjectId) return;

  document.getElementById('detailActions').innerHTML = '<div class="loading"><div class="spinner"></div><p>AI 策划中...</p></div>';

  try {
    const result = await api('/projects/' + currentProjectId + '/generate-script', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    alert('✅ ' + result.message);
    loadProjectDetail(currentProjectId);
  } catch (e) {
    alert('生成失败：' + e.message);
    resetActions();
  }
}

// ── Storyboard Breakdown (Agent 2) ──
async function generateBreakdown() {
  if (!currentEpisodeId) {
    alert('请先选择一个剧集');
    return;
  }

  try {
    const result = await api('/episodes/' + currentEpisodeId + '/breakdown', {
      method: 'POST',
    });
    alert('✅ ' + result.message);
    showEpisodeDetail(currentProjectId, currentEpisodeId);
  } catch (e) {
    alert('拆解失败：' + e.message);
  }
}

// ── Episode Detail ──
async function showEpisodeDetail(projectId, episodeId) {
  currentEpisodeId = episodeId;
  const panel = document.getElementById('scenePanel');
  panel.style.display = 'block';
  panel.innerHTML = '<div class="loading"><div class="spinner"></div><p>加载场景...</p></div>';
  document.getElementById('exportPanel').style.display = 'none';

  try {
    const ep = await api('/episodes/' + episodeId);

    let html = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <div>
          <strong>第 ${ep.episode_number} 集</strong>
          <span style="margin-left:8px; font-size:13px; color:rgba(255,255,255,0.5);">${ep.title || ''}</span>
        </div>
        <button class="action-btn btn-secondary" onclick="exportEpisode(${episodeId})">📋 导出</button>
      </div>
      ${ep.hook ? `<div class="field"><div class="field-label">🎣 黄金钩子</div><div class="field-value">${ep.hook}</div></div>` : ''}
      ${ep.cliffhanger ? `<div class="field"><div class="field-label">🔚 悬念</div><div class="field-value">${ep.cliffhanger}</div></div>` : ''}
      <div class="action-bar" style="margin:8px 0;">
        <button class="action-btn btn-primary" onclick="generateBreakdown()">🎯 拆解分镜</button>
        <button class="action-btn btn-success" onclick="renderEpisode(${episodeId})">🎬 渲染本集</button>
      </div>
    `;

    if (ep.emotion_arc && ep.emotion_arc.length > 0) {
      html += `<div class="field"><div class="field-label">📈 情绪走势</div><div class="field-value">`;
      html += ep.emotion_arc.map(e => `${'▸'} ${e.emotion}${e.intensity ? ` (强度:${e.intensity})` : ''}`).join(' → ');
      html += `</div></div>`;
    }

    // Scenes
    const scenes = ep.scenes || [];
    if (scenes.length > 0) {
      html += `<div class="field"><div class="field-label">🎥 分镜场景 (${scenes.length})</div></div>`;
      html += `<div class="scene-list">`;
      scenes.forEach(s => {
        const sStatus = s.status === 'draft' ? '📝' : s.status === 'generating' ? '⏳' : s.status === 'completed' ? '✅' : '❌';
        html += `<div class="scene-card">
          <div class="scene-header">
            <span>${sStatus} 场景 #${s.scene_number} ${s.location ? '— ' + s.location : ''}</span>
            <span style="font-size:12px; color:rgba(255,255,255,0.4);">${s.duration || 5}s</span>
          </div>
          ${s.camera_instruction ? `<div style="font-size:12px; color:var(--drama-secondary);">📷 ${s.camera_instruction}</div>` : ''}
          <div class="scene-prompt">${s.prompt_text ? s.prompt_text.substring(0, 120) + (s.prompt_text.length > 120 ? '...' : '') : '无提示词'}</div>
          ${s.quality_score ? `<div style="font-size:12px; margin-top:4px;">评分: ${'⭐'.repeat(Math.min(s.quality_score, 5))}${s.quality_score > 5 ? ' (' + s.quality_score + '/10)' : ''}</div>` : ''}
          ${s.selected_url ? `<div class="scene-video"><video src="${s.selected_url}" controls></video></div>` : ''}
          ${s.video_urls && s.video_urls.length > 0 ? `<div style="font-size:12px; margin-top:4px; color:rgba(255,255,255,0.4);">${s.video_urls.length} 个候选 ${s.selected_url ? '✅' : '❌ 未选择'}</div>` : ''}
          ${s.has_defect ? `<div style="font-size:12px; color:var(--drama-primary); margin-top:4px;">⚠️ 检测到缺陷</div>` : ''}
        </div>`;
      });
      html += `</div>`;
    }

    panel.innerHTML = html;
  } catch (e) {
    panel.innerHTML = `<p style="color:var(--drama-primary);">加载失败：${e.message}</p>`;
  }
}

// ── Batch Render ──
async function startRender() {
  if (!currentProjectId) return;
  const scenes = prompt('请输入要渲染的场景ID（用逗号隔开，留空=全部，例如：1,3,5）');
  renderEpisode(null, scenes);
}

async function renderEpisode(episodeId, sceneIdsStr) {
  const body = {};
  if (episodeId) {
    body.episode_ids = [episodeId];
  }
  if (sceneIdsStr) {
    body.scene_ids = sceneIdsStr.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));
  }

  try {
    const result = await api('/render', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    alert('✅ ' + result.message);
    if (currentEpisodeId) showEpisodeDetail(currentProjectId, currentEpisodeId);
  } catch (e) {
    alert('渲染失败：' + e.message);
  }
}

// ── Sync Task Status ──
async function syncTasks() {
  try {
    const result = await api('/tasks/sync');
    alert(`同步完成：${result.synced} 个场景已更新`);
    if (currentProjectId) loadProjectDetail(currentProjectId);
    if (currentEpisodeId) showEpisodeDetail(currentProjectId, currentEpisodeId);
  } catch (e) {
    alert('同步失败：' + e.message);
  }
}

// ── Export ──
async function exportEpisode(episodeId) {
  try {
    const manifest = await api('/episodes/' + episodeId + '/export');
    const panel = document.getElementById('exportPanel');
    panel.style.display = 'block';

    let html = `
      <div style="margin-bottom:8px;">
        <strong>${manifest.title || '第' + manifest.episode_number + '集'}</strong>
        <span style="margin-left:12px; font-size:13px; color:rgba(255,255,255,0.5);">
          总时长：${manifest.total_duration || 0}s | ${manifest.clip_count || 0} 个片段
        </span>
      </div>
    `;

    const clips = manifest.clips || [];
    if (clips.length === 0) {
      html += '<p style="color:rgba(255,255,255,0.5);">暂无可用视频片段</p>';
    } else {
      html += '<div class="scene-list">';
      clips.forEach((c, i) => {
        html += `<div class="scene-card">
          <div style="font-size:13px;">片段 ${i+1} — 场景 #${c.scene_number} (${c.duration || 0}s)</div>
          ${c.camera ? `<div style="font-size:12px; color:var(--drama-secondary);">📷 ${c.camera}</div>` : ''}
          ${c.video_url ? `<div class="scene-video"><video src="${c.video_url}" controls></video></div>` : '<div style="color:var(--drama-primary);">❌ 无视频</div>'}
        </div>`;
      });
      html += '</div>';
    }

    document.getElementById('exportContent').innerHTML = html;
  } catch (e) {
    alert('导出失败：' + e.message);
  }
}

// ── Reset Actions ──
function resetActions() {
  if (!currentProjectId) return;
  document.getElementById('detailActions').innerHTML = `
    <button class="action-btn btn-primary" onclick="generateScript()">📝 生成剧本</button>
    <button class="action-btn btn-secondary" onclick="generateBreakdown()">🎯 拆解分镜</button>
    <button class="action-btn btn-success" onclick="startRender()">🎬 批量渲染</button>
    <button class="action-btn btn-secondary" onclick="syncTasks()">🔄 同步状态</button>
  `;
}

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  // Read URL parameters
  const params = new URLSearchParams(window.location.search);
  const promptParam = params.get('prompt');
  const projectId = params.get('id');

  if (promptParam) {
    // Pre-fill the create modal with the prompt as logline
    document.getElementById('newLogline').value = promptParam;
    // Auto-generate a title from first 20 chars
    var title = promptParam.substring(0, 20) + (promptParam.length > 20 ? '...' : '');
    document.getElementById('newTitle').value = title || '新短剧项目';
  }

  if (projectId) {
    // Directly open project detail
    showProjectDetail(parseInt(projectId));
  } else {
    loadProjects();
  }

  // Auto-open create modal if prompt was passed and no project id
  if (promptParam && !projectId) {
    setTimeout(function() {
      showCreateModal();
    }, 500);
  }

  // Drama upload button → trigger file picker
  var uploadBtn = document.getElementById('drama-upload-btn');
  if (uploadBtn) {
    uploadBtn.addEventListener('click', function() {
      document.getElementById('drama-script-input').click();
    });
  }

  // Handle script file selection
  var scriptInput = document.getElementById('drama-script-input');
  if (scriptInput) {
    scriptInput.addEventListener('change', function(e) {
      var file = e.target.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function(ev) {
        var content = ev.target.result;
        document.getElementById('newLogline').value = content.substring(0, 500);
        // Auto-generate title from first line or filename
        var firstLine = content.split('\n')[0].trim().substring(0, 30);
        var titleInput = document.getElementById('newTitle');
        if (!titleInput.value) {
          titleInput.value = firstLine || file.name.replace(/\.[^.]+$/, '');
        }
      };
      reader.readAsText(file);
      // Reset input so same file can be selected again
      e.target.value = '';
    });
  }
});
