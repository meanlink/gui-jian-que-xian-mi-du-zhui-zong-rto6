import {esc,fmt} from '../../utils/dom.js';
export function table(columns,rows,empty='暂无记录。请先导入业务数据，再创建分析任务。',highlight=''){
 if(!rows.length)return '<div class="empty">'+esc(empty)+'</div>';
 return '<div class="table-wrap"><table><thead><tr>'+columns.map(c=>'<th>'+esc(c.label)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+columns.map(c=>{
  const severe=highlight&&c.key==='severity'&&Number(r.severity)>=4;
  return '<td'+(severe?' class="flag"':'')+'>'+esc(fmt(r[c.key]))+(severe?' · 高等级':'')+'</td>';
 }).join('')+'</tr>').join('')+'</tbody></table></div>';
}
