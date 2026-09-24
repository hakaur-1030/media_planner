import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "/Users/hakaur/media_planner";
const SKILL_DIR = "/Users/hakaur/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations";
const TMP_DIR = path.join(workspaceDir, ".deck-build");
const FINAL_PPTX = path.join(workspaceDir, "media_planner_deck", "Noon_Media_Planner_Management_Deck.pptx");
const RUNTIME_PYTHON = "/Users/hakaur/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";
const { resolvePresentationFont, finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);
const font = resolvePresentationFont({ fontFamily: "Aptos" });
const logo = new Uint8Array(await fs.readFile(path.join(workspaceDir, "logo.png")));

const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const C = { navy: "#101B32", blue: "#1565C0", cyan: "#00A9E0", teal: "#00897B", green: "#2E7D32", amber: "#F9A825", red: "#C62828", pale: "#F4F7FB", ink: "#14213D", muted: "#5C6B80", line: "#D9E2EF", white: "#FFFFFF", sky: "#E6F3FC", mint: "#E8F5F2", sand: "#FFF6DE" };

function box(slide, x, y, w, h, fill="none", line="none", radius="rect") {
  return slide.shapes.add({ geometry: radius, position: { left:x, top:y, width:w, height:h }, fill, line: { style:"solid", fill:line, width: line === "none" ? 0 : 1 } });
}
function text(slide, value, x, y, w, h, opts={}) {
  const s = box(slide,x,y,w,h,opts.fill ?? "none",opts.line ?? "none",opts.radius ?? "rect");
  s.text = value;
  s.text.style = { typeface: font, fontSize: opts.size ?? 20, color: opts.color ?? C.ink, bold: opts.bold ?? false, autoFit:"shrink", verticalAlignment:opts.va ?? "middle", align:opts.align ?? "left", marginLeft:opts.pad ?? 0, marginRight:opts.pad ?? 0, marginTop:opts.padY ?? 0, marginBottom:opts.padY ?? 0 };
  return s;
}
function title(slide, heading, sub="") {
  text(slide, heading, 66, 42, 1100, 46, {size:31,bold:true,color:C.navy});
  if (sub) text(slide, sub, 66, 92, 1100, 27, {size:14,color:C.muted});
  box(slide,66,126,1148,3,C.cyan,"none");
}
function footer(slide, n) {
  text(slide,"Noon Media Planner  |  Internal presentation",66,682,400,18,{size:10,color:C.muted});
  text(slide,String(n).padStart(2,"0"),1160,680,54,18,{size:10,color:C.muted,align:"right"});
}
function note(slide, content) { slide.speakerNotes.textFrame.setText(content); }
function bullet(slide, head, body, x,y,w, accent=C.cyan) {
  box(slide,x,y,7,43,accent,"none","roundRect");
  text(slide,head,x+20,y,w-20,23,{size:17,bold:true,color:C.ink});
  text(slide,body,x+20,y+24,w-20,35,{size:13,color:C.muted,va:"top"});
}
function flowNode(slide, label, detail, x,y,w,h, color) {
  const b=box(slide,x,y,w,h,C.white,C.line,"roundRect");
  text(slide,label,x+16,y+13,w-32,26,{size:16,bold:true,color});
  text(slide,detail,x+16,y+43,w-32,h-53,{size:12,color:C.muted,va:"top"});
  return b;
}
function connect(slide,a,b){ slide.shapes.connect(a,b,{kind:"straight",fromSide:"right",toSide:"left",line:{style:"solid",fill:C.cyan,width:2},head:{type:"arrow",width:"sm",length:"sm"}}); }
function bg(slide) { slide.background.fill=C.white; }

