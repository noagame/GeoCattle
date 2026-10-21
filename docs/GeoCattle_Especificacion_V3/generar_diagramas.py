from pathlib import Path
import html, re, json, zipfile, xml.etree.ElementTree as E
P=Path(__file__).resolve().parent
source=(P.parent/'01_CASOS_DE_USO.md').read_text()
cases={m[0]:m[1] for m in re.findall(r'^\| (CU-\d+) \| ([^|]+?) \|',source,re.M)}
D=[]
def diagram(slug,title,actors,ids,notes,extra=(),relations=()):
 D.append(dict(slug=slug,title=title,actors=actors,ids=ids,notes=notes,extra=extra,relations=relations))
# Asociaciones UML no son flechas de flujo. Los diagramas generales son vistas parciales declaradas.
diagram('01_general','Vista general de actores y funciones',[
 ('admin','Administrador', ['CU-03','CU-05','CU-06']),
 ('owner','Dueño',['CU-08','CU-13','CU-20']),
 ('worker','Trabajador',['CU-15','CU-17']),
 ('vet','Veterinario',['CU-15','CU-23']),
 ('ingest','Servicio de ingestión',['CU-26']),
 ('notify','Servicio de avisos',['CU-28'])],
 ['CU-03','CU-05','CU-06','CU-08','CU-13','CU-20','CU-15','CU-17','CU-23','CU-26','CU-28'],
 ['Vista resumida: los ocho diagramas cubren los 29 casos del catálogo V3.', 'No hay herencia entre perfiles. El administrador actúa en soporte con identidad y auditoría propias.'])
diagram('02_administrador','Administrador · plataforma', [('admin','Administrador',[f'CU-{i:02}' for i in range(1,8)])],
 [f'CU-{i:02}' for i in range(1,8)],
 ['MFA obligatorio para entrar al panel global; no se representa como una aprobación del dueño.', 'La administración de soporte sobre predios se muestra también en las vistas del dueño.', 'CU-04 administra colaboradores ya incorporados por el dueño.'])
diagram('03_dueno_gestion','Dueño · predios, colaboradores y aprobación',[
 ('owner','Dueño',['CU-08','CU-09','CU-10','CU-11','CU-12','CU-13','CU-20','CU-21','CU-25','CU-29']),
 ('admin','Administrador (soporte)',['CU-08','CU-09','CU-10','CU-11','CU-12','CU-13','CU-20','CU-21','CU-25','CU-29'])],
 ['CU-08','CU-09','CU-10','CU-11','CU-12','CU-13','CU-20','CU-21','CU-25','CU-29'],
 ['Dueño: solo su cuenta y predios. Administrador: contexto de soporte registrado.', 'CU-13 y CU-21 requieren verificación reforzada del dueño; no basta un botón de confirmación.', 'CU-29 es extensión FMA P2; no implica integración oficial con SIPEC.'])
diagram('04_dueno_monitoreo_salud','Dueño · monitoreo y salud',[
 ('owner','Dueño',['CU-01','CU-02','CU-07','CU-15','CU-16','CU-19','CU-22','CU-23','CU-24','CU-27','CU-28']),
 ('admin','Administrador (soporte)',['CU-01','CU-02','CU-07','CU-15','CU-16','CU-19','CU-22','CU-23','CU-24','CU-27','CU-28'])],
 ['CU-01','CU-02','CU-07','CU-15','CU-16','CU-19','CU-22','CU-23','CU-24','CU-27','CU-28'],
 ['Las asociaciones de CU-01, CU-02 y CU-07 se refieren a la cuenta propia del actor.', 'Salud: corrección/anulación agrega historia; no borra el registro original.', 'CU-28 agrupa configuración y entrega de avisos; se descompone en la vista técnica.'])
diagram('05_trabajador','Trabajador · consultas y propuestas', [('worker','Trabajador',['CU-01','CU-02','CU-07','CU-14','CU-15','CU-16','CU-17','CU-18','CU-19','CU-27'])],
 ['CU-01','CU-02','CU-07','CU-14','CU-15','CU-16','CU-17','CU-18','CU-19','CU-27'],
 ['CU-17, CU-18 y CU-19 generan solicitudes por defecto; ver diagrama de aprobación.', 'Confianza vigente puede habilitar aplicación directa por acción y predio.', 'El trabajador reporta tratamientos administrados; no obtiene facultad de prescribir.'])
