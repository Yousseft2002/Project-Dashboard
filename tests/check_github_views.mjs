// Rendering checks with synthetic GitHub evidence. No device data.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',hidden:false,addEventListener(){},classList:{toggle(){}}});return elements.get(id);}
const context=vm.createContext({console,Intl,Date,URLSearchParams,encodeURIComponent,decodeURIComponent,setInterval:()=>1,clearInterval(){},location:{hash:''},window:{addEventListener(){},scrollTo(){}},document:{querySelector:element,querySelectorAll:()=>[],addEventListener(){},hidden:false},fetch:async()=>({ok:true,json:async()=>({authenticated:false,configured:false})})});
vm.runInContext(fs.readFileSync('github_static/dashboard.js','utf8'),context);
await new Promise(resolve=>setImmediate(resolve));
assert.match(element('#view').innerHTML,/No local files or editor monitoring/);
vm.runInContext(`session={authenticated:true};data={projects:[],notifications:[],errors:[]};render()`,context);
assert.match(element('#cards').innerHTML,/Your next chapter/);
vm.runInContext(`data.projects=[{id:'owner/project',name:'<script>bad</script>',description:'<img src=x onerror=bad()>',private:true,branch:'main',language:'JavaScript',commits:[{sha:'a'.repeat(40),message:'<script>commit</script>',date:new Date().toISOString()}],issues:[{title:'Fix auth',pr:false,number:1,url:'https://github.com/owner/project/issues/1'}],milestones:[],branches:['main'],warnings:[],fetchedAt:new Date().toISOString()}];render()`,context);
assert.ok(!element('#cards').innerHTML.includes('<script>'));
assert.match(element('#cards').innerHTML,/&lt;script&gt;/);
vm.runInContext(`search='no match';renderCards()`,context);
assert.match(element('#cards').innerHTML,/No matches/);
vm.runInContext(`location.hash='#project/owner%2Fproject';render()`,context);
assert.match(element('#view').innerHTML,/I worked on this today/);
assert.match(element('#view').innerHTML,/No patch contents/);
assert.ok(!element('#view').innerHTML.includes('<script>'));
vm.runInContext(`location.hash='#activity';render()`,context);
assert.match(element('#view').innerHTML,/bounded view/);
vm.runInContext(`location.hash='#notifications';render()`,context);
assert.match(element('#view').innerHTML,/All quiet here/);
console.log('GitHub UI: sign-in, empty, populated, search, detail, timeline, notifications and escaped evidence passed.');
