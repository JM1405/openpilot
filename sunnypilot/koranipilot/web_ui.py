"""Self-contained Korean mobile Web UI HTML for Koranipilot 2.0 (port 7000)."""

from __future__ import annotations

WEB_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>고라니파일럿 리모컨</title>
<style>
:root{
  --bg:#0d1412;--card:#16221e;--card2:#1d2c27;--line:#293d36;
  --text:#f2f6f4;--muted:#9cb2a8;--accent:#5ce0a8;--warn:#f5b942;--danger:#ff6b6b;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;line-height:1.45;padding-bottom:44px;}
header{position:sticky;top:0;z-index:20;background:rgba(13,20,18,.95);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:12px 14px 10px;}
.top{display:flex;align-items:center;justify-content:space-between;gap:8px;}
.brand{font-size:19px;font-weight:800;letter-spacing:-.3px;}
.badge{font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;background:var(--card2);color:var(--muted);}
.badge.ok{background:rgba(92,224,168,.16);color:var(--accent);}
.badge.warn{background:rgba(245,185,66,.18);color:var(--warn);}
.tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px;}
.tab{border:1px solid var(--line);background:var(--card);color:var(--muted);border-radius:10px;padding:9px 4px;font-size:13px;font-weight:700;cursor:pointer;}
.tab.active{background:var(--accent);color:#092117;border-color:var(--accent);}
main{max-width:680px;margin:0 auto;padding:12px 14px;}
.panel{display:none;}
.panel.active{display:block;}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin-bottom:12px;}
.card h2{margin:0 0 6px;font-size:16px;font-weight:800;}
.sub{color:var(--muted);font-size:13px;margin:0 0 10px;}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.stat{background:var(--card2);border-radius:12px;padding:10px;}
.stat .k{font-size:11px;color:var(--muted);}
.stat .v{font-size:15px;font-weight:800;margin-top:2px;}
.btn{width:100%;border:0;border-radius:12px;padding:13px 14px;font-size:15px;font-weight:800;cursor:pointer;background:var(--card2);color:var(--text);}
.btn.primary{background:var(--accent);color:#092117;}
.btn.danger{background:rgba(255,107,107,.16);color:var(--danger);border:1px solid rgba(255,107,107,.35);}
.btn:disabled{opacity:.45;cursor:not-allowed;}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid rgba(255,255,255,.06);}
.row:first-of-type{border-top:0;padding-top:2px;}
.row-title{font-size:15px;font-weight:700;}
.row-desc{font-size:12px;color:var(--muted);margin-top:2px;}
.switch{position:relative;width:52px;height:30px;flex-shrink:0;}
.switch input{opacity:0;width:0;height:0;}
.slider{position:absolute;inset:0;background:#31443d;border-radius:999px;transition:.2s;cursor:pointer;}
.slider:before{content:"";position:absolute;width:24px;height:24px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s;}
input:checked+.slider{background:var(--accent);}
input:checked+.slider:before{transform:translateX(22px);}
.stepper{display:flex;align-items:center;gap:8px;flex-shrink:0;}
.step-btn{width:38px;height:36px;border-radius:10px;border:1px solid var(--line);background:var(--card2);color:var(--text);font-size:18px;font-weight:800;cursor:pointer;}
.step-val{min-width:66px;text-align:center;font-weight:800;font-size:15px;}
.seg{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}
.seg button{border:1px solid var(--line);background:var(--card2);color:var(--muted);border-radius:9px;padding:7px 11px;font-size:13px;font-weight:700;cursor:pointer;}
.seg button.active{background:var(--accent);color:#092117;border-color:var(--accent);}
.search{width:100%;padding:11px 13px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--text);font-size:15px;margin-bottom:10px;}
.chips{display:flex;gap:6px;overflow-x:auto;padding-bottom:8px;margin-bottom:8px;}
.chip{white-space:nowrap;border:1px solid var(--line);background:var(--card);color:var(--muted);border-radius:999px;padding:6px 12px;font-size:13px;font-weight:700;cursor:pointer;}
.chip.active{background:var(--accent);color:#092117;border-color:var(--accent);}
.model-item{padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--card2);margin-top:8px;display:flex;justify-content:space-between;align-items:center;gap:10px;}
.model-item.selected{border-color:var(--accent);}
.toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#1f332c;color:#fff;border:1px solid var(--accent);padding:10px 16px;border-radius:999px;font-size:13px;font-weight:700;z-index:50;display:none;max-width:90%;text-align:center;}
</style>
</head>
<body>
<header>
  <div class="top">
    <div class="brand">고라니파일럿 리모컨</div>
    <div id="connBadge" class="badge">연결 확인 중</div>
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="nav">방지턱·코너</button>
    <button class="tab" data-tab="models">주행 모델</button>
    <button class="tab" data-tab="settings">써니 설정</button>
    <button class="tab" data-tab="device">기기 관리</button>
  </div>
</header>

<main>
  <section id="tab-nav" class="panel active">
    <div class="card">
      <div class="stat-grid">
        <div class="stat"><div class="k">폰 내비 연동</div><div id="stNav" class="v">대기 중</div></div>
        <div class="stat"><div class="k">현재 감속 안내</div><div id="stDecel" class="v">없음</div></div>
        <div class="stat"><div class="k">전방 감지</div><div id="stEvents" class="v">-</div></div>
        <div class="stat"><div class="k">차량 상태</div><div id="stRoad" class="v">확인 중</div></div>
      </div>
      <div style="margin-top:12px;display:grid;gap:8px;">
        <button class="btn primary" onclick="applyRecommended()">고라니 추천 세팅 한 번에 켜기 (방지턱 + 코너 + 단속)</button>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          <button id="deepLinkBtn" class="btn" onclick="openCompanion()">폰 내비 앱 자동 연결</button>
          <a class="btn" href="https://github.com/JM1405/openpilot/releases/download/latest-apk/koranipilot-companion.apk" style="text-align:center;text-decoration:none;display:flex;align-items:center;justify-content:center;">안드로이드 앱(APK) 받기</a>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>과속방지턱 감속</h2>
      <p class="sub">방지턱 앞에서 미리 속도를 줄여 차가 덜컹거리지 않게 해요.</p>
      <div class="row">
        <div><div class="row-title">방지턱 감속 켜기</div></div>
        <label class="switch"><input type="checkbox" id="cfg_bump_enabled" onchange="saveCfg({bump_enabled:this.checked})"><span class="slider"></span></label>
      </div>
      <div class="row">
        <div><div class="row-title">통과 목표 속도</div><div class="row-desc">추천 25 km/h (부드러운 통과)</div></div>
        <div class="stepper">
          <button class="step-btn" onclick="stepCfg('bump_speed_kph',-1,15,45)">-</button>
          <div id="val_bump_speed_kph" class="step-val">25 km/h</div>
          <button class="step-btn" onclick="stepCfg('bump_speed_kph',1,15,45)">+</button>
        </div>
      </div>
      <div class="row">
        <div><div class="row-title">미리 줄여두는 거리</div><div class="row-desc">방지턱 몇 m 앞에서 감속을 끝낼지 (추천 12m)</div></div>
        <div class="stepper">
          <button class="step-btn" onclick="stepCfg('bump_lead_m',-1,5,25)">-</button>
          <div id="val_bump_lead_m" class="step-val">12 m</div>
          <button class="step-btn" onclick="stepCfg('bump_lead_m',1,5,25)">+</button>
        </div>
      </div>
      <div class="row">
        <div><div class="row-title">감속 강도</div><div class="row-desc">숫자가 클수록 더 늦고 강하게 줄여요 (추천 1.1)</div></div>
        <div class="stepper">
          <button class="step-btn" onclick="stepCfg('bump_comfort_decel',-0.1,0.6,2.0,1)">-</button>
          <div id="val_bump_comfort_decel" class="step-val">1.1</div>
          <button class="step-btn" onclick="stepCfg('bump_comfort_decel',0.1,0.6,2.0,1)">+</button>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>코너 (커브) 감속</h2>
      <p class="sub">써니 비전 코너 감속을 더 똑똑하게 조절하고, 내비 급커브 구간도 함께 줄여요.</p>
      <div class="row">
        <div><div class="row-title">비전 코너 감속 (카메라)</div><div class="row-desc">도로 굽이를 보고 미리 감속 (써니 기본)</div></div>
        <label class="switch"><input type="checkbox" id="sp_SmartCruiseControlVision" onchange="saveSp('SmartCruiseControlVision',this.checked)"><span class="slider"></span></label>
      </div>
      <div class="row">
        <div><div class="row-title">지도/내비 커브 감속</div><div class="row-desc">지도 곡률 기반 감속</div></div>
        <label class="switch"><input type="checkbox" id="sp_SmartCruiseControlMap" onchange="saveSp('SmartCruiseControlMap',this.checked)"><span class="slider"></span></label>
      </div>
      <div class="row">
        <div><div class="row-title">코너 감속 민감도</div><div class="row-desc">1.00=순정 · 1.15=조금 더 여유롭게 감속</div></div>
        <div class="stepper">
          <button class="step-btn" onclick="stepCfg('corner_vision_scale',-0.05,0.85,1.45,2)">-</button>
          <div id="val_corner_vision_scale" class="step-val">1.15</div>
          <button class="step-btn" onclick="stepCfg('corner_vision_scale',0.05,0.85,1.45,2)">+</button>
        </div>
      </div>
      <div class="row">
        <div><div class="row-title">내비 급커브 감속</div><div class="row-desc">카카오 내비 급커브 안내 시 감속</div></div>
        <label class="switch"><input type="checkbox" id="cfg_sharp_turn_enabled" onchange="saveCfg({sharp_turn_enabled:this.checked})"><span class="slider"></span></label>
      </div>
      <div class="row">
        <div><div class="row-title">급커브 기본 목표 속도</div></div>
        <div class="stepper">
          <button class="step-btn" onclick="stepCfg('sharp_turn_speed_kph',-5,20,75)">-</button>
          <div id="val_sharp_turn_speed_kph" class="step-val">40 km/h</div>
          <button class="step-btn" onclick="stepCfg('sharp_turn_speed_kph',5,20,75)">+</button>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>과속카메라 · 전체 스위치</h2>
      <div class="row">
        <div><div class="row-title">단속카메라 · 구간단속 감속</div></div>
        <label class="switch"><input type="checkbox" id="cfg_camera_enabled" onchange="saveCfg({camera_enabled:this.checked})"><span class="slider"></span></label>
      </div>
      <div class="row">
        <div><div class="row-title">단속 여유 속도</div><div class="row-desc">예: +5면 60단속에서 65로 통과</div></div>
        <div class="stepper">
          <button class="step-btn" onclick="stepCfg('camera_offset_kph',-2,-10,15)">-</button>
          <div id="val_camera_offset_kph" class="step-val">0 km/h</div>
          <button class="step-btn" onclick="stepCfg('camera_offset_kph',2,-10,15)">+</button>
        </div>
      </div>
      <div class="row">
        <div><div class="row-title">고라니파일럿 감속 전체 스위치</div></div>
        <label class="switch"><input type="checkbox" id="cfg_enabled" onchange="saveCfg({enabled:this.checked})"><span class="slider"></span></label>
      </div>
      <div class="row">
        <div><div class="row-title">C4 주행 화면 배지 표시</div></div>
        <label class="switch"><input type="checkbox" id="cfg_onroad_badge" onchange="saveCfg({onroad_badge:this.checked})"><span class="slider"></span></label>
      </div>
    </div>
  </section>

  <section id="tab-models" class="panel">
    <div class="card">
      <h2>현재 주행 모델</h2>
      <div id="activeModelName" style="font-size:17px;font-weight:800;margin:6px 0 4px;">확인 중...</div>
      <div id="downloadingText" class="sub"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;">
        <button class="btn primary" onclick="modelAction('refresh')">목록 새로고침</button>
        <button class="btn" onclick="modelAction('reset_stock')">순정 기본 모델</button>
      </div>
    </div>
    <div class="card">
      <h2>사용 가능한 모델 목록</h2>
      <p class="sub">정차 중이고 C4가 인터넷(와이파이/핫스팟)에 연결돼 있을 때 바꿀 수 있어요.</p>
      <div id="modelList">불러오는 중...</div>
    </div>
  </section>

  <section id="tab-settings" class="panel">
    <input id="settingSearch" class="search" type="search" placeholder="설정 검색 (예: 차선, 크루즈, 토크, 밝기...)" oninput="renderCatalog()">
    <div id="groupChips" class="chips"></div>
    <div id="catalogList">불러오는 중...</div>
  </section>

  <section id="tab-device" class="panel">
    <div class="card">
      <h2>고라니파일럿 2.0 기기 정보</h2>
      <p class="sub" id="deviceInfoText">불러오는 중...</p>
      <button id="rebootBtn" class="btn danger" onclick="rebootDevice()">콤마4(C4) 재부팅</button>
    </div>
  </section>
</main>

<div id="toast" class="toast"></div>

<script>
let statusData = null;
let catalogData = {groups: [], rows: []};
let activeGroup = 'all';

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function openCompanion() {
  const ip = (statusData && statusData.lan_ip) ? statusData.lan_ip : location.hostname;
  const port = (statusData && statusData.port) ? String(statusData.port) : (location.port || '7000');
  location.href = 'koranipilot://connect?ip=' + encodeURIComponent(ip) + '&port=' + encodeURIComponent(port);
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  clearTimeout(window._tt);
  window._tt = setTimeout(() => el.style.display = 'none', 2600);
}

async function api(url, body) {
  const opt = body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {};
  const res = await fetch(url, opt);
  return await res.json();
}

document.querySelectorAll('.tab').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'models') loadModels();
    if (btn.dataset.tab === 'settings' && !catalogData.rows.length) loadCatalog();
  };
});

