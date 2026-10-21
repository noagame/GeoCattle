import fs from 'node:fs/promises';
import path from 'node:path';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const out = path.dirname(new URL(import.meta.url).pathname);
const cut = '2026-10-21';
const noWork = ['2026-12-08','2026-12-25','2027-01-01'];
const rows = [
 ['P01','Consolidar alcance V3 y trazabilidad','Fabián','',cut,1,2,'Documentado','CU-01 a CU-29','44 RF, 22 RNF y diagramas consistentes'],
 ['P02','Integrar migración aditiva y API V3','Fabián','',cut,1,4,'Integrado local','RF-01 a RF-44','Código y migración preservan datos V1'],
 ['P03','Integrar los cuatro paneles web','Boris','',cut,1,4,'Integrado local','CU-03 a CU-25','Pantallas conectadas a API según perfil'],
 ['P04','Revisar contrato API y alcance por predio','Fabián','P01,P02','2026-10-22',2,4,'Planificado','RF-01,RF-42','Denegar IDs ajenos y conservar contexto'],
 ['P05','Revisar navegación y contexto por perfil','Boris','P01,P03','2026-10-22',2,4,'Planificado','CU-01,CU-15,CU-16','Cuatro identidades y navegación por permisos'],
 ['P06','Validar migración con datos heredados','Fabián','P04','2026-10-26',3,4,'Planificado','RNF-06,RNF-07','Crear desde cero y actualizar copia V1'],
 ['P07','Cerrar inventario y diseño de hardware','Boris','P05','2026-10-26',5,4,'Externo pendiente','Hardware anterior','BOM, energía, RF y montaje revisados'],
 ['P08','Ensayar MFA, sesiones y doble verificación','Fabián','P06','2026-10-29',4,4,'Planificado','RF-02 a RF-04; RNF-02 a RNF-05','TOTP, expiración, replay, suspensión y CSRF'],
 ['P09','Probar tareas de los cuatro perfiles','Boris','P05','2026-11-02',5,4,'Planificado','CU-01 a CU-25','Flujos navegador con dos dueños y colaborador'],
 ['P10','Probar aprobación, confianza y concurrencia','Fabián','P08','2026-11-04',5,4,'Planificado','RF-24 a RF-29','Pendiente sin efecto y aplicación exactamente una vez'],
 ['P11','Programar y probar dos nodos iniciales','Boris','P07,P09','2026-11-09',5,4,'Externo pendiente','CU-26; HW03','Lecturas reales y firmware identificado'],
 ['P12','Validar ficha técnica y salud inmutable','Fabián','P10','2026-11-11',5,4,'Planificado','RF-15,RF-30 a RF-33','Veterinario directo, correcciones y unidades'],
 ['P13','Verificar mapa, puntos y gateways','Boris','P09,P11','2026-11-16',5,4,'Planificado','RF-13,RF-22,RF-34','Cuatro vértices, geometría válida y origen visible'],
 ['P14','Validar KPIs, auditoría y observabilidad','Fabián','P12','2026-11-18',5,4,'Planificado','RF-07 a RF-10; RNF-16','Conteos sin duplicados, p95 y auditoría sin secretos'],
 ['P15','Integrar radio y medir banco académico','Boris','P11,P13','2026-11-23',5,4,'Externo pendiente','CU-26 a CU-28','Recepción real, secuencia y recuperación de datos'],
 ['P16','Medir carga e idempotencia de telemetría','Fabián','P14','2026-11-25',5,4,'Planificado','RNF-08 a RNF-10','70 nodos, 5 clientes, 10 min y 100 eventos'],
 ['P17','Ejecutar usabilidad con cuatro perfiles','Boris','P13,P15','2026-11-30',5,4,'Externo pendiente','RNF-14','Móvil 360 px, tareas y tiempos observados'],
 ['P18','Ensayar respaldo, restauración y corte WAN','Fabián','P16','2026-12-02',4,4,'Planificado','RNF-12,RNF-13','RPO/RTO medidos y recuperación de cola'],
 ['P19','Actualizar manuales, informe y evidencias','Boris','P17','2026-12-07',4,4,'Planificado','CU-01 a CU-29','Documentación con alcance real y pendientes'],
 ['P20','Verificar correo y avisos con proveedor real','Fabián','P18','2026-12-09',3,4,'Externo pendiente','RF-18,RF-40','Enrolamiento entregado, fallos y reintentos'],
 ['P21','Cerrar regresión y versión académica','Fabián','P06,P08,P10,P12,P14,P16,P18,P20','2026-12-14',2,4,'Planificado','P0 y P1','Sin defectos críticos y evidencia reproducible'],
 ['P22','Demostrar cadena y obtener revisión de uso','Boris','P15,P17,P19','2026-12-14',2,4,'Externo pendiente','H2 académico','Nodo real, mapa, evento y dato vencido'],
 ['P23','Medir preserie predial durante cuatro semanas','Boris','P07,P11,P15,P17,P21,P22','2026-12-16',18,3,'Externo condicionado','K01,K02,K08,ME01,EN01','Cobertura, autonomía, seguridad y productor'],
 ['P24','Medir continuidad y soporte de la preserie','Fabián','P21,P22','2026-12-16',18,2,'Externo condicionado','RNF-11; RTO/RPO','Monitor por minuto y ventana mínima de 7 días'],
 ['P25','Consolidar entrega documental académica','Fabián','P19,P21,P22','2026-12-16',3,2,'Planificado','Informe y Gantt','Acta académica separada del piloto de campo'],
];
const dt=s=>new Date(`${s}T12:00:00Z`);
const iso=d=>d.toISOString().slice(0,10);
const isWork=d=>![0,6].includes(d.getUTCDay())&&!noWork.includes(iso(d));
const finish=(s,n)=>{let d=dt(s);let left=n-1;while(left){d.setUTCDate(d.getUTCDate()+1);if(isWork(d))left--;}return iso(d);};
const tasks=rows.map(([id,task,owner,deps,start,days,hours,status,trace,criterion])=>({id,task,owner,deps:deps?deps.split(','):[],start,days,hours,status,trace,criterion,end:finish(start,days)}));
const byId=new Map(tasks.map(t=>[t.id,t]));
for(const t of tasks)for(const id of t.deps){if(!byId.has(id))throw Error(`Dependencia no existe: ${id}`);if(byId.get(id).end>=t.start)throw Error(`Dependencia fuera de orden: ${id} / ${t.id}`);}
const capacity={};for(const t of tasks){for(let d=dt(t.start);iso(d)<=t.end;d.setUTCDate(d.getUTCDate()+1)){if(!isWork(d))continue;const k=`${t.owner}/${iso(d)}`;capacity[k]=(capacity[k]||0)+t.hours;}}
if(Math.max(...Object.values(capacity))>6)throw Error('Carga diaria superior a 6 h');
const weeks=Array.from({length:13},(_,i)=>{const d=dt('2026-10-19');d.setUTCDate(d.getUTCDate()+i*7);return iso(d);});
const workbook=Workbook.create();const sheet=workbook.worksheets.add('Gantt V3');sheet.showGridLines=false;sheet.tabColor='#203A5A';
sheet.getRange('A1:Y61').format.font={name:'Arial',size:10,color:'#1C2939'};
sheet.getRange('A1:Y61').format.verticalAlignment='center';
sheet.getRange('A2').values=[['GeoCattle — Carta Gantt V3']];sheet.getRange('A2').format.font={name:'Arial',size:16,bold:true,color:'#203A5A'};
sheet.getRange('A3').values=[['Corte: 21/10/2026. Plan de revisión y aceptación: 21/10/2026–12/01/2027.']];
sheet.getRange('A4').values=[['Fechas y esfuerzo estimados. Las tareas de campo dependen de equipos, clima y acceso al predio.']];
sheet.getRange('A5').values=[['Ámbar: inicio, duración, h/día y estado editables. Fin, esfuerzo y barras se recalculan.']];
const headers=['ID','Tarea','Responsable propuesto','Predecesoras','Inicio','Días hábiles','Fin','h/día','Esfuerzo (h)','Estado al corte','Trazabilidad','Criterio de cierre',...weeks.map((_,i)=>`S${i+1}`)];
sheet.getRange('A6:Y6').values=[headers];sheet.getRange('A6:Y6').format={fill:'#203A5A',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:36,wrapText:true,horizontalAlignment:'center'};
sheet.getRange('M7:Y7').values=[weeks.map(dt)];sheet.getRange('M7:Y7').setNumberFormat('dd/mm');sheet.getRange('M7:Y7').format={fill:'#EAF0F7',horizontalAlignment:'center',font:{name:'Arial',size:10,bold:true}};
const first=8,last=first+tasks.length-1;
sheet.getRange(`A${first}:L${last}`).values=tasks.map(t=>[t.id,t.task,t.owner,t.deps.join(', '),dt(t.start),t.days,null,t.hours,null,t.status,t.trace,t.criterion]);
sheet.getRange(`E${first}:E${last}`).setNumberFormat('dd/mm/yyyy');sheet.getRange(`G${first}:G${last}`).setNumberFormat('dd/mm/yyyy');
sheet.getRange(`F${first}:F${last}`).setNumberFormat('0');sheet.getRange(`H${first}:I${last}`).setNumberFormat('0');
sheet.getRange(`A${first}:Y${last}`).format.rowHeight=42;
sheet.getRange(`B${first}:D${last}`).format.wrapText=true;sheet.getRange(`J${first}:L${last}`).format.wrapText=true;
for(const col of ['E','F','H','J'])sheet.getRange(`${col}${first}:${col}${last}`).format.fill='#FFF2CE';
sheet.getRange(`F${first}:F${last}`).dataValidation={rule:{type:'whole',operator:'between',formula1:1,formula2:60}};
sheet.getRange(`H${first}:H${last}`).dataValidation={rule:{type:'whole',operator:'between',formula1:1,formula2:6}};
sheet.getRange(`J${first}:J${last}`).dataValidation={rule:{type:'list',values:['Documentado','En integración','Integrado local','Validado local','Planificado','Externo pendiente','Externo condicionado','Completado']}};
sheet.getRange('A37').values=[['Calendario no laborable propuesto']];sheet.getRange('A37').format.font.bold=true;
sheet.getRange('A38:B40').values=noWork.map(s=>[null,dt(s)]);sheet.getRange('B38:B40').setNumberFormat('dd/mm/yyyy');
sheet.getRange('D37').values=[['Máximo planificado: 6 h/persona/día. No incluye dedicación completa del equipo.']];
sheet.getRange('D38').values=[['Hitos: cierre académico 18/12/2026; preserie condicionada hasta 12/01/2027.']];
sheet.getRange('D39').values=[['FMA e intercambio SIPEC: extensión P2 sin fecha ni implementación oficial comprometidas.']];
sheet.getRange('D40').values=[['Lote 70: solo después de preserie aceptada, presupuesto y decisión del productor.']];
sheet.getRange('A43').values=[['Fuentes del plan']];sheet.getRange('A43').format.font.bold=true;
sheet.getRange('A44').values=[['Informe de 04/10/2026: sección VII, tabla “Fase / Semanas / Dependencia y entrega / Responsable”.']];
sheet.getRange('A45').values=[['Especificación V3 de 20/10/2026: 29 CU, 44 RF y 22 RNF. Confirmación: veterinario directo.']];
sheet.getRange('A46').values=[['Plan revisable; no se dispone de fecha académica oficial ni de agenda de terreno confirmada.']];
sheet.getRange('A48').values=[['Esfuerzo planificado por responsable (h)']];sheet.getRange('A48').format.font.bold=true;
sheet.getRange('A49:A50').values=[['Fabián'],['Boris']];
sheet.getRange('B49').formulas=[[`=SUMIFS(I${first}:I${last},C${first}:C${last},A49)`]];
sheet.getRange('B50').formulas=[[`=SUMIFS(I${first}:I${last},C${first}:C${last},A50)`]];
for(let i=0;i<tasks.length;i++){const r=first+i;sheet.getRange(`G${r}`).formulas=[[`=WORKDAY(E${r},F${r}-1,$B$38:$B$40)`]];sheet.getRange(`I${r}`).formulas=[[`=F${r}*H${r}`]];const forms=weeks.map((_,i)=>{const c=String.fromCharCode(77+i);return `=IF(AND($E${r}<=${c}$7+6,$G${r}>=${c}$7),"x","")`;});sheet.getRange(`M${r}:Y${r}`).formulas=[forms];sheet.getRange(`M${r}:Y${r}`).format.horizontalAlignment='center';}
for(const [start,end,width] of [['A','A',8],['B','B',44],['C','C',20],['D','D',22],['E','E',14],['F','F',11],['G','G',14],['H','I',11],['J','J',22],['K','K',25],['L','L',50],['M','Y',7]])sheet.getRange(`${start}1:${end}50`).format.columnWidth=width;
sheet.getRange(`M${first}:Y${last}`).conditionalFormats.addCustom(`AND(M$7<=$G${first},M$7+6>=$E${first})`,{fill:'#BBD0E8',font:{color:'#203A5A',bold:true}});
sheet.freezePanes.freezeRows(7);sheet.freezePanes.freezeColumns(2);
workbook.recalculate();
const expectedHours=tasks.reduce((a,t)=>a+t.days*t.hours,0);
for(let i=0;i<tasks.length;i++){const actual=sheet.getRange(`I${first+i}`).values[0][0];if(actual!==tasks[i].days*tasks[i].hours)throw Error(`Esfuerzo incorrecto ${tasks[i].id}`);}
for(let i=0;i<tasks.length;i++){const serial=sheet.getRange(`G${first+i}`).values[0][0];const actual=new Date((serial-25569)*86400000).toISOString().slice(0,10);if(actual!==tasks[i].end)throw Error(`Fecha incorrecta ${tasks[i].id}: ${actual}`);}
const check=await workbook.inspect({kind:'table',range:'Gantt V3!E8:J12',include:'values,formulas',tableMaxRows:5,tableMaxCols:6,maxChars:4000});
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:20},maxChars:3000});
const original=sheet.getRange('F8').values[0][0];sheet.getRange('F8').values=[[7]];if(sheet.getRange('I8').values[0][0]!==14)throw Error('No recalcula esfuerzo');if(sheet.getRange('N8').values[0][0]!=='x')throw Error('No recalcula barra temporal');sheet.getRange('F8').values=[[original]];workbook.recalculate();
await fs.writeFile(path.join(out,'qa','verificacion_gantt.txt'),`${check.ndjson}\n${errors.ndjson}\n${JSON.stringify({tasks:tasks.length,expectedHours,maxDailyHours:Math.max(...Object.values(capacity)),finish:tasks.at(-3).end,dependencyCheck:true,inputRecalculation:true},null,2)}`);
const preview=await workbook.render({sheetName:'Gantt V3',range:'A1:J19',scale:1.4,format:'png'});await fs.writeFile(path.join(out,'qa','gantt_hoja.png'),new Uint8Array(await preview.arrayBuffer()));
const preview2=await workbook.render({sheetName:'Gantt V3',range:'J6:Y32',scale:1.4,format:'png'});await fs.writeFile(path.join(out,'qa','gantt_calendario.png'),new Uint8Array(await preview2.arrayBuffer()));
const preview3=await workbook.render({sheetName:'Gantt V3',range:'A20:L50',scale:1.2,format:'png'});await fs.writeFile(path.join(out,'qa','gantt_cierre.png'),new Uint8Array(await preview3.arrayBuffer()));
const output=await SpreadsheetFile.exportXlsx(workbook);await output.save(path.join(out,'Carta_Gantt_GeoCattle_V3_2026-10-21.xlsx'));
await fs.writeFile(path.join(out,'gantt_v3.json'),JSON.stringify({cut,nonWorkingDates:noWork,weeks,tasks},null,2));
const esc=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const width=1950,rowH=42,top=160,gridX=1040,colW=65,height=top+tasks.length*rowH+150;
let svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#fff"/><style>text{font-family:Arial,sans-serif;fill:#203047}.h{font-size:26px;font-weight:bold}.body{font-size:15px}.small{font-size:13px}.head{fill:#fff;font-size:14px;font-weight:bold}</style><text x="32" y="45" class="h">GeoCattle — Carta Gantt V3</text><text x="32" y="76" class="body">Corte 21/10/2026 · Dos responsables · 12 semanas para revisión, aceptación y preserie condicionada</text><text x="32" y="101" class="small">Fechas estimadas. El cierre académico y la habilitación comercial tienen criterios de aceptación diferentes.</text><rect x="24" y="120" width="1902" height="40" fill="#203A5A"/>`;
for(const [x,label]of[[32,'ID'],[88,'Tarea'],[530,'Responsable'],[650,'Inicio'],[755,'Fin'],[866,'Estado al corte']])svg+=`<text x="${x}" y="145" class="head">${label}</text>`;
weeks.forEach((s,i)=>{svg+=`<text x="${gridX+i*colW+colW/2}" y="137" text-anchor="middle" class="head">S${i+1}</text><text x="${gridX+i*colW+colW/2}" y="152" text-anchor="middle" class="head">${s.slice(8)}/${s.slice(5,7)}</text>`;});
const short=s=>`${s.slice(8)}/${s.slice(5,7)}/${s.slice(2,4)}`;
tasks.forEach((t,i)=>{const y=top+i*rowH;if(i%2===0)svg+=`<rect x="24" y="${y}" width="1902" height="${rowH}" fill="#F1F5FA"/>`;for(const [x,label]of[[32,t.id],[88,t.task],[530,t.owner],[650,short(t.start)],[755,short(t.end)],[866,t.status]])svg+=`<text x="${x}" y="${y+26}" class="${x===88?'body':'small'}">${esc(label)}</text>`;weeks.forEach((s,j)=>{const d=dt(s);d.setUTCDate(d.getUTCDate()+6);if(t.start<=iso(d)&&t.end>=s)svg+=`<rect x="${gridX+j*colW+4}" y="${y+8}" width="${colW-8}" height="${rowH-16}" rx="4" fill="${t.status.startsWith('Externo')?'#E8B46B':['Documentado','Integrado local','Validado local'].includes(t.status)?'#5EAB91':'#7296BF'}"/>`;});});
const y=top+tasks.length*rowH+34;
svg+=`<text x="32" y="${y}" class="body">Azul: integración/revisión planificada · Verde: documentado o integrado local · Ámbar: evidencia externa pendiente o condicionada.</text><text x="32" y="${y+28}" class="body">Software y demo: hasta 15/12; consolidación académica: 18/12; preserie condicionada: 16/12–12/01.</text><text x="32" y="${y+56}" class="small">El lote de 70 collares y la integración oficial SIPEC no tienen fecha comprometida. Fechas no laborables propuestas: 08/12, 25/12 y 01/01.</text><text x="32" y="${y+80}" class="small">La tabla editable contiene dependencias, criterios de cierre, trazabilidad y esfuerzo por tarea. La S1 empieza el lunes 19/10 y el trabajo el miércoles 21/10.</text></svg>`;
await fs.writeFile(path.join(out,'Carta_Gantt_GeoCattle_V3_2026-10-21.svg'),svg);
const md=`# Carta Gantt GeoCattle V3\n\nCorte: **21 de octubre de 2026**. Esta versión sustituye la planificación relativa de ocho semanas del informe del 4 de octubre. El cronograma ofrece fechas de revisión y aceptación para el alcance V3 y conserva las pruebas físicas como una línea condicionada.\n\n![Carta Gantt](Carta_Gantt_GeoCattle_V3_2026-10-21.svg)\n\n[Plan editable en Excel](Carta_Gantt_GeoCattle_V3_2026-10-21.xlsx).\n\n## Criterios y supuestos\n\n- Dos responsables propuestos: Fabián Del Villar coordina datos/API/seguridad; Boris Baier coordina interfaz, integración IoT y validación. La asignación conserva la distribución del informe y permite revisión cruzada.\n- No existe una fecha académica oficial ni disponibilidad predial confirmada en las fuentes. Las fechas son una línea base revisable, no compromisos de terceros.\n- Semanas de lunes a domingo. S1 empieza el 19/10; las tareas comienzan el 21/10. La S13 es parcial y muestra el cierre de preserie hasta el 12/01/2027.\n- La hoja usa días hábiles de lunes a viernes y tres fechas propuestas sin trabajo: 08/12, 25/12 y 01/01. Confirmar disponibilidad del equipo en fin de año y ajustar las entradas del calendario antes de comprometer terreno.\n- Dedicación máxima planificada: 6 horas por persona/día. Los esfuerzos son estimaciones de trabajo futuro, no horas efectivamente ejecutadas por personas o subagentes.\n- “Integrado local” indica código presente y comprobaciones locales disponibles. No demuestra carga, cobertura, autonomía ni aceptación del productor.\n- Las predecesoras se verifican al generar esta línea base. En Excel se editan inicio/duración/h/día/estado; fin, esfuerzo y barras cambian. Las dependencias deben revisarse al cambiar fechas.\n- FMA y eventual intercambio SIPEC siguen siendo P2. Registrar un formulario local no equivale a emitirlo oficialmente. El lote de 70 se programa solo tras aceptar preserie y presupuesto.\n\n## Tareas y dependencias\n\n| ID | Tarea | Responsable propuesto | Inicio | Fin | Predecesoras | Estado al corte | Criterio de cierre |\n|---|---|---|---|---|---|---|\n${tasks.map(t=>`| ${t.id} | ${t.task} | ${t.owner} | ${t.start} | ${t.end} | ${t.deps.join(', ')||'—'} | ${t.status} | ${t.criterion} |`).join('\n')}\n\n## Hitos\n\n| Hito | Fecha objetivo | Evidencia exigida |\n|---|---|---|\n| H1 Base V3 integrada localmente | 21/10/2026 | Migración aditiva, API, cuatro paneles y ejecución de comprobaciones locales documentadas. |\n| H2 Versión académica verificada | 15/12/2026 | Regresión, MFA, aislamiento, aprobación, ficha sanitaria, carga, restauración y demo real. |\n| H3 Entrega documental académica | 18/12/2026 | Informe, Gantt, manual, inventario y resultados distinguiendo pendiente/ejecutado. |\n| H4 Preserie aceptada | 12/01/2027 condicionado | Cuatro semanas de campaña, cobertura/autonomía/continuidad/montaje y acta del productor. |\n| H5 Habilitación de 70 collares | Sin fecha | H4 aprobado, costo revisado, fabricación, instalación y capacitación. |\n\n## Fuentes\n\n- Informe más reciente: \`Entregables_GeoCattle_2026-10-04/Informe_2_GeoCattle_con_Viabilidad_y_Flujo_Caja_2026-10-04.docx\`, sección “VII Cronograma ajustado y organización”, tabla de encabezados “Fase / Semanas / Dependencia y entrega / Responsable”.\n- \`docs/especificacion-v3/00_ANALISIS_Y_ALCANCE.md\`, \`01_CASOS_DE_USO.md\` y \`02_REQUERIMIENTOS.md\`.\n- Decisión confirmada por el usuario: veterinario con cambios directos; trabajador con aprobación salvo confianza por acción.\n\nLa evidencia exacta de implementación se mantiene en \`EVIDENCIA_IMPLEMENTACION.md\` y en \`actualizacion_informe.md\` de la raíz del proyecto.\n`;
await fs.writeFile(path.join(out,'CARTA_GANTT_V3.md'),md);
console.log(JSON.stringify({tasks:tasks.length,expectedHours,maxDailyHours:Math.max(...Object.values(capacity)),lastFieldDate:byId.get('P23').end,output:path.join(out,'Carta_Gantt_GeoCattle_V3_2026-10-21.xlsx')}));
