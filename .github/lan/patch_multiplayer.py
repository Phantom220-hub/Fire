from pathlib import Path
import re, sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else '/mnt/data/lastcampfire_src')
js_path = root / 'www/js/game.js'
html_path = root / 'www/index.html'
js = js_path.read_text(encoding='utf-8')
html = html_path.read_text(encoding='utf-8')

def replace_once(source, old, new, label):
    count = source.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, got {count}')
    return source.replace(old, new, 1)

# Network role and authoritative host/client state.
js = replace_once(js,
"""  let run = null, scene = null;
  let paused = false, modalOpen = false;
  const cam = { x: 0, y: 0 };
  const input = { x: 0, y: 0, kx: 0, ky: 0 };
  let hudT = 0;
""",
"""  let run = null, scene = null;
  let paused = false, modalOpen = false;
  const cam = { x: 0, y: 0 };
  const input = { x: 0, y: 0, kx: 0, ky: 0 };
  const net = { role: null, connected: false, started: false, peerHero: 'hunter', remoteInput: { x: 0, y: 0, kx: 0, ky: 0 }, inputT: 0, snapshotT: 0, seq: 0, sending: false };
  let hudT = 0;

  function networkActor(heroId, x, y) {
    const h = HEROES[heroId] || HEROES.hunter;
    return { kind: 'p', heroId: HEROES[heroId] ? heroId : 'hunter', x: x, y: y, r: 5, hp: h.hp, maxHp: h.hp, face: 0.6, anim: 0, inv: 0, cd: 0.3, ht: 0, lt: 2, nt: 3, swing: 0, moving: false, fx: 1, fy: 0, dead: false };
  }
  function packActor(p) {
    if (!p) return null;
    return { kind: 'p', heroId: p.heroId || 'hunter', x: p.x, y: p.y, r: p.r || 5, hp: p.hp, maxHp: p.maxHp, face: p.face || 0, anim: p.anim || 0, inv: p.inv || 0, cd: p.cd || 0, ht: p.ht || 0, lt: p.lt || 0, nt: p.nt || 0, swing: p.swing || 0, moving: !!p.moving, fx: p.fx || 1, fy: p.fy || 0, dead: !!p.dead };
  }
  function playersInRun(r) { return r.remotePlayer ? [r.player, r.remotePlayer] : [r.player]; }
  function sendLanPacket(packet) {
    if (!window.LanBridge || !net.connected) return Promise.resolve();
    return window.LanBridge.send(packet).catch(err => { console.warn('LAN send', err); });
  }
  function makeLanSnapshot(type) {
    const r = run; if (!r) return null;
    const s = serialize(r);
    s.hostPlayer = packActor(r.player);
    s.remotePlayer = packActor(r.remotePlayer);
    s.pet = r.pet ? { id: r.pet.id, x: r.pet.x, y: r.pet.y, vx: r.pet.vx, cd: r.pet.cd, anim: r.pet.anim } : null;
    s.fx = { meteors: r.meteors, rings: r.rings, bolts: r.bolts };
    return { type: type || 'snapshot', seq: ++net.seq, state: s, over: r.over || false, overT: r.overT || 0, why: r.why || '' };
  }
  function startLanHost() {
    if (net.role !== 'host' || !net.connected) { hint('Сначала подключи второй телефон'); return; }
    if (net.started) { hint('Совместная игра уже запущена'); return; }
    const hostHero = HEROES[save.hero] ? save.hero : 'hunter';
    newRun(hostHero); run.slot = null;
    run.player.x = CX - 24; run.player.y = CY + 30;
    run.remotePlayer = networkActor(net.peerHero, CX + 24, CY + 30);
    run.pet = null;
    net.remoteInput = { x: 0, y: 0, kx: 0, ky: 0 };
    net.started = true; net.snapshotT = 0; net.finalSent = false;
    enterPlay();
    banner('СОВМЕСТНАЯ ИГРА', 'Один мир · два игрока', '#7dff8f');
    sendLanPacket(makeLanSnapshot('start'));
  }
  function applyLanSnapshot(packet) {
    const s = packet && packet.state;
    if (!s || !s.remotePlayer || !s.hostPlayer) return;
    const local = Object.assign({}, s.remotePlayer);
    const host = Object.assign({}, s.hostPlayer);
    const view = Object.assign({}, s, { hero: s.hero || 'hunter', p: host });
    const r = deserialize(view, null);
    r.player = Object.assign({ kind: 'p' }, local);
    r.remotePlayer = Object.assign({ kind: 'p' }, host);
    r.heroId = local.heroId || 'hunter'; r.hd = HEROES[r.heroId] || HEROES.hunter;
    r.slot = null; r.over = packet.over || false; r.overT = packet.overT || 0; r.why = packet.why || '';
    if (s.fx) { r.meteors = s.fx.meteors || []; r.rings = s.fx.rings || []; r.bolts = s.fx.bolts || []; }
    const networkPet = s.pet ? Object.assign({}, s.pet) : null;
    run = r; scene = null;
    if (state !== 'play' || !net.started) {
      net.started = true; enterPlay();
      $('#build').style.display = 'none'; $('#pauseBtn').style.display = 'none';
      hint('Ты в общем мире. Передвигайся джойстиком; бой и добыча автоматические.', 5000);
    }
    run.pet = networkPet;
    updateHud();
  }
  window.addEventListener('lan-role', e => { net.role = e.detail || null; net.connected = false; net.started = false; });
  window.addEventListener('lan-connected', () => { net.connected = true; });
  window.addEventListener('lan-message', e => {
    const m = e.detail || {}; 
    if (m.type === 'hello' && net.role === 'host') {
      net.peerHero = HEROES[m.hero] ? m.hero : 'hunter';
      if (run && run.remotePlayer && !net.started) run.remotePlayer.heroId = net.peerHero;
      hint('Второй игрок подключился. Нажми «Начать совместную игру».', 4500);
    } else if (m.type === 'input' && net.role === 'host' && net.started) {
      net.remoteInput.x = Math.max(-1, Math.min(1, Number(m.x) || 0));
      net.remoteInput.y = Math.max(-1, Math.min(1, Number(m.y) || 0));
      net.remoteInput.kx = 0; net.remoteInput.ky = 0;
    } else if ((m.type === 'start' || m.type === 'snapshot') && net.role === 'client') {
      applyLanSnapshot(m);
    } else if (m.type === 'leave' && net.role === 'host') {
      net.connected = false; net.remoteInput.x = net.remoteInput.y = 0;
      hint('Второй игрок отключился. Мир сохранён у хоста.', 4000);
    }
  });
  window.addEventListener('lan-start', startLanHost);
  window.addEventListener('lan-stop', () => {
    net.connected = false; net.started = false; net.role = null;
    if (run) run.remotePlayer = null;
    if (state === 'play') { $('#build').style.display = ''; $('#pauseBtn').style.display = ''; }
  });
""", 'LAN state injection')

