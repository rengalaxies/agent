import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { Presentation, PresentationFile } from '@oai/artifact-tool';

// Run in a runtime containing @oai/artifact-tool. Outputs are never product deploys.
const here = path.dirname(fileURLToPath(import.meta.url));
const output = path.resolve(process.env.DECK_OUTPUT || path.join(here, '..'));
const preview = path.resolve(process.env.DECK_PREVIEW || path.join(output, '.preview'));
await fs.mkdir(output, { recursive: true });
await fs.mkdir(preview, { recursive: true });
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const C = { paper:'#F5F4EE', ink:'#102E2C', green:'#087F72', muted:'#53635E', line:'#C6D1C9', white:'#FFFFFF', pale:'#E7EEE8', amber:'#92521D' };
const font = 'Arial';
let number = 0;
const copy = [];

function text(slide, value, x, y, w, h, size=28, options={}) {
  const box = slide.shapes.add({geometry:'textbox', name:options.name || value.slice(0,50),
    position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  box.text = value;
  box.text.insets = 0;
  box.text.style = {typeface:font,fontSize:size,color:options.color || C.ink,
    bold:options.bold || false,alignment:options.align || 'left',verticalAlignment:'top'};
  return box;
}
function rule(slide,x,y,w,color=C.line) {
  return slide.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:2},fill:color,line:{fill:'none',width:0}});
}
function node(slide,label,x,y,w=230,h=92,fill=C.white) {
  const n=slide.shapes.add({geometry:'rect',name:label,position:{left:x,top:y,width:w,height:h},fill,
    line:{fill:C.green,width:2}});
  n.text=label; n.text.insets={left:16,right:16,top:17,bottom:10};
  n.text.style={typeface:font,fontSize:27,bold:true,color:C.ink,alignment:'center',verticalAlignment:'middle'};
  return n;
}
function connect(slide,a,b,from='right',to='left',style='solid',kind='straight') {
  return slide.shapes.connect(a,b,{kind,fromSide:from,toSide:to,
    line:{fill:C.green,width:2,style},tail:{type:'triangle',width:'med',length:'med'}});
}
function slide(title, note, sources=[], dark=false) {
  const s=p.slides.add(); number++;
  s.background.fill=dark?C.ink:C.paper;
  if(title)text(s,title,64,55,1145,112,48,{bold:true,color:dark?C.white:C.ink,name:'Slide title'});
  text(s,`AGENT GRAPH  ·  ${number}/8`,64,674,1100,24,16,{color:dark?'#C9DAD3':C.muted});
  s.speakerNotes.text=note+'\n\nИсточники:\n'+sources.join('\n');
  copy.push({slide:number,title,notes:note,sources});
  return s;
}

