"use strict";
let qualityPacket = null;
function renderQualitySources(packet) {
  const context=packet.source_context;
  if (!context) return "";
  const states={no_frozen_detail:"本轮没有可定位的完整正文，不能用当前资料代替",ambiguous_version:"历史正文版本不唯一，需先核对来源",unavailable:"本轮历史正文不可用",integrity_failed:"来源完整性核对未通过",display_limit:"全文超过本页显示上限，以下对照不完整"};
  return `<section class="detail-section"><h3>原文逐段对照 · 检查回答遗漏</h3><p class="form-note">${e(context.notice)}</p>${context.scope_truncated ? '<p class="form-note">范围超过显示上限，以下岗位对照不完整。</p>' : ""}${context.sources.map(source=>`<details open><summary>${e(source.title || "岗位正文")} · ${source.state === "available" ? "研究当时的完整正文" : e(states[source.state] || "待核对")}</summary>${source.snapshot_id ? `<p class="form-note">正文版本：${e(source.snapshot_id)} · 取得：${e(source.observed_at || "未知")}</p>` : ""}${source.units.map(unit=>`<div class="research-context"><blockquote class="body-text">${e(unit.text)}</blockquote><p class="form-note">字符 ${e(unit.start)}–${e(unit.end)} · ${unit.claim_indices.length ? "引用片段涉及判断："+unit.claim_indices.map(index=>e(index+1)).join("、")+"；仍需核对回答是否覆盖" : "没有判断引用该段，请核对是否与问题有关、是否被遗漏"}</p></div>`).join("")}</details>`).join("") || '<p class="form-note">没有可对照的岗位正文范围。</p>'}</section>`;
}
function renderQualityMap(packet) {
  if (!packet.work_map) return renderCognitiveRevisions(packet,new Map());
  return renderWorkMap(packet,new Map()) + renderCognitiveRevisions(packet,new Map()) + `<fieldset><legend>地图关系单独核对</legend><p class="form-note">逐条原文判断通过不代表分组和因果关系成立。核对分组边界、反例、迁移限制、修订理由与未知；各组展开可见判断编号，下文查对应原文。</p><label>地图关系与边界<select name="work-map-rating"><option value="unknown">尚待核对</option><option value="pass">分组与关系在本次范围内有支持</option><option value="fail">需要修正</option></select></label><label>依据与疑点<input name="work-map-reason" required maxlength="1200"></label></fieldset>`;
}
function renderQualityRepair(packet) {
  const item=packet.repair;
  if (!item?.available && item?.project_id) return `<p class="form-note">这是项目内的研究，补查仍累计原项目总预算。<button class="secondary small" data-project-open="${e(item.project_id)}">到原项目安排补查</button></p>`;
  if (!item?.available) return "";
  return `<form id="quality-repair" class="panel strategy-editor"><h3>参考本次复核重新研究</h3><p class="form-note">${e(item.notice)} 前次已调用 ${e(item.previous_model_calls)} 次。当前仅支持原本地岗位范围的直接研究。</p><div class="form-grid"><label>本轮最多调用<input name="max_calls" type="number" min="2" max="12" value="8" required></label><label>本轮秒数上限<input name="timeout" type="number" min="1" max="300" value="240" required></label></div><label><input name="offline" type="checkbox">只预览反馈与证据，不调用模型</label><button class="primary">新建这一轮（预算另计）</button><p class="form-note">使用现有研究方法，复核意见需回查；不会把Agent复核当人审或自动采纳为知识。</p></form>`;
}
const qualityDimensions = {citation_semantics:"引用是否支持判断",requirement_classification:"必备、加分与未明确",profile_coverage:"画像与重要遗漏",unknown_handling:"未知及范围边界",counterexamples:"反例和相反证据",question_answered:"原问题是否已回答"};
const qualityStatus = {pending:"待核对",approved:"人工已核对",rejected:"需要补查",needs_recheck:"来源或记忆已变化，需重新核对"};
window.loadQuality = async function () {
  try {
    const data = await api("quality");
    $("#quality-runs").innerHTML=data.runs.length ? data.runs.map(run=>`<article class="panel report-row"><div><h3>${e(run.question || "研究")}</h3><p>${e(qualityStatus[run.review_status] || run.review_status)} · ${run.claim_count} 条判断${run.reviewer_kind === "agent_assisted" ? " · Agent协助评审" : ""}</p><small>${e(when(run.created_at))}</small></div><button class="secondary" data-quality-open="${e(run.id)}">逐条核对</button></article>`).join("") : empty("暂无已完成研究","先完成一次有模型判断的研究。离线整理证据仍可查看，空判断不能被批准为研究回答。");
    $("#quality-baselines").innerHTML=data.baselines.map(item=>`<article class="panel strategy-editor"><h2>冻结资料上的检索基线</h2><p>${item.detail_total ?? "未知"} 份正文；${item.missing_detail_total ?? "未知"} 个岗位缺正文。检索指标不是语义正确率。</p>${item.results.map(result=>`<p>${result.phase === "holdout" ? "预留验收" : "开发"}：召回 ${Number(result.baseline_mean_recall ?? 0).toFixed(3)} → ${Number(result.candidate_mean_recall ?? 0).toFixed(3)}；${result.label_review_status === "reviewed" ? "标签已由人类核对" : "Agent草案标签，待人类核对"}；${result.status === "insufficient" ? "证据不足，未启用" : e(result.status)}</p>`).join("")}${item.status === "invalid_or_changed" ? "<p>冻结资料已变化或不可用，请离线重新核对。</p>" : ""}</article>`).join("");
  } catch(error) { $("#quality-runs").innerHTML=errorBox(error); }
};