// 1 Cover
{ const s=p.slides.add(); s.background.fill=C.navy;
  box(s,0,0,1280,720,C.navy,"none"); box(s,0,0,22,720,C.cyan,"none");
  s.images.add({blob:logo,contentType:"image/png",alt:"noon logo",fit:"contain",position:{left:70,top:70,width:190,height:62}});
  text(s,"Media Planner",70,202,880,70,{size:50,bold:true,color:C.white});
  text(s,"A governed, data-backed workflow for faster onsite media plans",74,284,780,50,{size:24,color:"#D6E7F5"});
  box(s,72,374,300,4,C.cyan,"none");
  text(s,"Management, Product & Technology Review",74,415,560,30,{size:16,bold:true,color:C.white});
  text(s,"September 2026",74,454,300,24,{size:14,color:"#B9C9D9"});
  const a=box(s,912,174,218,218,"#173457","none","ellipse"); const b=box(s,975,237,92,92,C.cyan,"none","ellipse");
  box(s,856,449,305,1,"#4B6886","none");
  text(s,"Plan with evidence.\nPrice with the approved card.\nSave every decision.",856,486,330,104,{size:20,bold:true,color:C.white,va:"top"});
  note(s,"Source: Media Planner repository README.md, main.py, planner.py. Title slide."); }

// 2 Executive
{ const s=p.slides.add(); bg(s); title(s,"The management case","Media Planner converts a fragmented planning exercise into a traceable, repeatable decision flow.");
  const metrics=[["3","markets currently supported","AE, SA and EG"],["7","BigQuery source domains","Rates, inventory, historic delivery, bookings and more"],["2","persisted outputs","Plan run plus line-level plan" ]];
  metrics.forEach((m,i)=>{const x=66+i*385; box(s,x,170,340,130,C.pale,"none","roundRect"); text(s,m[0],x+22,188,62,52,{size:38,bold:true,color:C.blue}); text(s,m[1],x+96,194,220,25,{size:16,bold:true}); text(s,m[2],x+24,245,290,34,{size:12,color:C.muted,va:"top"});});
  bullet(s,"A single planning workspace", "Inputs capture brand, category, country, campaign window, budget, marketplace split, phases and objective.",66,350,520);
  bullet(s,"Commercial rules stay explicit", "Rate-card validation, booking history, availability and allocation limits prevent an attractive plan from becoming an unbookable one.",66,435,520,C.teal);
  bullet(s,"Every plan has a record", "The API saves the request, output, diagnostics and plan code in BigQuery so teams can reload and regenerate the same plan.",660,350,500,C.amber);
  bullet(s,"Designed for operator control", "Planners can inspect recommendations, choose pricing, add approved manual slots and review feasibility notices before finalizing.",660,435,500,C.green);
  footer(s,2); note(s,"Facts: supported countries in main.py; source/output tables in README.md; workflow inputs in models.py."); }

// 3 workflow
{ const s=p.slides.add(); bg(s); title(s,"Planner experience: guided choice with human control","The product keeps the planner in the decision loop while automating evidence gathering and allocation.");
  const steps=[["1. Define campaign","Brand, comcat, markets, dates, net budget, objective and splits"],["2. Review shortlist","Eligible slots show pricing options, predicted performance, availability and rationale"],["3. Build plan","Planner selects slots or adds an approved manual placement; engine allocates by phase"],["4. Inspect outcome","Plan shows spend, views, expected CTR/RoAS, confidence and split feasibility"],["5. Save or regenerate","BigQuery-backed plan code supports reload, exclusions and replacement suggestions"]];
  const nodes=[]; steps.forEach((v,i)=>nodes.push(flowNode(s,v[0],v[1],66+i*230,205,190,190,[C.blue,C.cyan,C.teal,C.green,C.amber][i]))); nodes.slice(0,-1).forEach((a,i)=>connect(s,a,nodes[i+1]));
  text(s,"Key product principle",66,470,220,25,{size:16,bold:true,color:C.navy});
  text(s,"Recommendations are a starting point, not a black box. The planner can review the evidence and make controlled exceptions.",66,505,960,48,{size:22,bold:true,color:C.ink,va:"top"});
  footer(s,3); note(s,"Source: main.py endpoints /api/slot-preselection, /api/media-plan and regenerate; planner.py manual slot and diagnostic logic."); }

