import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

const $ = id => document.getElementById(id);
const SLOTS = [['hairStyle','髪型'],['top','トップス'],['bottom','ボトムス'],
               ['outer','上着'],['dress','ドレス'],['shoes','靴']];
const STORAGE_KEY = 'promodeler-makeup-riggedwoman-v6';
let config, token, scene, camera, renderer, orbit, model, loadUrl;
let morphMeshes = [], bones = new Map(), view = 'full', ready = false;
let baselineUrl = '', exportSignature = null, exportReady = false, waitingExport = false;
let state = {phase:'starting',livePhase:'starting'};

async function request(url, options={}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '操作に失敗しました');
  return data;
}
function post(url, payload) {
  return request(url,{method:'POST',headers:{'Content-Type':'application/json',
    'X-Makeup-Token':token},body:JSON.stringify(payload)});
}
function settings() {
  return {
    sliders:Object.fromEntries(Object.keys(config.parameters).map(path=>
      [path,Number($('slider-'+path).value)])),
    modules:Object.fromEntries(SLOTS.map(([key])=>[key,$('module-'+key).value||null])),
    bag:$('bag').checked,
    underwear:{top:$('underwear-top').checked,bottom:$('underwear-bottom').checked}
  };
}
const signature = value => JSON.stringify(value);

function chooseRecipe(recipe) {
  for (const path of Object.keys(config.parameters)) {
    const [group,key] = path.split('.');
    const input = $('slider-'+path);
    input.value = recipe[group]?.[key] ?? 0.5;
    $('value-'+path).textContent = Number(input.value).toFixed(2);
  }
  for (const [key] of SLOTS) {
    const value = key==='hairStyle' ? recipe.appearance?.hairStyle : recipe.wardrobe?.[key];
    const select = $('module-'+key);
    select.value = value || '';
    if (select.selectedIndex < 0) select.selectedIndex = 0;
  }
  $('bag').checked = (recipe.accessories || []).includes('streetwear_bag');
  $('underwear-top').checked = recipe.underwear?.top !== false;
  $('underwear-bottom').checked = recipe.underwear?.bottom !== false;
  changed(false);
}
function restore() {
  chooseRecipe(config.starter);
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (!stored || !stored.sliders || !stored.modules) return;
    for (const [path,value] of Object.entries(stored.sliders)) {
      const input = $('slider-'+path);
      if (input && Number.isFinite(value)) {
        input.value = value;
        $('value-'+path).textContent = Number(input.value).toFixed(2);
      }
    }
    for (const [key,value] of Object.entries(stored.modules)) {
      const select = $('module-'+key);
      if (select && [...select.options].some(item=>item.value===(value||''))) select.value=value||'';
    }
    $('bag').checked = !!stored.bag;
    if (stored.underwear) {
      $('underwear-top').checked = stored.underwear.top !== false;
      $('underwear-bottom').checked = stored.underwear.bottom !== false;
    }
    changed(false);
  } catch (_) { /* A missing or old saved draft should not block the editor. */ }
}
function keepOutfitConsistent(event) {
  const dress = $('module-dress');
  if (event?.target===dress && dress.value) {
    for (const key of ['top','bottom','outer']) $('module-'+key).value='';
  } else if (event?.target?.value && ['top','bottom','outer'].some(key=>event.target===$('module-'+key))) {
    dress.value='';
  }
}
function changed(persist=true) {
  const now = settings();
  if (persist) {
    try { localStorage.setItem(STORAGE_KEY,JSON.stringify(now)); } catch (_) {}
  }
  if (ready) applyLive(now);
  $('save').disabled = !ready;
  $('export').disabled = !ready || waitingExport;
  const matches = exportReady && exportSignature===signature(now);
  $('glb-link').hidden = !matches;
  $('current-caption').textContent = ready ? 'ドラッグで回転・ホイールで拡大できます' : '3Dモデルを準備しています';
}
function buildControls() {
  for (const [path,meta] of Object.entries(config.parameters)) {
    const row=document.createElement('div'); row.className='control';
    const label=document.createElement('label'); label.htmlFor='slider-'+path; label.textContent=meta.label;
    const value=document.createElement('output'); value.id='value-'+path;
    const input=document.createElement('input'); input.type='range'; input.id='slider-'+path;
    input.min='0'; input.max=String(meta.max); input.step='0.01'; input.value='0.5';
    input.addEventListener('input',()=>{value.textContent=Number(input.value).toFixed(2);changed()});
    row.append(label,value,input);
    $(path.startsWith('face.')?'face-controls':'body-controls').append(row);
  }
  for (const [key,labelText] of SLOTS) {
    const row=document.createElement('div'); row.className='selectrow';
    const label=document.createElement('label'); label.htmlFor='module-'+key; label.textContent=labelText;
    const select=document.createElement('select'); select.id='module-'+key;
    if (key!=='hairStyle') {
      const option=document.createElement('option'); option.value=''; option.textContent='なし'; select.append(option);
    }
    for (const item of config.modules[key==='hairStyle'?'appearance.hairStyle':'wardrobe.'+key]||[]) {
      const option=document.createElement('option'); option.value=item.id; option.textContent=item.label; select.append(option);
    }
    select.addEventListener('change',event=>{keepOutfitConsistent(event);changed()});
    row.append(label,select); $('module-controls').append(row);
  }
  $('bag').addEventListener('change',()=>changed());
  $('underwear-top').addEventListener('change',()=>changed());
  $('underwear-bottom').addEventListener('change',()=>changed());
  $('reset').addEventListener('click',()=>{chooseRecipe(config.starter);changed()});
  $('save').addEventListener('click',save);
  $('export').addEventListener('click',exportModel);
  for (const [kind,id] of [['full','tab-full'],['face','tab-face']]) {
    $(id).addEventListener('click',()=>switchView(kind));
  }
}