# Client HUD should show its own character: snapshots swap player into r.player above.

# Extend player damage and enemy targeting to both characters.
js = replace_once(js,
"""  function chooseTarget(e) {
    const r = run, p = r.player, f = r.fire;
    if (r.dg) { e.tgt = p; return; }
    let best = f, bd = d2(e.x, e.y, f.x, f.y);
    if (e.type !== 'ghost') for (let i = 0; i < r.structs.length; i++) { const s = r.structs[i], d = d2(e.x, e.y, s.x, s.y); if (d < bd) { bd = d; best = s; } }
    if (d2(e.x, e.y, p.x, p.y) < 70 * 70 && p.hp > 0) best = p;
    e.tgt = best;
  }
""",
"""  function chooseTarget(e) {
    const r = run, p = r.player, f = r.fire;
    if (r.dg) { e.tgt = p; return; }
    let best = f, bd = d2(e.x, e.y, f.x, f.y);
    if (e.type !== 'ghost') for (let i = 0; i < r.structs.length; i++) { const s = r.structs[i], d = d2(e.x, e.y, s.x, s.y); if (d < bd) { bd = d; best = s; } }
    let playerDist = 70 * 70;
    playersInRun(r).forEach(actor => {
      if (!actor.dead && actor.hp > 0) { const d = d2(e.x, e.y, actor.x, actor.y); if (d < playerDist) { playerDist = d; best = actor; } }
    });
    e.tgt = best;
  }
""", 'enemy target')