{
 const s=slide('', 'Целевой автономный B2B-сервис. Помогает команде заранее увидеть возможное влияние изменения на соседние команды. Полный автономный сценарий ещё не реализован; экономия и спрос не измерены.','docs/product/pilot/OFFER.md'.split('\n'),true);
 text(s,'Кого затронет\nследующее изменение?',64,155,1130,205,68,{bold:true,color:C.white,name:'Cover title'});
 text(s,'Автономный сервис для команд,\nкоторые меняют внутренние API',68,405,1050,95,34,{color:'#DCE7E0'});
 text(s,'Задача Jira  →  граф связей  →  уточнение в PR',68,564,1100,43,29,{color:'#7AD4B7'});
 text(s,'Концепция автономного MVP · 24 октября 2026',68,621,1050,28,20,{color:'#B7CFC2'});
}
{
 const s=slide('Изменение API затрагивает соседнюю команду',
  'Иллюстрация: задача предлагает ограничить выдачу заказов. Граф связывает потребителя с операцией и основанием. Статическая связь и наблюдение вызова помогают выбрать проверку, но не доказывают будущую поломку. Пример не является клиентским кейсом.', ['docs/product/pilot/GRAPH.md','docs/agent-graph-demo/deployments/2026-10-22/README.md']);
 text(s,'Задача: «Ограничить выдачу заказов одной страницей»',64,178,1140,52,29,{bold:true});
 const reporting=node(s,'Reporting\nотчёт соседней команды',64,286,315,114);
 const orders=node(s,'Orders\nGET /orders',510,286,270,114,C.pale);
 connect(s,reporting,orders);
 text(s,'вызывает',391,318,108,36,22,{color:C.green});
 text(s,'Что видит команда',860,282,335,45,29,{bold:true});
 text(s,'Потребитель: Reporting\nОснование: файл и строка\nПроверка: полнота отчёта',860,345,350,151,26);
 text(s,'Инсайт появляется до того, как потерю данных заметит пользователь отчёта',64,483,710,110,33,{bold:true,color:C.green});
 text(s,'Иллюстрация сценария. Влияние подтверждается проверкой, а не наличием ребра.',64,620,1140,30,19,{color:C.muted});
}
{
 const s=slide('Jira предупреждает раньше. PR уточняет.',
  'Два входа в общий анализ. Jira работает с намерением и даёт предварительную область влияния. PR работает с diff по двум SHA и уточняет конкретные места. Оба результата — план первого автономного выпуска. Один комментарий обновляется; не нужен оператор на каждую задачу.', ['docs/product/pilot/OFFER.md','docs/product/pilot/DECISIONS.md']);
 text(s,'Когда создаётся задача',64,201,510,55,34,{bold:true,color:C.green});
 text(s,'Намерение из текста Jira\nВозможные сервисы и команды\nОснования и открытые вопросы',64,293,510,175,29);
 text(s,'Когда появляется код',700,201,510,55,34,{bold:true,color:C.green});
 text(s,'Изменение по двум версиям\nКонкретные места вызова\nЧто проверить до merge',700,293,510,175,29);
 rule(s,64,520,1140);
 text(s,'Один граф. Один обновляемый результат.\nБез ручного запуска анализа.',64,558,1120,85,34,{bold:true});
}
{
 const s=slide('Граф связывает код с работой сервисов',
  'Граф — обновляемая память с основаниями: кто вызывает кого, по какому источнику и когда это актуально. Код даёт объявленные вызовы; трассы или подходящие логи — наблюдения. Агент использует карту при анализе; человек может открыть путь и источник. Статическая находка, runtime-наблюдение и модельная гипотеза раздельны. Runtime-коннектор и устойчивый граф пока план.', ['docs/product/pilot/GRAPH.md','https://grafana.com/docs/tempo/latest/metrics-from-traces/service_graphs/']);
 const a=node(s,'Код и контракты',64,245,275,90);
 const b=node(s,'Трассы и журналы',64,435,275,90);
 const g=node(s,'Граф связей\nс основаниями',496,320,280,125,C.pale);
 const c=node(s,'Агент\nанализ Jira и PR',926,245,290,100);
 const d=node(s,'Команда\nпросмотр связей',926,435,290,100);
 connect(s,a,g,'right','left','solid','elbow');connect(s,b,g,'right','left','solid','elbow');
 connect(s,g,c,'right','left','solid','elbow');connect(s,g,d,'right','left','solid','elbow');
 text(s,'Источник · версия или окно · свежесть',371,202,520,39,25,{color:C.green,bold:true});
 text(s,'Факт, наблюдение и гипотеза имеют разные статусы.\nОтсутствие трафика не доказывает отсутствия потребителя.',64,572,1140,75,27);
}
{
 const s=slide('Альтернативы и наша гипотеза преимущества',
  'Сравнение задач по официальным источникам от 24.10.2026; общий эксперимент качества не проводился. Qwen-Agent поддерживает инструменты и MCP. Sourcegraph умеет точную навигацию SCIP. oasdiff сравнивает OpenAPI, Pact проверяет контракты. Tempo строит граф из трасс. Не утверждаем, что у альтернатив нет проверяемых оснований. Гипотеза сервиса — общий актуальный контекст кода и runtime для раннего Jira/PR-инсайта.',
  ['https://github.com/QwenLM/Qwen-Agent','https://sourcegraph.com/docs/code-navigation/precise-code-navigation','https://www.oasdiff.com/docs/getting-started','https://docs.pact.io/','https://grafana.com/docs/tempo/latest/metrics-from-traces/service_graphs/']);
 const values=[
 ['Подход','Сильная сторона','Что проверяем в нашем сценарии'],
 ['Агент + поиск','Гибкий разбор задачи и кода','Актуальность контекста и труд поддержки'],
 ['Sourcegraph','Точная навигация по коду','Межсервисные связи и наблюдаемые вызовы'],
 ['oasdiff / Pact','Изменения API и контракты','Поиск потребителей за пределами контракта'],
 ['Tempo / Grafana','Наблюдаемые вызовы и нагрузка','Связь наблюдения с будущим изменением']
 ];
 const table=s.tables.add({rows:5,columns:3,left:64,top:192,width:1152,height:365,columnWidths:[254,380,518],values});
 for(let r=0;r<5;r++){table.rows[r].height=73;for(let c=0;c<3;c++){
  const cell=table.getCell(r,c);cell.fill=r===0?C.ink:(r%2===0?C.pale:C.paper);
  cell.text.style={typeface:font,fontSize:r===0?23:24,bold:r===0||c===0,color:r===0?C.white:C.ink};
 }}
 table.borders.assign({style:'solid',fill:C.line,width:1});
 text(s,'Наша гипотеза: актуальный граф кода и вызовов\nдаёт полезный инсайт раньше — в Jira и PR.',64,586,1130,72,29,{bold:true,color:C.green});
}
{
 const s=slide('Подключение один раз — работа по событиям',
  'Целевая установка: закреплённый релиз на Linux-ВМ; Cloud.ru — адаптер создания ВМ с тем же installer. Владелец один раз задаёт доступы и рамки ресурсов. Модель может использовать внутренний либо отдельно согласованный внешний endpoint. Конституция исполняется инструментами, схемами, правами и лимитами. Повторная установка, восстановление и возврат обязательны, но пока не проверены для автономного сервиса.', ['docs/product/pilot/INSTALLATION.md','docs/product/pilot/CONSTITUTION.md','https://cloud.ru/docs/terraform-evolution/ug/topics/quickstart']);
 const cols=[['01','Установить релиз','Готовый образ\nLinux-ВМ'],['02','Подключить данные','Код, вызовы\nJira и Git'],['03','Задать правила','Модель, доступы\nконституция, лимиты'],['04','Получать инсайты','Автоматически\nпо событиям']];
 for(let i=0;i<4;i++){const x=64+i*295;text(s,cols[i][0],x,214,230,70,56,{bold:true,color:C.green});
  rule(s,x,309,250);text(s,cols[i][1],x,337,252,75,29,{bold:true});text(s,cols[i][2],x,435,252,90,26);}
 text(s,'В штатном потоке оператор не нужен.\nСбои, актуальность и пределы работы видны в результате.',64,574,1130,77,30,{bold:true});
}
{
 const s=slide('Что работает сейчас и что входит в MVP',
  'Сейчас узкое статическое ядро requests/FastAPI/OpenAPI JSON, digest и строки, история контекстов, синтетическое демо. PR45/46 слиты. Пока нет автономных Jira/PR, runtime-коннектора, устойчивого графа и проверенной коробки нового сервиса. Qwen 0/3 в серии остановился на invalid_model_action до семантики, поэтому сначала диагностика/согласование протокола, затем квалификация. Не обещать готовность модели или срок из старого ручного пилота.', ['docs/product/pilot/EVIDENCE.md','docs/product/pilot/BACKLOG.md','experiments/evidence_refs_v2/runs/2026-10-22-batch1/README.md']);
 text(s,'Работает в прототипе',64,200,520,55,34,{bold:true,color:C.green});
 text(s,'Узкий статический анализ API\nПроверяемые ссылки на исходники\nИстория результатов\nСинтетический сценарий демо',64,290,520,235,29);
 text(s,'Следующий автономный выпуск',695,200,520,88,34,{bold:true,color:C.green});
 text(s,'Jira и PR без ручного запуска\nОбновляемый граф и данные о вызовах\nПроверенная открытая модель\nУстановка и восстановление из коробки',695,303,520,240,28);
 rule(s,64,570,1152);
 text(s,'Преимущество, экономия и работа на коде клиента ещё требуют проверки.',64,605,1145,45,26,{bold:true});
}
{
 const s=slide('Первое подключение: один сквозной сценарий',
  'После инженерной готовности выбрать один API и связанные потребители, доступный runtime-источник и проекты Jira/Git. До отложенной серии фиксируются критерии и независимо известные последствия. Нет постоянного инженера и разметчика; человеческие минуты поддержки измеряются отдельно. Цена, срок и экономия не установлены.', ['docs/product/pilot/OFFER.md','docs/product/pilot/PROTOCOL.md','docs/product/pilot/ECONOMICS.md']);
 text(s,'Выбираем контур',64,205,520,55,34,{bold:true,color:C.green});
 text(s,'Один API и его потребители\nКод + источник наблюдаемых вызовов\nПроекты Jira и Git\nПодключённая открытая модель',64,294,540,220,28);
 text(s,'Проверяем результат',720,205,495,55,34,{bold:true,color:C.green});
 text(s,'Время до полезного инсайта\nОснования, пропуски и ложные сигналы\nРучные минуты поддержки\nСтоимость полезного результата',720,294,495,220,28);
 text(s,'Цель — полезный ответ раньше,\nс минимальным участием команды.',64,565,1145,92,38,{bold:true});
}