function makeRenderer() {
  const holder=$('current-figure');
  renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));
  renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure=1.35;
  holder.replaceChildren(renderer.domElement);
  scene=new THREE.Scene(); scene.background=new THREE.Color('#282b30');
  scene.add(new THREE.HemisphereLight(0xffffff,0x727988,2.0));
  const key=new THREE.DirectionalLight(0xffffff,2.5);key.position.set(1.8,3.2,3.2);scene.add(key);
  const fill=new THREE.DirectionalLight(0xc7deff,1.2);fill.position.set(-2.1,2.1,-1.2);scene.add(fill);
  camera=new THREE.PerspectiveCamera(35,1,0.01,100);
  camera.position.set(0,1.0,4.3);
  orbit=new OrbitControls(camera,renderer.domElement);
  orbit.target.set(0,0.95,0);orbit.enableDamping=true;
  orbit.minDistance=0.35;orbit.maxDistance=6;
  const resize=()=>{
    const width=Math.max(1,holder.clientWidth),height=Math.max(1,holder.clientHeight);
    renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(holder);resize();
  const loop=()=>{requestAnimationFrame(loop);orbit.update();renderer.render(scene,camera)};loop();
}
function switchView(kind) {
  view=kind;
  $('tab-full').classList.toggle('active',kind==='full');
  $('tab-face').classList.toggle('active',kind==='face');
  if (kind==='face') {camera.position.set(0,1.61,0.73);orbit.target.set(0,1.61,0);}
  else {camera.position.set(0,1.0,4.3);orbit.target.set(0,0.95,0);}
  orbit.update();
  if (baselineUrl) $('original-image').src=state.baseline?.[kind]||baselineUrl;
}
function eachMorph(name,weight) {
  for (const mesh of morphMeshes) {
    const index=mesh.morphTargetDictionary?.[name];
    if (index!==undefined) mesh.morphTargetInfluences[index]=weight;
  }
}
function applyLive(current) {
  if (!model) return;
  const reset=new Set();
  for (const spec of Object.values(config.parameterSpecs)) {
    for (const shape of spec.shapeKeys||[]) reset.add(shape.name);
  }
  for (const slot of Object.values(config.bodyMeshMasks)) {
    for (const masks of Object.values(slot)) for (const mask of masks)
      reset.add('PM_Hide_'+mask.vertexGroup.replace(/^PM_Cover_/,''));
  }
  for (const name of reset) eachMorph(name,0);
  for (const [path,spec] of Object.entries(config.parameterSpecs)) {
    const value=current.sliders[path];
    for (const shape of spec.shapeKeys||[]) {
      const amount=shape.side==='negative'?Math.max(0,(0.5-value)*2):Math.max(0,(value-0.5)*2);
      eachMorph(shape.name,Math.min(1,amount*(shape.factor??1)));
    }
    for (const boneSpec of spec.bones||[]) {
      const bone=bones.get(boneSpec.name);
      if (bone) bone.scale[boneSpec.axis.toLowerCase()] = boneSpec.scale[0]+(boneSpec.scale[1]-boneSpec.scale[0])*value;
    }
  }
  const modules=current.modules;
  const allModuleObjects=new Set(Object.values(config.moduleObjects)
    .flatMap(choices=>Object.values(choices).flat()));
  for (const name of allModuleObjects) {
    const object=model.getObjectByName(name);if(object)object.visible=false;
  }
  for (const [key,value] of Object.entries(modules)) {
    const path=key==='hairStyle'?'appearance.hairStyle':'wardrobe.'+key;
    for (const name of config.moduleObjects[path]?.[value]||[]) {
      const object=model.getObjectByName(name);if(object)object.visible=true;
    }
  }
  for (const [name,objectNames] of Object.entries(config.accessories)) {
    for (const objectName of objectNames) {
      const object=model.getObjectByName(objectName);
      if(object)object.visible=name==='streetwear_bag'&&current.bag;
    }
  }
  for (const [slot,name] of [['top','Bra'],['bottom','Underwear_Bottoms']]) {
    const object=model.getObjectByName(name);if(object)object.visible=current.underwear[slot];
  }
  for (const [key,value] of Object.entries(modules)) {
    if (key==='hairStyle'||!value) continue;
    const path='wardrobe.'+key;
    for (const name of config.bodyMasks[path]?.[value]||[]) {
      const object=model.getObjectByName(name);if(object)object.visible=false;
    }
    for (const mask of config.bodyMeshMasks[path]?.[value]||[]) {
      eachMorph('PM_Hide_'+mask.vertexGroup.replace(/^PM_Cover_/,''),1);
    }
  }
}
function loadModel(url) {
  if (loadUrl===url) return;
  loadUrl=url;
  $('status-text').textContent='3Dモデルを読み込んでいます';
  new GLTFLoader().load(url,gltf=>{
    if (model) scene.remove(model);
    model=gltf.scene;
    morphMeshes=[];bones=new Map();
    model.traverse(object=>{
      if(object.isMesh&&object.morphTargetDictionary)morphMeshes.push(object);
      if(object.isBone)bones.set(object.name,object);
    });
    scene.add(model);ready=true;
    $('status').dataset.phase='ready';
    $('status-text').textContent='リアルタイム表示中';
    applyLive(settings());switchView(view);changed(false);
  },event=>{
    if(event.total) $('status-text').textContent='3Dモデル読み込み '+Math.round(event.loaded/event.total*100)+'%';
  },error=>{
    $('status').dataset.phase='error';
    $('status-text').textContent='3Dモデルを読み込めません: '+error.message;
    loadUrl=null;
  });
}
async function save() {
  try {
    const name=$('recipe-name').value.trim();
    const result=await post('/api/save',{name,settings:settings()});
    $('save-note').textContent='保存しました: '+result.path;
    $('recipe-link').href=result.url;$('recipe-link').hidden=false;
  } catch(error) {$('save-note').textContent=error.message;}
}
async function exportModel() {
  try {
    exportSignature=signature(settings());exportReady=false;waitingExport=true;changed(false);
    await post('/api/build',settings());
    $('export-note').textContent='GLBを書き出しています。3D画面の操作は続けられます。';
  } catch(error) {
    waitingExport=false;exportSignature=null;exportReady=false;changed(false);
    $('export-note').textContent=error.message;
  }
}
async function poll() {
  try {
    state=await request('/api/status');
    if(state.baseline&&baselineUrl!==state.baseline.full) {
      baselineUrl=state.baseline.full;$('original-image').src=state.baseline[view];
    }
    if(state.livePhase==='ready'&&state.liveModel) {
      if(loadUrl&&loadUrl!==state.liveModel) {
        config=await request('/api/config');
        token=config.token;
      }
      loadModel(state.liveModel);
    }
    else if(!ready) $('status-text').textContent=state.liveMessage||'3Dプレビューを準備しています';
    if(waitingExport&&state.phase==='ready') {
      waitingExport=false;
      exportReady=true;
      $('glb-link').href=state.current.glb;
      $('export-note').textContent='GLBの書き出しが完了しました。';
      changed(false);
    } else if(waitingExport&&state.phase==='error') {
      waitingExport=false;exportSignature=null;exportReady=false;
      $('export-note').textContent=state.message;
      changed(false);
    }
  } catch(error) {$('status-text').textContent=error.message;}
}
async function start() {
  try {
    config=await request('/api/config');token=config.token;
    buildControls();restore();
    try {makeRenderer();} catch(error) {
      $('status').dataset.phase='error';
      $('status-text').textContent='このブラウザーでは3D表示を開始できません: '+error.message;
      return;
    }
    await poll();setInterval(poll,1500);
  } catch(error) {$('status-text').textContent=error.message;}
}
start();