async function refreshStatus() {
  try {
    const s = await api('/api/status');
    statusData = s;
    const badge = document.getElementById('connBadge');
    badge.textContent = s.is_onroad ? '주행 중' : '정차 중';
    badge.className = 'badge ' + (s.is_onroad ? 'warn' : 'ok');

    const nav = s.nav_summary || {};
    document.getElementById('stNav').textContent = nav.fresh ? ('연결됨 (' + (nav.mode === 'route' ? '길안내' : '안전주행') + ')') : '폰 앱 대기 중';
    const dec = s.active_decel || {};
    document.getElementById('stDecel').textContent = dec.active ? (dec.label + (dec.distance_m != null ? ' · ' + Math.round(dec.distance_m) + 'm' : '')) : '감속 없음';
    const c = nav.counts || {};
    document.getElementById('stEvents').textContent = nav.fresh ? ('턱 ' + (c.bump||0) + ' · 커브 ' + (c.sharp_turn||0) + ' · 단속 ' + ((c.camera||0)+(c.section||0))) : '-';
    document.getElementById('stRoad').textContent = s.is_onroad ? '주행 중 (일부 설정 잠금)' : '정차 중 (모든 설정 가능)';

    const cfg = s.config || {};
    ['enabled','bump_enabled','sharp_turn_enabled','camera_enabled','onroad_badge'].forEach(k => {
      const el = document.getElementById('cfg_' + k);
      if (el) el.checked = !!cfg[k];
    });
    document.getElementById('val_bump_speed_kph').textContent = cfg.bump_speed_kph + ' km/h';
    document.getElementById('val_bump_lead_m').textContent = cfg.bump_lead_m + ' m';
    document.getElementById('val_bump_comfort_decel').textContent = Number(cfg.bump_comfort_decel).toFixed(1);
    document.getElementById('val_corner_vision_scale').textContent = Number(cfg.corner_vision_scale).toFixed(2);
    document.getElementById('val_sharp_turn_speed_kph').textContent = cfg.sharp_turn_speed_kph + ' km/h';
    const off = Number(cfg.camera_offset_kph || 0);
    document.getElementById('val_camera_offset_kph').textContent = (off > 0 ? '+' : '') + off + ' km/h';

    const qt = s.quick_toggles || {};
    ['SmartCruiseControlVision','SmartCruiseControlMap'].forEach(k => {
      const el = document.getElementById('sp_' + k);
      if (el) el.checked = !!qt[k];
    });

    document.getElementById('deviceInfoText').textContent =
      '버전 ' + s.version + ' · 기기 주소 http://' + (s.lan_ip || '알 수 없음') + ':' + s.port;
    document.getElementById('rebootBtn').disabled = !!s.is_onroad;
  } catch (e) {}
}

