const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('expert/questionnaire.html','utf8'),script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{value:'',checked:false,disabled:false,textContent:'',innerHTML:'',click(){}});return nodes.get(id);}
let exported;const context={document:{getElementById:node,createElement:()=>({click(){}})},Blob,URL:{createObjectURL(b){exported=b;return 'blob:test';},revokeObjectURL(){}},setTimeout(){},console};vm.createContext(context);vm.runInContext(script,context);
assert(node('case').innerHTML.includes('Контракт после изменения'));assert(node('progress').textContent.includes('1/80'));
node('decision').value='ACCEPT';node('confidence').value='4';node('realism').value='3';node('reason').value='compatible';node('next').onclick();assert(node('progress').textContent.includes('2/80'));
node('prev').onclick();assert.equal(node('decision').value,'ACCEPT');node('save').onclick();assert(exported);
node('finish').onclick();assert(node('message').textContent.includes('Для завершения'));
exported.text().then(text=>{let d=JSON.parse(text);assert.equal(d.answers[0].decision,'ACCEPT');assert.equal(d.complete,false);assert(!text.includes('expected_decision'));console.log('questionnaire smoke passed: navigation, retained answers, draft export, completion gate, blind payload');});