js = replace_once(js,
"""  function hurtPlayer(d) {
    const p = run.player; if (p.inv > 0 || run.over) return;
    p.hp -= d; p.inv = 0.55; run.shake = Math.max(run.shake, 4); Snd.sfx('hurt'); burst(p.x, p.y - 8, '#ff5a5f', 6, 50, 0.4, 1);
    if (p.hp <= 0) gameOver('hero');
  }
""",
"""  function hurtPlayer(d, target) {
    const r = run, p = target && target.kind === 'p' ? target : r.player;
    if (p.inv > 0 || p.dead || r.over) return;
    p.hp = Math.max(0, p.hp - d); p.inv = 0.55; r.shake = Math.max(r.shake, 4); Snd.sfx('hurt'); burst(p.x, p.y - 8, '#ff5a5f', 6, 50, 0.4, 1);
    if (p.hp <= 0) {
      p.dead = true; p.moving = false;
      if (playersInRun(r).every(actor => actor.dead || actor.hp <= 0)) gameOver('hero');
      else hint((p === r.player ? 'Первый' : 'Второй') + ' игрок пал. Второй ещё держится!', 3500);
    }
  }
""", 'player damage')
js = replace_once(js, "if (t.kind === 'p') hurtPlayer(d); else if (t.kind === 'f')", "if (t.kind === 'p') hurtPlayer(d, t); else if (t.kind === 'f')", 'damage target')

# A dead player's character must not be selected again.
js = replace_once(js,
"""      e.tt -= dt; if (e.tt <= 0 || !e.tgt || e.tgt.dead || (e.tgt.kind === 'p' && p.hp <= 0)) { e.tt = rand(0.35, 0.55); chooseTarget(e); }
""",
"""      e.tt -= dt; if (e.tt <= 0 || !e.tgt || e.tgt.dead || (e.tgt.kind === 'p' && (e.tgt.hp <= 0 || e.tgt.dead))) { e.tt = rand(0.35, 0.55); chooseTarget(e); }
""", 'enemy retarget')

# Make updatePlayer reusable for the second network-controlled actor.
js = replace_once(js,
"""  function updatePlayer(r, dt, st) {
    const p = r.player;
    let ax = input.x + input.kx, ay = input.y + input.ky; const m = Math.hypot(ax, ay);
""",
"""  function updatePlayer(r, dt, st, actor, controls) {
    const p = actor || r.player, ctl = controls || input;
    if (p.dead || p.hp <= 0) return;
    let ax = ctl.x + ctl.kx, ay = ctl.y + ctl.ky; const m = Math.hypot(ax, ay);
""", 'generic player controls')
js = replace_once(js,
"""    if (p.moving) { p.x += ax * st.speed * dt; p.y += ay * st.speed * dt; p.fx = ax / Math.max(0.01, Math.min(1, m)); p.fy = ay / Math.max(0.01, Math.min(1, m)); p.anim += dt; }
""",
"""    const actorSpeed = actor && actor !== r.player && HEROES[p.heroId] ? st.speed * HEROES[p.heroId].speed / r.hd.speed : st.speed;
    if (p.moving) { p.x += ax * actorSpeed * dt; p.y += ay * actorSpeed * dt; p.fx = ax / Math.max(0.01, Math.min(1, m)); p.fy = ay / Math.max(0.01, Math.min(1, m)); p.anim += dt; }
""", 'actor speed')
js = replace_once(js,
"""        r.projs.push({ x: p.x, y: p.y - 8, vx: Math.cos(a) * 230, vy: Math.sin(a) * 230, dmg: st.dmg, pierce: st.pierce, life: 0.9, col: r.hd.bolt, hit: [], own: 'p' });
""",
"""        const actorHero = HEROES[p.heroId] || r.hd;
        r.projs.push({ x: p.x, y: p.y - 8, vx: Math.cos(a) * 230, vy: Math.sin(a) * 230, dmg: st.dmg, pierce: st.pierce, life: 0.9, col: actorHero.bolt, hit: [], own: 'p' });
""", 'actor bolt colour')

# Host simulates both characters. Client only sends controls and renders authoritative snapshots.
js = replace_once(js,
"""    updatePlayer(r, dt, st);
    updatePet(r, dt);
""",
"""    updatePlayer(r, dt, st);
    if (net.role === 'host' && net.connected && r.remotePlayer) updatePlayer(r, dt, st, r.remotePlayer, net.remoteInput);
    updatePet(r, dt);
""", 'host second player tick')

