import {datasets,calibrations} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify,date} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';
function calibrationPanel(calibration, versions){
 const current=calibration?.current,list=calibration?.versions||[],admin=session.user.role==='admin';
 const runs=Object.entries(current?.run_offsets||{}).map(([run,value])=>run+'='+value).join(', ');
 return '<section class="panel"><div class="section-title"><h2>里程校准</h2><span>当前 v'+(current?.version??0)+' · 共 '+list.length+' 个版本</span></div><p class="hint">每点登记的里程误差在数据行内（mileage_error_m），同车次的共同偏移在此登记。校准更新会新增版本并保留旧版本；已有试验仍按创建时的版本可查。</p><form id="calibration-form"><div class="parameter-grid"><label>共同偏移 (m)<input type="number" step="0.1" name="default_offset_m" value="'+(current?.default_offset_m??0)+'" '+(admin?'':'disabled')+'></label><label>备注<input name="note" maxlength="300" value="" placeholder="例如：11 月复测后整体前移" '+(admin?'':'disabled')+'></label></div><label>车次偏移 (m)<input name="run_offsets" value="'+esc(runs)+'" placeholder="DJ-01=12.5, DJ-02=-8" '+(admin?'':'disabled')+'></label><p class="hint">按数据中的车次编号登记整趟列车的共同偏移（会叠加到共同偏移上）。</p><button type="submit" class="primary" '+((!admin)?'disabled':'')+'>保存为新校准版本</button></form><p class="hint">格式：车次=偏移米，逗号分隔。未列出的车次沿用共同偏移；未登记误差的点按 0 米处理。观察员可查看不能修改。</p>'+(!list.length?'<div class="empty">尚无校准记录，v0 表示按原始里程计算。</div>':'<div class="version-list">'+list.map(v=>'<article class="'+(v.active?'active':'')+'"><div><strong>v'+v.version+(v.active?' · 当前':'')+'</strong><p>共同偏移 '+v.default_offset_m+' m · '+Object.keys(v.run_offsets||{}).length+' 个车次单独偏移</p><small>'+esc(v.note||'无备注')+' · '+date(v.created_at)+'</small></div><button class="button small" data-revert="'+v.id+'" '+(admin&&!v.active?'':'disabled')+'>以 v'+v.version+' 为新版本</button></article>').join('')+'</div>')+'</section>';
}
export async function dataPage(){
 workspace.datasets=await datasets.list();let selected=workspace.datasets[0]?await datasets.get(workspace.datasets[0].id):null,m=workspace.meta;
 let calibration=selected?await calibrations.list(selected.id):{current:null,versions:[]};
 workspace.calibration=calibration;
 return heading('02 / DATA INTAKE','数据接入与批次追溯','保留原始业务字段、来源和内容指纹。分析任务始终绑定一个不可变数据批次，并按创建时的完整校准版本计算。')+'<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>'+workspace.datasets.length+' 批</span></div><div class="batch-list">'+workspace.datasets.map(d=>'<button class="batch-item'+(selected?.id===d.id?' selected':'')+'" data-dataset="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>'+d.rows+' 条 · '+esc(d.source)+'</span><small>SHA256 '+esc(d.checksum.slice(0,18))+'…</small></button>').join('')+'</div><div class="section-title"><h2>接入新数据</h2></div><form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月复测批次"></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label><p class="hint">必需字段：'+m.columns.filter(c=>c.required!==false).map(c=>esc(c.key)+' / '+esc(c.label)).join('，')+'。可选字段 run_id、mileage_error_m。5–5,000 条记录。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>校验并接入批次</button></form></section><section class="panel"><div class="section-title"><h2 id="preview-name">'+esc(selected?.name||'尚无批次')+'</h2><span>预览前 30 条</span></div><div id="data-preview">'+table(m.columns,selected?.records.slice(0,30)||[])+'</div></section></div><div id="calibration-panel">'+calibrationPanel(calibration,workspace.datasets)+'</div>';
}
function parseRuns(text){
 const offsets={};
 for(const part of String(text||'').split(/[,，\n]/)){
   const item=part.trim();if(!item)continue;
   const [run,value,...rest]=item.split('=');
   if(!run||value===undefined||rest.length)throw new Error('车次偏移格式应为 车次=偏移米，例如 DJ-01=12.5');
   const number=Number(value);if(!Number.isFinite(number))throw new Error('车次 '+run.trim()+' 的偏移不是有效数值');
   offsets[run.trim()]=number;
 }
 return offsets;
}
function bindCalibrationPanel(datasetId,refresh){
 const form=document.querySelector('#calibration-form');if(!form)return;
 form.addEventListener('submit',async e=>{
   e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
   try{
     const data=new FormData(form);
     await calibrations.update(datasetId,{default_offset_m:Number(data.get('default_offset_m')),run_offsets:parseRuns(data.get('run_offsets')),note:data.get('note')});
     notify('已保存新的里程校准版本；基于旧校准的未发布简报已停止发布');await refresh();
   }catch(error){notify(error.message,true);}finally{button.disabled=false;}
 });
 document.querySelectorAll('[data-revert]').forEach(button=>button.onclick=async()=>{
   try{
     const versions=workspace.calibration?.versions||[],source=versions.find(v=>String(v.id)===button.dataset.revert);
     if(!source)return;
     await calibrations.update(datasetId,{default_offset_m:source.default_offset_m,run_offsets:source.run_offsets,note:'以 v'+source.version+' 为基础重新登记'});
     notify('已基于旧版本建立新的校准版本');await refresh();
   }catch(error){notify(error.message,true);}
 });
}
export function bindData(refresh){
 let source='manual.json',selectedId=workspace.datasets[0]?.id;
 bindCalibrationPanel(selectedId,refresh);
 document.querySelector('#file-input').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;source=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 document.querySelectorAll('[data-dataset]').forEach(button=>button.onclick=async()=>{try{const d=await datasets.get(button.dataset.dataset);selectedId=d.id;document.querySelector('#preview-name').textContent=d.name;document.querySelector('#data-preview').innerHTML=table(workspace.meta.columns,d.records.slice(0,30));const calibration=await calibrations.list(d.id);workspace.calibration=calibration;document.querySelector('#calibration-panel').innerHTML=calibrationPanel(calibration);bindCalibrationPanel(d.id,refresh);}catch(error){notify(error.message,true);}});
 submit(document.querySelector('#dataset-form'),async f=>{await datasets.create({name:f.get('name'),source,records:JSON.parse(f.get('records'))});notify('数据已接入，可前往工作台执行分析');await refresh();});
}