// 4 architecture
{ const s=p.slides.add(); bg(s); title(s,"Architecture: a focused API layer between planners and governed data","Cloud Run hosts the FastAPI service. BigQuery provides both planning inputs and saved-plan persistence.");
  const ui=flowNode(s,"Web planner","Single-page HTML experience\nRequests and plan review",66,220,245,150,C.blue);
  const api=flowNode(s,"FastAPI orchestration","Validation, error handling, FX cache, planning endpoints and response summaries",430,190,315,210,C.navy);
  const bq=flowNode(s,"BigQuery repository","Reads planning data and writes runs / line items through Application Default Credentials",875,220,280,150,C.teal);
  connect(s,ui,api); connect(s,api,bq);
  box(s,430,445,315,118,C.sky,"none","roundRect"); text(s,"Planning services",451,461,240,22,{size:16,bold:true,color:C.blue}); text(s,"Eligibility + recommendations\nDeterministic allocation\nRate-window line splitting\nDiagnostics and plan summary",451,491,260,65,{size:13,color:C.ink,va:"top"});
  box(s,875,445,280,118,C.mint,"none","roundRect"); text(s,"Deployment boundary",896,461,220,22,{size:16,bold:true,color:C.teal}); text(s,"Cloud Run: europe-west1\nRuntime service account\nBigQuery billing/query project",896,491,230,60,{size:13,color:C.ink,va:"top"});
  footer(s,4); note(s,"Source: README.md cloud setup and data flow; main.py; bigquery_repository.py; cloudbuild.yaml; Dockerfile."); }

// 5 data
{ const s=p.slides.add(); bg(s); title(s,"Data foundation: each decision links to a governed source","The repository resolves data into an eligible slot catalogue, historical performance pool and time-bounded inventory.");
  const vals=[
    ["Domain","Planning use","Representative source"],
    ["Slot catalogue","Placement metadata, page, zone, dimensions","slot_base_data"],
    ["Approved rate cards","CPM / CPD and daily Q4 rate schedules","slot_rate_card_base; rate_card_Q4"],
    ["Bookings & availability","Eligibility gate and forecasted inventory","adgroup_booked_delivered; forecasting"],
    ["Historic performance","Views, clicks, spend, revenue, CTR and RoAS","campaign_delivery_data_past_performance"],
    ["Plan persistence","Request, summary, diagnostics and plan lines","media_plan_runs; media_plan_lines"],
  ];
  const t=s.tables.add({rows:vals.length,columns:3,left:66,top:174,width:1148,height:320,values:vals,columnWidths:[210,420,518]});
  t.styleOptions={headerRow:true,bandedRows:true}; t.borders.assign({style:"solid",fill:C.line,width:1});
  for(let c=0;c<3;c++){t.getCell(0,c).fill=C.navy; t.getCell(0,c).text.style={typeface:font,fontSize:13,bold:true,color:C.white};}
  for(let r=1;r<vals.length;r++)for(let c=0;c<3;c++)t.getCell(r,c).text.style={typeface:font,fontSize:12,color:C.ink};
  text(s,"Why this matters",66,540,175,24,{size:16,bold:true,color:C.navy});
  text(s,"The planner does not fabricate commercial inputs. A plan can only use an approved price, eligible inventory and a valid service-date window.",66,573,1040,35,{size:18,bold:true,color:C.ink,va:"top"});
  footer(s,5); note(s,"Source: README.md Data flow; BigQueryRepository.fetch_slot_catalog, fetch_historical_performance and fetch_inventory."); }