# Meteor and hostile projectile hits can affect either player.
js = replace_once(js,
"""      if (d2(r.player.x, r.player.y, m.x, m.y) < 24 * 24) hurtPlayer(12);
""",
"""      playersInRun(r).forEach(actor => { if (!actor.dead && d2(actor.x, actor.y, m.x, m.y) < 24 * 24) hurtPlayer(12, actor); });
""", 'meteor hits')
js = replace_once(js,
"""        const p = r.player, f = r.fire;
        if (d2(q.x, q.y, p.x, p.y - 7) < 7 * 7) { hurtPlayer(q.dmg); del = true; }
        else if (d2(q.x, q.y, f.x, f.y - 4) < 13 * 13) { hurtFire(q.dmg * 0.8); del = true; }
""",
"""        const f = r.fire;
        const hitPlayer = playersInRun(r).find(actor => !actor.dead && d2(q.x, q.y, actor.x, actor.y - 7) < 7 * 7);
        if (hitPlayer) { hurtPlayer(q.dmg, hitPlayer); del = true; }
        else if (d2(q.x, q.y, f.x, f.y - 4) < 13 * 13) { hurtFire(q.dmg * 0.8); del = true; }
""", 'hostile projectile hits')

# Draw both players; each uses its own selected hero sprite.
js = replace_once(js,
"""    dl.push({ y: r.player.y, k: 3, o: r.player }); if (!r.dg) dl.push({ y: r.fire.y, k: 4, o: r.fire });
""",
"""    dl.push({ y: r.player.y, k: 3, o: r.player });
    if (r.remotePlayer && r.remotePlayer.hp > 0) dl.push({ y: r.remotePlayer.y, k: 3, o: r.remotePlayer });
    if (!r.dg) dl.push({ y: r.fire.y, k: 4, o: r.fire });
""", 'draw remote player')
js = replace_once(js,
"""    const S = SPR.hero[r.heroId], fr = p.moving ? Math.floor(p.anim * 9) % 2 : 0, bob = p.moving ? (fr ? 1 : 0) : (Math.sin(r.time * 3) > 0.7 ? 1 : 0);
""",
"""    const S = SPR.hero[p.heroId || r.heroId] || SPR.hero[r.heroId], fr = p.moving ? Math.floor(p.anim * 9) % 2 : 0, bob = p.moving ? (fr ? 1 : 0) : (Math.sin(r.time * 3) > 0.7 ? 1 : 0);
""", 'actor sprite')

# Host controls the real game loop; client transmits joystick positions and never simulates a second world.
js = replace_once(js,
"""      if (state === 'play' && run && !paused && !modalOpen) update(dt);
      else if (state === 'play' && run && (paused || modalOpen)) { /* заморозка */ }
""",
"""      if (state === 'play' && run && !paused && !modalOpen && net.role !== 'client') update(dt);
      else if (state === 'play' && run && net.role === 'client' && !paused && !modalOpen) {
        net.inputT += dt;
        if (net.inputT >= 0.08 && net.connected) {
          net.inputT = 0;
          sendLanPacket({ type: 'input', x: Math.max(-1, Math.min(1, input.x + input.kx)), y: Math.max(-1, Math.min(1, input.y + input.ky)) });
        }
      }
      else if (state === 'play' && run && (paused || modalOpen)) { /* заморозка */ }
""", 'client input loop')

# Add periodic world snapshots after the host simulation has updated all entities.
js = replace_once(js,
"""    hudT -= dt; if (hudT <= 0) { hudT = 0.1; updateHud(); }
  }

  function updateAmbient(r, dt) {
""",
"""    hudT -= dt; if (hudT <= 0) { hudT = 0.1; updateHud(); }
    if (net.role === 'host' && net.connected && net.started && r.remotePlayer) {
      net.snapshotT += dt;
      if (net.snapshotT >= 0.12 && !net.sending) {
        net.snapshotT = 0; net.sending = true;
        sendLanPacket(makeLanSnapshot('snapshot')).finally(() => { net.sending = false; });
      }
    }
  }

  function updateAmbient(r, dt) {
""", 'host snapshots')