diagram('06_veterinario','Veterinario · ficha técnica y sanitaria', [('vet','Veterinario',['CU-01','CU-02','CU-07','CU-14','CU-15','CU-16','CU-22','CU-23','CU-24','CU-27'])],
 ['CU-01','CU-02','CU-07','CU-14','CU-15','CU-16','CU-22','CU-23','CU-24','CU-27'],
 ['CU-22, CU-23 y CU-24 se aplican directamente: no requieren aprobación del dueño.', 'Acceso solo a predios con membresía vigente; cada cambio conserva autoría y auditoría.', 'El perfil no administra colaboradores, DIIO, predios ni asignaciones de collar.'])
diagram('07_aprobacion','Propuestas del trabajador y decisiones del dueño',[
 ('worker','Trabajador',['CU-17','CU-18','CU-19']),('owner','Dueño',['CU-20','CU-21'])],
 ['CU-17','CU-18','CU-19','CU-20','CU-21'],
 ['Las solicitudes persisten sin modificar la ficha efectiva hasta una decisión autorizada.', '«include» significa comportamiento obligatorio; «extend» significa una extensión condicional.', 'La aplicación directa por confianza es una alternativa; no hereda permisos adicionales.', 'La revisión/aplicación incluye control de versión, auditoría e idempotencia.'],
 extra=[('AUX-01','Persistir propuesta y notificar al dueño'),('AUX-02','Aplicar cambio con decisión y auditoría'),('AUX-03','Aplicar directamente por confianza')],
 relations=[('CU-17','AUX-01','include',''),('CU-18','AUX-01','include',''),('CU-19','AUX-01','include',''),('AUX-02','CU-20','extend','[dueño aprueba]'),('AUX-03','AUX-01','extend','[confianza vigente]'),('AUX-03','AUX-02','include','')])
diagram('08_actores_tecnicos','Servicios técnicos · ingestión, alertas y avisos',[
 ('collar','Collar / red IoT',['CU-26']),('ingest','Servicio de ingestión',['CU-26','CU-27']),
 ('notify','Servicio de avisos',['CU-28']),('owner','Dueño',['CU-27','CU-28']),
 ('worker','Trabajador',['CU-27']),('vet','Veterinario',['CU-27'])],
 ['CU-26','CU-27','CU-28'],
 ['Los servicios técnicos son actores externos al límite de la aplicación de gestión.', 'CU-27 comprende generar (servicio) y atender (personas); no son permisos intercambiables.', 'CU-28 comprende configurar (dueño) y entregar avisos (servicio).', 'Cada servicio usa credencial técnica y alcance restringido.'])

def wrap(text,maxlen=37):
 words=text.split(); lines=[]; cur=''
 for w in words:
  if len(cur)+len(w)+1>maxlen:
   lines.append(cur);cur=w
  else:cur=(cur+' '+w).strip()
 if cur:lines.append(cur)
 return lines

def textsvg(x,y,lines,size=16,color='#17384d',anchor='middle',weight='400'):
 return ''.join(f'<text x="{x}" y="{y+i*(size+5)}" font-family="sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{html.escape(line)}</text>' for i,line in enumerate(lines))

