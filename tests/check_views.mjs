import fs from 'node:fs';
import assert from 'node:assert/strict';
const { state } = await import('../static/js/state.js');
state.data=JSON.parse(fs.readFileSync(0,'utf8'));
const { dashboardView }=await import('../static/js/views/dashboard.js');
const { projectView }=await import('../static/js/views/project.js');
const { integrationsView,debugView }=await import('../static/js/views/integrations.js');
for (const render of [dashboardView,integrationsView,debugView,()=>projectView(state.data.projects[0].id)]) {
  const html=render();
  assert(html.length>100);
  assert(!html.includes('NaN'));
  assert(!html.includes('[object Object]'));
}
console.log('Dashboard, project, integrations and debug views rendered from actual collector metadata.');