# Don't allow one-player dungeon transitions to split the co-op world.
js = replace_once(js,
"""  function enterDungeon(u) {
    const r = run, p = r.player; saveNow(); cancelPlace(); hideSel(); closePop();
""",
"""  function enterDungeon(u) {
    if (net.role) { hint('Подземелья пока доступны только в одиночной игре'); return; }
    const r = run, p = r.player; saveNow(); cancelPlace(); hideSel(); closePop();
""", 'disable solo dungeons in LAN')

# Route LAN disconnect notifications into the simulation state.
js = replace_once(js,
"""  window.addEventListener('lan-connected', () => { net.connected = true; });
""",
"""  window.addEventListener('lan-connected', () => { net.connected = true; });
  window.addEventListener('lan-disconnected', () => { net.connected = false; net.remoteInput.x = 0; net.remoteInput.y = 0; });
""", 'disconnect event')

# Boss ground-slam attacks both heroes in a co-op session.
js = replace_once(js,
"""        if (d2(e.x, e.y, p.x, p.y) < R * R) hurtPlayer(14 + r.night * 0.5);
""",
"""        playersInRun(r).forEach(actor => { if (!actor.dead && d2(e.x, e.y, actor.x, actor.y) < R * R) hurtPlayer(14 + r.night * 0.5, actor); });
""", 'boss slam')

# Keep both heroes' health and life-steal effects consistent in the shared run.
extra_replacements = [
    ("""    r.player.hp = Math.min(r.player.maxHp, r.player.hp + r.player.maxHp * 0.35);
""",
     """    playersInRun(r).forEach(actor => { if (!actor.dead) actor.hp = Math.min(actor.maxHp, actor.hp + actor.maxHp * 0.35); });
""", "day heal"),
    ("""    if (id === 'vit') { p.maxHp = r.st.maxHp; p.hp = Math.min(p.maxHp, p.hp + 30); }
""",
     """    if (id === 'vit') { playersInRun(r).forEach(actor => { const h = HEROES[actor.heroId] || r.hd; actor.maxHp = h.hp + 30 * (r.up.vit || 0); actor.hp = Math.min(actor.maxHp, actor.hp + 30); }); }
""", "vitality upgrade"),
    ("""    const lf = r.up.life || 0; if (lf && Math.random() < 0.2 * lf) r.player.hp = Math.min(r.player.maxHp, r.player.hp + 2);
""",
     """    const lf = r.up.life || 0; if (lf && Math.random() < 0.2 * lf) playersInRun(r).forEach(actor => { if (!actor.dead) actor.hp = Math.min(actor.maxHp, actor.hp + 2); });
""", "life steal"),
    ("""    if (r.over) { r.overT -= dt; updateParts(r, dt); if (r.over === true && r.overT <= 0) { r.over = 1; showOver(); } return; }
""",
     """    if (r.over) { r.overT -= dt; updateParts(r, dt); if (net.role === 'host' && net.connected && !net.finalSent) { net.finalSent = true; sendLanPacket(makeLanSnapshot('snapshot')); } if (r.over === true && r.overT <= 0) { r.over = 1; showOver(); } return; }
""", "final co-op snapshot")
]
for old, new, label in extra_replacements:
    count = js.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source match, got {count}")
    js = js.replace(old, new, 1)

js_path.write_text(js, encoding='utf-8')

# Replace the text-signal panel with host/join/start controls and a JSON packet bridge.
start = html.find('<div id="lanBeta"')
end = html.find('<script src="js/sprites.js"></script>', start)
if start < 0 or end < 0:
    raise SystemExit('LAN panel boundaries not found')