async function saveCfg(patch) {
  const res = await api('/api/korani-config', patch);
  if (res.ok) toast('설정을 저장했어요');
  refreshStatus();
}

function stepCfg(key, delta, lo, hi, decimals) {
  if (!statusData) return;
  let v = Number(statusData.config[key]) + delta;
  v = Math.max(lo, Math.min(hi, v));
  if (decimals != null) v = Number(v.toFixed(decimals));
  else v = Math.round(v);
  saveCfg({[key]: v});
}

async function applyRecommended() {
  const res = await api('/api/korani-config', {action:'recommended'});
  toast(res.message || '추천 세팅을 켰어요!');
  refreshStatus();
}

async function saveSp(key, value) {
  const res = await api('/api/settings', {key, value});
  toast(res.message || '저장했어요');
  refreshStatus();
}

async function loadModels() {
  const m = await api('/api/models');
  document.getElementById('activeModelName').textContent = m.active_name || '기본 모델 (순정)';
  document.getElementById('downloadingText').textContent = m.downloading_index != null ? ('다운로드 예약 중 (# ' + m.downloading_index + ')') : '';
  const list = document.getElementById('modelList');
  const bundles = m.bundles || [];
  if (!bundles.length) {
    list.innerHTML = '<div class="sub">아직 불러온 모델 목록이 없어요. 위 [목록 새로고침]을 눌러주세요.</div>';
    return;
  }
  list.innerHTML = bundles.map(b => {
    const active = m.active_index === b.index;
    const idx = Number(b.index);
    return `<div class="model-item ${active ? 'selected' : ''}">
      <div>
        <div style="font-weight:800;font-size:15px;">${esc(b.display_name)}</div>
        <div class="row-desc">${esc(b.folder || '')} · gen ${esc(b.generation || '')}</div>
      </div>
      <button class="btn ${active ? '' : 'primary'}" style="width:auto;padding:9px 14px;" ${m.is_onroad ? 'disabled' : ''} onclick="modelAction('select', ${idx})">${active ? '사용 중' : '선택'}</button>
    </div>`;
  }).join('');
}