mx=E.Element('mxfile',host='app.diagrams.net',version='24.7.17')
for d in D:
 nodes=[(i,cases[i]) for i in d['ids']]+list(d['extra']); n=len(nodes)
 # Columna única para casos; extensiones a la derecha cuando están presentes.
 special=d['slug']=='07_aprobacion'
 H=max(900,290+len(d['ids'])*105+len(d['notes'])*28)
 if special:H=1180
 W=1580 if special else 1360
 boundary=(300,120,W-600,H-260)
 positions={}
 for i,(code,label) in enumerate(nodes):
  if special and code.startswith('AUX'):
   j=int(code[-2:])-1;positions[code]=(1120,290+j*265,330,84)
  else:positions[code]=(680 if not special else 650,210+d['ids'].index(code)*105,510 if not special else 460,78)
 if special:boundary=(300,120,1230,H-280)
 actorpos={}
 # Un solo actor a izquierda; múltiples alternan lados salvo aprobación con panel auxiliar a derecha.
 left=[a for i,a in enumerate(d['actors']) if i%2==0 or special]
 right=[a for i,a in enumerate(d['actors']) if i%2==1 and not special]
 for side,aa in [('left',left),('right',right)]:
  for j,a in enumerate(aa):
   y=210+j*max(180,(H-440)/max(len(aa),1)); x=125 if side=='left' else W-125
   actorpos[a[0]]=(x,y,side)
 svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
 '<defs><marker id="open" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="#7b3e94" stroke-width="1.4"/></marker></defs>',f'<rect width="{W}" height="{H}" fill="#f7f9fc"/>',textsvg(40,49,[d['title']],27,anchor='start',weight='700'),textsvg(40,81,['GeoCattle V3 · diagrama UML de casos de uso · 20 octubre 2026'],14,anchor='start',color='#526a7d')]
 bx,by,bw,bh=boundary
 svg += [f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="8" fill="white" stroke="#607c91" stroke-width="1.6"/>',textsvg(bx+20,by+30,['GeoCattle · aplicación de gestión'],17,anchor='start',weight='700')]
 # Asociaciones detrás de elipses. Líneas sólidas sin flecha: comunicación, no secuencia.
 for aid,aname,ids in d['actors']:
  ax,ay,side=actorpos[aid]
  for code in ids:
   cx,cy,rw,rh=positions[code]; ex=cx-rw/2 if side=='left' else cx+rw/2
   svg.append(f'<line x1="{ax+30 if side=="left" else ax-30}" y1="{ay+42}" x2="{ex}" y2="{cy}" stroke="#a0afbd" stroke-width="1.05"/>')
 for code,label in nodes:
  cx,cy,rw,rh=positions[code];fill='#eaf3fb' if code.startswith('CU') else '#f5edf9'
  svg.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rw/2}" ry="{rh/2}" fill="{fill}" stroke="#526e85" stroke-width="1.4"/>')
  lines=wrap(code+' · '+label,43 if not special or code.startswith('CU') else 29)
  svg.append(textsvg(cx,cy-(len(lines)-1)*10+5,lines,15))
 for aid,aname,ids in d['actors']:
  ax,ay,_=actorpos[aid]
  svg += [f'<circle cx="{ax}" cy="{ay}" r="17" fill="white" stroke="#294b61" stroke-width="2"/>',f'<path d="M{ax} {ay+17} V{ay+67} M{ax-29} {ay+34} H{ax+29} M{ax} {ay+67} L{ax-24} {ay+100} M{ax} {ay+67} L{ax+24} {ay+100}" fill="none" stroke="#294b61" stroke-width="2"/>',textsvg(ax,ay+129,wrap(aname,23),15,weight='700')]
 for src,tgt,kind,condition in d['relations']:
  x1,y1,w1,h1=positions[src];x2,y2,w2,h2=positions[tgt]
  # Los conectores UML auxiliares se curvan para mantener sus rótulos fuera de elipses.
  if src.startswith('AUX') and tgt.startswith('AUX'):
   sx,sy=x1+w1/2,y1;tx,ty=x2+w2/2,y2
   outer=1430 if kind=='extend' else 1340
   path=f'M {sx} {sy} H {outer} V {ty} H {tx}'
   lx,ly=outer,(sy+ty)/2
  else:
   if x1>x2:sx=x1-w1/2;tx=x2+w2/2
   else:sx=x1+w1/2;tx=x2-w2/2
   sy=y1;ty=y2
   path=f'M {sx} {sy} L {tx} {ty}';lx=(sx+tx)/2;ly=(sy+ty)/2-9
  svg.append(f'<path d="{path}" fill="none" stroke="#7b3e94" stroke-width="1.4" stroke-dasharray="6 4" marker-end="url(#open)"/>')
  svg.append(textsvg(lx,ly,['«'+kind+'»']+([condition] if condition else []),11,color='#7b3e94'))
 for j,note in enumerate(d['notes']):svg.append(textsvg(40,H-100+j*25,[note],13,anchor='start',color='#435d70'))
 svg.append('</svg>');(P/(d['slug']+'.svg')).write_text('\n'.join(svg))
 # PlantUML mantiene semántica y nombres sin depender de layout de imagen.
 puml=['@startuml','left to right direction','skinparam packageStyle rectangle','skinparam shadowing false','title '+d['title']]
 for aid,name,ids in d['actors']:puml.append(f'actor "{name}" as {aid}')
 puml.append('rectangle "GeoCattle · aplicación de gestión" {')
 for code,label in nodes:puml.append('  usecase "'+code+'\\n'+label+'" as '+code.replace('-','_'))
 puml.append('}')
 for aid,name,ids in d['actors']:
  for code in ids:puml.append(f'{aid} -- {code.replace("-","_")}')
 for src,tgt,kind,cond in d['relations']:puml.append(f'{src.replace("-","_")} ..> {tgt.replace("-","_")} : <<{kind}>>'+('\\n'+cond if cond else ''))
 for j,note in enumerate(d['notes']):puml.append('note "'+note.replace('"','\"')+'" as note'+str(j))
 puml.append('@enduml');(P/(d['slug']+'.puml')).write_text('\n'.join(puml)+'\n')
 # Draw.io: actores, límite, elipses y conectores UML editables.
 diagram=E.SubElement(mx,'diagram',id=d['slug'],name=d['title']);model=E.SubElement(diagram,'mxGraphModel',page='1',pageWidth=str(W),pageHeight=str(H),grid='1',gridSize='10');root=E.SubElement(model,'root');E.SubElement(root,'mxCell',id='0');E.SubElement(root,'mxCell',id='1',parent='0')
 def cell(id,value,x,y,w,h,style):
  z=E.SubElement(root,'mxCell',id=id,value=value,style=style,vertex='1',parent='1');E.SubElement(z,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),attrib={'as':'geometry'})
 cell('boundary','GeoCattle · aplicación de gestión',bx,by,bw,bh,'rounded=0;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacing=15;fillColor=#ffffff;strokeColor=#607c91;fontSize=17;')
 cell('title',d['title'],35,30,W-70,60,'text;html=1;fontSize=25;align=left;fontStyle=1;')
 for aid,name,ids in d['actors']:
  ax,ay,side=actorpos[aid];cell(aid,name,ax-40,ay-17,80,128,'shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;fillColor=#ffffff;fontSize=14;')
 for code,label in nodes:
  cx,cy,w,h=positions[code];cell(code,code+'<br>'+html.escape(label),cx-w/2,cy-h/2,w,h,'ellipse;whiteSpace=wrap;html=1;fillColor=#eaf3fb;strokeColor=#526e85;fontSize=15;')
 def edge(a,b,label,style):
  z=E.SubElement(root,'mxCell',id='edge-'+str(len(root)),value=label,edge='1',parent='1',source=a,target=b,style=style);E.SubElement(z,'mxGeometry',relative='1',attrib={'as':'geometry'})
 for aid,name,ids in d['actors']:
  for code in ids:edge(aid,code,'','endArrow=none;startArrow=none;html=1;strokeColor=#a0afbd;')
 for a,b,k,cond in d['relations']:edge(a,b,'«'+k+'»'+('<br>'+cond if cond else ''),'dashed=1;endArrow=open;html=1;strokeColor=#7b3e94;fontSize=11;')
 for j,note in enumerate(d['notes']):cell('note'+str(j),html.escape(note),35,H-110+j*25,W-70,25,'text;html=1;align=left;fontSize=12;')