async function openQuality(id) {
  qualityPacket=await api("quality/runs/"+encodeURIComponent(id));
  const packet=qualityPacket;
  const requirement={required:"必备",preferred:"加分",unspecified:"未明确性质"};
  $("#quality-detail").innerHTML=`<form id="quality-review" class="panel strategy-editor"><h2>${e(packet.question || "研究质量核对")}</h2><p class="form-note">${e(packet.notice)}<br>模型调用 ${packet.usage.model_calls ?? "未知"} 次；耗时 ${packet.usage.elapsed_seconds ?? "未知"} 秒；费用未知。${packet.approve_allowed ? "" : "<br>此结果缺有效判断、存在来源/记忆变化或范围问题，当前不能批准。"}</p>${renderReviewFindings(packet)}${renderQualityMap(packet)}<h3>逐条判断与原文</h3>${packet.claims.map(claim=>`<fieldset data-quality-claim="${claim.index}"><legend>判断 ${claim.index+1} · ${e(requirement[claim.requirement] || claim.requirement)}</legend><p class="body-text">${e(claim.text)}</p>${claim.citations.map(cite=>`<details open><summary>${e(cite.title || "原文引用")} · ${e(cite.source || "未知来源")} · ${cite.start ?? "?"}–${cite.end ?? "?"}</summary><blockquote class="body-text">${e(cite.quote || "")}</blockquote><p class="form-note">来源发布时间：${e(cite.source_published_at || "未知")}；取得时间：${e(cite.observed_at || "未知")}<br>版本：${e(cite.snapshot_id || cite.public_document_id || "未归档搜索材料")}；${cite.valid ? "引用来源可识别，语义仍需核对" : "引用缺失或范围无法确认"}</p></details>`).join("")}<div class="form-grid"><label>原文语义<select name="support-${claim.index}"><option value="unknown">尚不能判断</option><option value="supported">原文支持主体、范围与强度</option><option value="unsupported">原文不充分支持</option></select></label><label>要求性质<select name="requirement-${claim.index}"><option value="unknown">尚不能判断</option><option value="correct">必备 / 加分 / 未明确标注正确</option><option value="incorrect">标注需要纠正</option></select></label></div><label>核对理由<input name="claim-note-${claim.index}" maxlength="1200" required placeholder="指出支持或不支持的原文，保留不确定"></label></fieldset>`).join("") || "<p>没有模型判断；不能批准为研究回答。</p>"}<h3>整体业务核对</h3>${Object.entries(qualityDimensions).map(([key,label])=>`<div class="form-grid"><label>${e(label)}<select name="dimension-${key}"><option value="unknown">待核对 / 证据不足</option><option value="pass">本次问题与范围内满足</option><option value="fail">需要修正</option>${!["citation_semantics","question_answered"].includes(key) ? '<option value="not_applicable">本次问题不适用</option>' : ""}</select></label><label>说明<input name="reason-${key}" required maxlength="1200" placeholder="说明依据、重要遗漏或不适用原因"></label></div>`).join("")}<details><summary>原研究记录的信息缺口</summary><ul>${packet.gaps.map(gap=>`<li>${e(gap)}</li>`).join("")}</ul></details><div class="form-grid"><label>审核者<input name="reviewer" required maxlength="100" placeholder="你的名称"></label><label>评审来源<select name="reviewer_kind"><option value="human">我在页面逐项核对原文</option><option value="agent_assisted">整理已有Agent协助评审（不代替人审）</option></select></label><label>处理<select name="decision"><option value="pending">保留待核对</option><option value="reject">拒绝当前回答，加入待补查</option>${packet.approve_allowed ? '<option value="approve">逐项支持且回答问题，人工接受</option>' : ""}</select></label></div><label>总结 / 下一步补查问题<textarea name="note" required maxlength="2000" rows="3" placeholder="拒绝时这段说明会进入待补查；不会自动调用模型或扩大范围"></textarea></label><button class="primary">保存核对</button><p class="form-note">核对记录不是新的独立证据。记忆遗忘会清除关联核对文本和补查通知。</p></form><div class="panel strategy-editor"><h3>已保存的核对</h3>${packet.reviews.length ? packet.reviews.map(review=>`<p><strong>${e(qualityStatus[review.status] || review.status)}</strong> · ${e(review.reviewer)} · ${review.reviewer_kind === "human" ? "人类核对" : "Agent协助评审"}${review.stale_result ? " · 结果已有变化" : ""}<br>${e(review.note)}${review.work_map_review ? `<br><strong>地图关系：</strong>${e(({pass:"本次范围内支持",fail:"需要修正",unknown:"待核对"})[review.work_map_review.rating] || "待核对")} · ${e(review.work_map_review.reason)}` : ""}</p>`).join("") : "<p>尚无核对记录，保持待审。</p>"}</div>`;
  $("#quality-detail").innerHTML += renderQualityRepair(packet);
  if (packet.source_context) $("#quality-review").insertAdjacentHTML("afterbegin", renderQualitySources(packet));
}
$("#refresh-quality")?.addEventListener("click",()=>loadQuality());
document.addEventListener("click",event=>{const button=event.target.closest("[data-quality-open]");if(button)openQuality(button.dataset.qualityOpen).catch(error=>notify(error.message,true));});
document.addEventListener("submit",async event=>{
  if(event.target.id !== "quality-review")return;
  event.preventDefault();if(!qualityPacket)return;
  const f=event.target.elements;
  const dimensions=Object.fromEntries(Object.keys(qualityDimensions).map(key=>[key,{rating:f["dimension-"+key].value,reason:f["reason-"+key].value.trim()}]));
  const claim_reviews=qualityPacket.claims.map(claim=>({index:claim.index,support:f["support-"+claim.index].value,requirement:f["requirement-"+claim.index].value,note:f["claim-note-"+claim.index].value.trim()}));
  const payload={result_sha256:qualityPacket.result_sha256,reviewer:f.reviewer.value.trim(),reviewer_kind:f.reviewer_kind.value,decision:f.decision.value,note:f.note.value.trim(),dimensions,claim_reviews};
  if (qualityPacket.work_map) payload.work_map_review={rating:f["work-map-rating"].value,reason:f["work-map-reason"].value.trim()};
  const button=event.target.querySelector("button[type=submit],button.primary");
  try {button.disabled=true;await api("quality/runs/"+qualityPacket.run_id+"/reviews",{method:"POST",body:JSON.stringify(payload)});await openQuality(qualityPacket.run_id);await loadQuality();notify("核对已保存；待补查不会自动花费模型额度。");}
  catch(error){button.disabled=false;notify(error.message,true);}
});
document.addEventListener("click",event=>{if(event.target.closest("[data-forget-memory]")){qualityPacket=null;$("#quality-detail")?.replaceChildren();$("#quality-runs")?.replaceChildren();}});
document.addEventListener("submit",async event=>{
  if (event.target.id !== "quality-repair") return;
  event.preventDefault();
  const item=qualityPacket?.repair;
  if (!item?.available) return;
  const f=event.target.elements,button=event.target.querySelector("button.primary");
  const payload={question:item.question,job_ids:item.job_ids,public_document_ids:item.public_document_ids??null,filters:item.filters,review_run_id:item.review_run_id,review_id:item.review_id,approach:"standard",allow_public:false,offline:f.offline.checked,max_calls:Number(f.max_calls.value),timeout:Number(f.timeout.value)};
  try {button.disabled=true;const started=await api("research",{method:"POST",body:JSON.stringify(payload)});location.hash="#research";await openRun(started.id);notify("新一轮已建立，旧研究与复核保留。");}
  catch(error){button.disabled=false;notify(error.message,true);}
});
if(location.hash === "#quality")loadQuality();