async function modelAction(action, index) {
  toast(action === 'refresh' ? '모델 목록을 가져오는 중...' : '적용 요청 중...');
  const res = await api('/api/models', index != null ? {action, index} : {action});
  toast(res.message || (res.ok ? '완료!' : '실패'));
  loadModels();
}

async function loadCatalog() {
  catalogData = await api('/api/settings');
  const chips = document.getElementById('groupChips');
  const all = [{id:'all', title:'전체'}, ...(catalogData.groups || [])];
  chips.innerHTML = all.map(g => `<button class="chip ${activeGroup===g.id?'active':''}" onclick="setGroup('${esc(g.id)}')">${esc(g.title)}</button>`).join('');
  renderCatalog();
}

function setGroup(id) {
  activeGroup = id;
  loadCatalog();
}

function renderCatalog() {
  const q = (document.getElementById('settingSearch').value || '').trim().toLowerCase();
  const rows = (catalogData.rows || []).filter(r => {
    if (activeGroup !== 'all' && r.group !== activeGroup) return false;
    if (q && !r.title.toLowerCase().includes(q) && !r.key.toLowerCase().includes(q)) return false;
    return true;
  });
  const onroad = statusData && statusData.is_onroad;
  const host = document.getElementById('catalogList');
  if (!rows.length) { host.innerHTML = '<div class="card"><div class="sub">검색 결과가 없어요.</div></div>'; return; }
  host.innerHTML = '<div class="card">' + rows.map(r => {
    const locked = onroad && r.restart;
    const tag = r.restart ? '<span style="color:var(--warn);font-size:11px;margin-left:6px;">정차 중 변경</span>' : '';
    const keySafe = esc(r.key);
    const titleSafe = esc(r.title);
    if (r.type === 'bool') {
      return `<div class="row">
        <div><div class="row-title">${titleSafe}${tag}</div></div>
        <label class="switch"><input type="checkbox" ${r.value ? 'checked' : ''} ${locked ? 'disabled' : ''} onchange="updateCat('${keySafe}', this.checked)"><span class="slider"></span></label>
      </div>`;
    }
    if (r.type === 'enum') {
      const opts = (r.options || []).map(o => {
        const same = o.value === r.value || (o.value !== null && r.value !== null && Number(o.value) === Number(r.value));
        const valJson = esc(JSON.stringify(o.value));
        return `<button class="${same ? 'active' : ''}" ${locked ? 'disabled' : ''} onclick="updateCat('${keySafe}', ${valJson})">${esc(o.label)}</button>`;
      }).join('');
      return `<div class="row" style="display:block;"><div class="row-title">${titleSafe}${tag}</div><div class="seg">${opts}</div></div>`;
    }
    const step = Number(r.step || 1);
    const min = r.min != null ? Number(r.min) : 0;
    const max = r.max != null ? Number(r.max) : 999;
    return `<div class="row">
      <div><div class="row-title">${titleSafe}${tag}</div></div>
      <div class="stepper">
        <button class="step-btn" ${locked ? 'disabled' : ''} onclick="updateCat('${keySafe}', Math.max(${min}, Number((${Number(r.value||0)} - ${step}).toFixed(2))))">-</button>
        <div class="step-val">${esc(r.value == null ? '-' : r.value)}</div>
        <button class="step-btn" ${locked ? 'disabled' : ''} onclick="updateCat('${keySafe}', Math.min(${max}, Number((${Number(r.value||0)} + ${step}).toFixed(2))))">+</button>
      </div>
    </div>`;
  }).join('') + '</div>';
}

async function updateCat(key, value) {
  const res = await api('/api/settings', {key, value});
  toast(res.message || '저장했어요');
  const row = catalogData.rows.find(x => x.key === key);
  if (row && res.ok) row.value = res.value;
  renderCatalog();
  refreshStatus();
}

async function rebootDevice() {
  if (!confirm('콤마4를 지금 재부팅할까요?')) return;
  const res = await api('/api/reboot', {});
  toast(res.message || '재부팅 중...');
}

refreshStatus();
setInterval(refreshStatus, 2000);
</script>
</body>
</html>
"""