E.indent(mx);(P/'CASOS_DE_USO_V3.drawio').write_text(E.tostring(mx,encoding='unicode'))
(P/'catalogo_diagramas.json').write_text(json.dumps(D,ensure_ascii=False,indent=2))
# Cobertura del catálogo: cada caso aparece en al menos un diagrama.
coverage={code:[d['slug'] for d in D if code in d['ids']] for code in cases}
assert all(coverage.values())
read=['# GeoCattle V3 — Diagramas de casos de uso','','Ocho vistas UML de los 29 casos definidos en la especificación V3. Las imágenes son resúmenes visuales de los casos documentados; no agregan permisos nuevos.','','| Vista | Imagen | Vector | Fuente |','|---|---|---|---|']
for d in D:read.append(f'| {d["title"]} | [PNG]({d["slug"]}.png) | [SVG]({d["slug"]}.svg) | [PlantUML]({d["slug"]}.puml) |')
read += ['','Archivo editable multipágina: [CASOS_DE_USO_V3.drawio](CASOS_DE_USO_V3.drawio).','','## Convenciones UML','','- Actor fuera del límite del sistema; elipse dentro del sistema = caso de uso.', '- Línea continua sin flecha = asociación; no representa orden de pasos.', '- `include`: flecha discontinua desde el caso que incluye hacia el comportamiento obligatorio.', '- `extend`: flecha desde la extensión hacia el caso base; condición indicada entre corchetes.', '- No se dibuja el inicio de sesión como `include` de cada operación: una sesión válida es precondición.', '- AUX-01 a AUX-03 descomponen comportamiento ya definido; no son CU-30 ni requisitos adicionales.', '- El diagrama de aprobación no es un diagrama de secuencia: el orden transaccional sigue en el documento de casos.', '- Persistir y notificar significa guardar propuesta y cola de aviso; el envío externo puede ocurrir después.','','## Decisiones representadas','','Administrador global separado de dueño; MFA para administrador y step-up para acciones sensibles del dueño. Trabajador sujeto a revisión salvo confianza por acción. Veterinario con cambios directos. FMA continúa como extensión P2.','','## Cobertura completa','','| Caso | Nombre | Vistas |','|---|---|---|']
for code,title in cases.items():read.append(f'| {code} | {title} | '+', '.join(coverage[code])+' |')
(P/'README.md').write_text('\n'.join(read)+'\n')
print('Generados 8 SVG, 8 PlantUML y Draw.io multipágina; cobertura de 29/29 casos.')
