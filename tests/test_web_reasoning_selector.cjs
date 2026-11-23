const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('channel/web/static/js/views/models.js', 'utf8');
const fn = source.slice(source.indexOf('function syncChatEffort(scope)'));
function run({thinking, only, model='gpt-6', saved='high'}) {
  const wrap = { classList: { hidden: false, add() {this.hidden=true}, remove() {this.hidden=false} } };
  const dd = {}, provider = {_ddValue:'codex'}, modelEl = {_ddValue:model};
  const nodes = {'#cap-chat-effort-wrap':wrap, '#cap-chat-effort':dd, '#cap-chat-provider':provider, '#cap-chat-model':modelEl};
  const root = {querySelector: s => nodes[s] || null};
  const meta = {supported:true, thinking_only:only, default:'low', options:[{value:'low'},{value:'high'}]};
  const ctx = { document: root, chatEffortConfig: {enable_thinking:thinking, providers:{codex:{reasoning_by_model:{'gpt-6':meta}}}, reasoning_effort_by_model:{'codex:gpt-6':saved}}, chatEffortDraft:'', getDropdownValue: e => e._ddValue, initDropdown: (e,o,v,cb) => { e.value=v; e.choose=cb; } };
  vm.createContext(ctx); vm.runInContext(fn,ctx); ctx.syncChatEffort(root);
  return {wrap,dd,ctx};
}
test('always-thinking model shows saved value even when toggle off', () => {const x=run({thinking:false,only:true}); assert.equal(x.wrap.classList.hidden,false); assert.equal(x.dd.value,'high'); x.dd.choose('low'); assert.equal(x.ctx.chatEffortDraft,'low');});
test('hybrid model hidden when thinking off; unknown model hidden', () => {assert.equal(run({thinking:false,only:false}).wrap.classList.hidden,true); assert.equal(run({thinking:true,only:true,model:'unknown'}).wrap.classList.hidden,true);});
test('invalid saved value falls back to supported default',()=>{assert.equal(run({thinking:true,only:true,saved:'bad'}).dd.value,'low');});