// 6 recommendations
{ const s=p.slides.add(); bg(s); title(s,"Recommendation logic: filter for feasibility, then rank for fit","The engine narrows inventory before prioritising placements that match the campaign objective and commercial context.");
  const stages=[["Candidate pool","Slot catalogue and historical delivery joined by country / slot"],["Eligibility gates","Forecast availability, rate validity, booking history, country, marketplace and comcat relevance"],["Performance signals","Visibility, CTR, RoAS, brand affinity, comcat relevance, trend and confidence"],["Shortlist order","Objective-aware diversity across page families and marketplace shares" ]];
  const shapes=[]; stages.forEach((a,i)=>{shapes.push(flowNode(s,a[0],a[1],66+i*290,210,230,170,[C.blue,C.teal,C.amber,C.green][i]));}); shapes.slice(0,-1).forEach((a,i)=>connect(s,a,shapes[i+1]));
  text(s,"Confidence handling",66,475,188,22,{size:16,bold:true,color:C.navy});
  text(s,"Sparse but rate-valid Supermall placements remain discoverable with lower confidence rather than disappearing from the eligible set.",66,510,980,40,{size:19,bold:true,color:C.ink,va:"top"});
  footer(s,6); note(s,"Source: planner.py build_candidates / suggest_slots; BigQueryRepository.fetch_slot_catalog; tests/test_planner_rules.py Supermall eligibility test."); }

// 7 constraints
{ const s=p.slides.add(); bg(s); title(s,"Allocation logic: spend the budget inside a clear set of guardrails","The live V1 engine is deterministic and rule-based. It creates editable lines, then reports when the requested split is infeasible.");
  const v=[["Control","How the engine applies it","Operator outcome"],["Budget","On-deck budget ceiling, discounted net price and minimum CPM block","Spend is allocated in bookable units"],["Marketplace","Core / Supermall target shares; Core has a 35% per-slot cap","Scarce Supermall can absorb its requested share"],["Phases","Non-overlapping 09:00 service windows and phase budget splits","Slot windows do not collide"],["Diversity","Avoid repeated category-zone use per phase and prefer unused generated slots","More balanced placement mix"],["Feasibility","Diagnostics compare requested and actual brand, phase, marketplace, comcat and objective splits","Closest feasible draft stays reviewable" ]];
  const t=s.tables.add({rows:v.length,columns:3,left:66,top:165,width:1148,height:347,values:v,columnWidths:[192,575,381]}); t.styleOptions={headerRow:true,bandedRows:true}; t.borders.assign({style:"solid",fill:C.line,width:1});
  for(let c=0;c<3;c++){t.getCell(0,c).fill=C.navy;t.getCell(0,c).text.style={typeface:font,fontSize:13,bold:true,color:C.white};}
  for(let r=1;r<v.length;r++)for(let c=0;c<3;c++)t.getCell(r,c).text.style={typeface:font,fontSize:11.5,color:C.ink};
  text(s,"Management implication",66,558,210,23,{size:16,bold:true,color:C.navy});
  text(s,"The product treats a constrained plan as an informed draft with an explanation, rather than a silent failure or false precision.",66,591,1030,36,{size:18,bold:true,color:C.ink,va:"top"});
  footer(s,7); note(s,"Source: planner.py maximum_slot_budget, plan_media and diagnostics; main.py split deviation notices."); }

// 8 price date
{ const s=p.slides.add(); bg(s); title(s,"Pricing and date controls protect commercial accuracy","The planner calculates a plan over 09:00-to-09:00 service windows and validates prices against the applicable rate card.");
  const a=flowNode(s,"Campaign / phase dates","The end date is a closing boundary. Adjacent phases may touch at the same 09:00 boundary.",66,205,275,165,C.blue);
  const b=flowNode(s,"Rate-window validation","A booked slot needs an approved CPM or CPD rate for its service period. Q4 daily cards require every applicable date.",475,205,305,165,C.teal);
  const c=flowNode(s,"Line construction","The engine splits a line at a price change, preserving view and amount totals across the split.",914,205,240,165,C.amber);
  connect(s,a,b);connect(s,b,c);
  box(s,66,450,1090,102,C.sand,"none","roundRect"); text(s,"Commercial safeguards in the eligible catalogue",88,468,440,22,{size:16,bold:true,color:"#8A5A00"});
  text(s,"Unpriced inventory cannot become a commercial recommendation. Homepage CPD is gated below a USD 15,000 on-deck budget, while a planner’s manual selection remains visible as a controlled exception.",88,499,1010,35,{size:16,color:C.ink,va:"top"});
  footer(s,8); note(s,"Source: models.py phase validation; planner.py rate availability and split_rows_at_rate_changes; BigQueryRepository.fetch_slot_catalog; tests/test_planner_rules.py."); }