new_panel = r'''<div id="lanBeta" style="position:fixed;z-index:10000;display:none;inset:6%;background:#141a33;color:#eef2ff;border:3px solid #3b4a7a;border-radius:14px;padding:16px;overflow:auto;font:16px system-ui;box-shadow:0 10px 50px #000b">
<h2 style="margin-top:0">Совместная игра по Wi-Fi</h2>
<p>Телефоны должны быть подключены к одной точке доступа. Первый игрок создаёт комнату, второй вводит IP хоста. После подключения хост нажимает «Начать совместную игру».</p>
<button id="lanHost" style="padding:12px;margin:4px">Создать комнату</button>
<div style="margin:10px 0"><input id="lanIp" placeholder="IP телефона-хоста" inputmode="decimal" style="font-size:18px;width:65%;padding:10px;border-radius:7px"><button id="lanJoin" style="padding:12px">Войти</button></div>
<button id="lanStart" disabled style="padding:13px;margin:4px;background:#286b47;color:white">Начать совместную игру</button>
<button id="lanStop" style="padding:12px;margin:4px">Отключиться</button><button id="lanClose" style="padding:12px;margin:4px">Закрыть</button>
<div id="lanStatus" style="margin-top:12px;padding:10px;background:#0c1022;border-radius:8px;white-space:pre-wrap">LAN не подключён.</div></div>
<button id="lanOpen" style="position:fixed;z-index:9999;display:none;bottom:12px;left:12px;padding:10px">Совместная игра</button>
<script>
(function(){
const panel=document.getElementById('lanBeta'),open=document.getElementById('lanOpen'),status=document.getElementById('lanStatus');
const start=document.getElementById('lanStart'),host=document.getElementById('lanHost'),join=document.getElementById('lanJoin');
function note(t){status.textContent=t;}
function emit(name,detail){window.dispatchEvent(new CustomEvent(name,{detail:detail}));}
open.style.display='block';open.onclick=()=>panel.style.display='block';
document.getElementById('lanClose').onclick=()=>panel.style.display='none';
const native=window.Capacitor&&Capacitor.isNativePlatform()&&Capacitor.Plugins&&Capacitor.Plugins.Lan;
const bridge={role:null,connected:false,send(packet){if(!native)return Promise.reject('LAN-плагин недоступен');const data=JSON.stringify(packet);if(data.length>250000)return Promise.reject('Пакет мира слишком большой');return native.send({data:data});}};
window.LanBridge=bridge;
if(!native){note('Для LAN установи APK с нативным LAN-плагином.');host.disabled=true;join.disabled=true;}
else{
native.addListener('status',e=>{const m=String(e.message||'');note(m);if(bridge.role==='host'&&m.indexOf('Второй телефон подключился')>=0){bridge.connected=true;start.disabled=false;emit('lan-connected');}if(m.indexOf('Соединение прервано')>=0||m.indexOf('отключился')>=0){bridge.connected=false;start.disabled=true;emit('lan-disconnected');}});
native.addListener('message',e=>{try{emit('lan-message',JSON.parse(e.data));}catch(err){note('Получен некорректный пакет игры: '+err);}});
host.onclick=async()=>{start.style.display='';host.disabled=true;bridge.role='host';bridge.connected=false;start.disabled=true;emit('lan-role','host');note('Создаём комнату…');try{const r=await native.host();document.getElementById('lanIp').value=r.ip||'';note('Комната создана. IP хоста: '+(r.ip||'не определён')+'\nОжидаем второй телефон…');}catch(e){note('Не удалось создать комнату: '+e);host.disabled=false;bridge.role=null;emit('lan-role',null);}};
join.onclick=async()=>{join.disabled=true;bridge.role='client';bridge.connected=false;emit('lan-role','client');note('Подключаемся к хосту…');try{await native.connect({ip:document.getElementById('lanIp').value.trim()});bridge.connected=true;emit('lan-connected');let selected='hunter';try{const profile=JSON.parse(localStorage.getItem('nyxvault_last_campfire_v1')||'{}');if(profile.hero)selected=profile.hero;}catch(e){}await bridge.send({type:'hello',hero:selected});start.style.display='none';note('Подключено. Ожидаем, пока хост начнёт игру…');panel.style.display='none';}catch(e){note('Не удалось подключиться: '+e);join.disabled=false;bridge.role=null;emit('lan-role',null);}};
start.onclick=()=>{if(!bridge.connected||bridge.role!=='host')return;panel.style.display='none';emit('lan-start');};
document.getElementById('lanStop').onclick=async()=>{try{if(bridge.connected)await bridge.send({type:'leave'});await native.stop();}catch(e){}bridge.connected=false;bridge.role=null;start.disabled=true;host.disabled=false;join.disabled=false;emit('lan-stop');emit('lan-role',null);note('LAN остановлен.');};
}
})();
</script>
'''
html = html[:start] + new_panel + html[end:]
html_path.write_text(html, encoding='utf-8')
print('Patched LAN co-op controls and authoritative multiplayer logic.')