for(let i=0;i<p.slides.items.length;i++){
 const s=p.slides.items[i];
 const png=await p.export({slide:s,format:'png',scale:1});
 await fs.writeFile(path.join(preview,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
}
const candidate=path.join(preview,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
if(process.env.PRESENTATIONS_SKILL_DIR){
 const {finalizePresentation}=await import(pathToFileURL(path.join(process.env.PRESENTATIONS_SKILL_DIR,'container_tools/artifact_tool_utils.mjs')).href);
 await finalizePresentation({workspaceDir:path.resolve(output,'..'),candidatePath:candidate,
  finalPath:path.join(output,'pilot-presentation.pptx'),pythonExecutable:process.env.RUNTIME_PYTHON,
  integrityValidatorPath:path.join(process.env.PRESENTATIONS_SKILL_DIR,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(process.env.PRESENTATIONS_SKILL_DIR,'container_tools/inspect_presentation_layout_geometry.py'),
  explicitTotalSlideCount:8,requiredNativeTableOwnerSlides:[5],
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--require-native-table-slide','5'],
  fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,
  receiptPath:path.join(preview,'validation.json')});
}else await fs.copyFile(candidate,path.join(output,'pilot-presentation.pptx'));
// PDF is converted from the verified PPTX, so the two deliverables share content.
await promisify(execFile)(process.env.SOFFICE_BIN || 'soffice',[
 '--headless',`-env:UserInstallation=${pathToFileURL(path.join(preview,'libreoffice-profile')).href}`,
 '--convert-to','pdf','--outdir',output,path.join(output,'pilot-presentation.pptx')
],{timeout:120000});
await fs.writeFile(path.join(output,'src','slides.json'),JSON.stringify(copy,null,2)+'\n').catch(async()=>{
 await fs.mkdir(path.join(output,'src'),{recursive:true});
 await fs.writeFile(path.join(output,'src','slides.json'),JSON.stringify(copy,null,2)+'\n');
});
console.log(JSON.stringify({slides:p.slides.items.length,output,preview}));