// 9 persistence
{ const s=p.slides.add(); bg(s); title(s,"Saved plans support traceability, iteration and operational handoff","Persisted plan codes make a generated plan an auditable business object rather than a transient calculation.");
  const left=flowNode(s,"Save","API writes the request context, summary and diagnostics to media_plan_runs; line items go to media_plan_lines.",66,210,290,160,C.blue);
  const mid=flowNode(s,"Reload","A plan code retrieves the stored record and displays the original plan through the hosted app URL.",494,210,290,160,C.teal);
  const right=flowNode(s,"Regenerate","The planner can exclude slots. The service retains valid choices and adds replacements from a refreshed recommendation pool.",922,210,290,160,C.green);
  connect(s,left,mid);connect(s,mid,right);
  text(s,"What teams can rely on",66,455,250,24,{size:16,bold:true,color:C.navy});
  bullet(s,"Business continuity", "A saved plan can be reopened without depending on a planner’s local session.",66,500,340,C.cyan);
  bullet(s,"Engineering observability", "Error responses distinguish input, BigQuery access and unexpected application failures with a reference code.",462,500,340,C.teal);
  bullet(s,"Product learning", "Stored diagnostics reveal where demand, rate cards or constraints prevent the desired plan mix.",858,500,340,C.amber);
  footer(s,9); note(s,"Source: README.md notes; main.py build_response, regenerate_media_plan and exception handlers; BigQueryRepository.save_plan / get_saved_plan."); }

// 10 operations
{ const s=p.slides.add(); bg(s); title(s,"Operating model: clear data, platform and product responsibilities","The solution has a lightweight runtime footprint, while quality depends on well-maintained commercial data and explicit ownership.");
  const vals=[["Area","Current control","Recommended accountable team"],["Runtime","Cloud Run in europe-west1; container starts FastAPI / Uvicorn","Platform Engineering"],["Access","Runtime service account with BigQuery read, write and job permissions","Platform + Data Governance"],["Planning sources","Rates, bookings, forecast, delivery and catalogue supply the engine","BI / Commercial Operations"],["Rules and UX","Eligibility, allocation diagnostics and controlled manual choices","Product + Media Planning"],["Quality assurance","Unit tests cover rate changes, phase boundaries, category relevance and constraints","Engineering + QA"]];
  const t=s.tables.add({rows:vals.length,columns:3,left:66,top:170,width:1148,height:335,values:vals,columnWidths:[190,575,383]});t.styleOptions={headerRow:true,bandedRows:true};t.borders.assign({style:"solid",fill:C.line,width:1});
  for(let c=0;c<3;c++){t.getCell(0,c).fill=C.navy;t.getCell(0,c).text.style={typeface:font,fontSize:13,bold:true,color:C.white};} for(let r=1;r<vals.length;r++)for(let c=0;c<3;c++)t.getCell(r,c).text.style={typeface:font,fontSize:11.5,color:C.ink};
  text(s,"Risk to manage",66,548,150,22,{size:16,bold:true,color:C.red}); text(s,"The planner can only be as current as the rate card, forecast and booking data. Ownership and freshness checks should sit alongside feature rollout.",66,580,1075,38,{size:18,bold:true,color:C.ink,va:"top"});
  footer(s,10); note(s,"Source: README.md Cloud Run target setup / required GCP setup; cloudbuild.yaml, Dockerfile; tests folder."); }

// 11 maturity roadmap
{ const s=p.slides.add(); bg(s); title(s,"Maturity path: scale confidence before expanding optimisation scope","The live V1 engine remains the production path. V2 is an isolated prototype and should enter production only after rule-parity validation.");
  const phases=[["Now: production core","V1 enforces requested splits, rate cards, budget rules and transparent diagnostics.\n\nFocus: adoption, data freshness and operator feedback."],["Next: evidence and governance","Add dashboards for split deviations, inventory shortfalls, rate-card coverage and saved-plan outcomes.\n\nFocus: measurable planning quality."],["Later: controlled optimisation","Validate V2 eCPM, fill-rate and tiering logic against V1 guardrails before enabling it.\n\nFocus: experiment design and safe release gates."]];
  phases.forEach((v,i)=>{const x=66+i*385; box(s,x,206,330,260,[C.sky,C.mint,C.sand][i],"none","roundRect");text(s,v[0],x+24,230,285,46,{size:20,bold:true,color:[C.blue,C.teal,"#8A5A00"][i],va:"top"});text(s,v[1],x+24,300,280,130,{size:15,color:C.ink,va:"top"});});
  text(s,"Technical note",66,540,130,22,{size:16,bold:true,color:C.navy}); text(s,"The API currently rejects engine=v2 because it does not yet enforce the full Media Planner split, rate-card and budget rule set.",66,573,1070,33,{size:18,bold:true,color:C.ink,va:"top"});
  footer(s,11); note(s,"Source: main.py create_media_plan and regenerate_media_plan reject v2; selection_v2.py module header describes prototype status."); }

// 12 decisions
{ const s=p.slides.add(); bg(s); title(s,"Decisions requested to move from capability to operating product","The immediate objective is not a broader algorithm. It is adoption with accountable data and measurable planning quality.");
  const rows=[["Decision","Why it matters","Suggested owner"],["Confirm production pilot scope","Select markets, campaign types and success criteria for the first operating cohort.","Business / Commercial"],["Name data owners and freshness SLAs","Rate cards, forecasts and booking history determine whether an eligible plan can be booked.","BI + Commercial Operations"],["Approve product measurement","Track plan utilisation, split deviation reasons, manual exceptions and downstream delivery results.","Product + Analytics"],["Set V2 release criteria","Require guardrail parity, back-testing and a controlled rollout before activating the prototype.","Engineering + Product"]];
  const t=s.tables.add({rows:rows.length,columns:3,left:66,top:172,width:1148,height:296,values:rows,columnWidths:[305,595,248]});t.styleOptions={headerRow:true,bandedRows:true};t.borders.assign({style:"solid",fill:C.line,width:1});for(let c=0;c<3;c++){t.getCell(0,c).fill=C.navy;t.getCell(0,c).text.style={typeface:font,fontSize:13,bold:true,color:C.white};}for(let r=1;r<rows.length;r++)for(let c=0;c<3;c++)t.getCell(r,c).text.style={typeface:font,fontSize:12,color:C.ink};
  box(s,66,535,1148,82,C.navy,"none","roundRect");text(s,"Proposed outcome",92,551,200,25,{size:16,bold:true,color:C.cyan});text(s,"Run a governed pilot, learn from the saved-plan evidence, then expand the planner with demonstrated commercial and operational confidence.",92,579,1060,22,{size:17,bold:true,color:C.white});
  footer(s,12); note(s,"Recommendation based on the current system architecture and explicit V2 production block. No external sources used."); }

const candidate = path.join(TMP_DIR,"media_planner_candidate.pptx");
await (await PresentationFile.exportPptx(p)).save(candidate);
await fs.mkdir(path.dirname(FINAL_PPTX),{recursive:true});
const result=await finalizePresentation({
  explicitTotalSlideCount:12,
  requiredNativeTableOwnerSlides:[5,7,10,12],
  workspaceDir,candidatePath:candidate,finalPath:FINAL_PPTX,pythonExecutable:RUNTIME_PYTHON,
  integrityValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs:["--expected-slide-size-emu","12192000,6858000","--validate-bullet-geometry","--validate-heading-fit","--require-native-table-slide","5","--require-native-table-slide","7","--require-native-table-slide","10","--require-native-table-slide","12"],
  fontPolicy:{basis:"design",families:[font]},verifyArtifactToolImport:true,
  receiptPath:path.join(TMP_DIR,"media_planner_validation.json")
});
console.log(JSON.stringify({final:FINAL_PPTX,result},null,2));
