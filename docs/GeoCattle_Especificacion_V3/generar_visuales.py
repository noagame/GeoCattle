from pathlib import Path
import json,html,re,xml.etree.ElementTree as E
P=Path(__file__).resolve().parent
T=json.loads((P/'catalogo_modelo.json').read_text())
colors={'Identidad':'#e8efff','Predios':'#e0f2ed','Ganado y espacio':'#eaf2d8','IoT':'#e0f0ff','Operación':'#fff0d7','Aprobaciones':'#ffeadf','Salud':'#f7e5f0','Administración':'#ece8ff','Extensión FMA':'#efefef'}
mx=E.Element('mxfile',host='app.diagrams.net',version='24.7.17')
for group in dict.fromkeys(t['group'] for t in T):
    ts=[t for t in T if t['group']==group]; diag=E.SubElement(mx,'diagram',id=group,name=group)
    model=E.SubElement(diag,'mxGraphModel',dx='1422',dy='850',grid='1',gridSize='10',page='1',pageScale='1',pageWidth='1500',pageHeight='2500'); root=E.SubElement(model,'root'); E.SubElement(root,'mxCell',id='0'); E.SubElement(root,'mxCell',id='1',parent='0')
    placements={}; heights=[80,80,80]
    for t in ts:
        col=min(range(3),key=lambda n:heights[n]); y=heights[col]; x=30+col*480; h=50+len(t['columns'])*22
        placements[t['name']]=(x,y,h); heights[col]+=h+90
        text='<b>'+t['name']+'</b><br><hr>'+ '<br>'.join(html.escape(c['name']+' : '+c['type']+(' [PK]' if 'PRIMARY KEY' in c['flags'] else '')+(' [FK]' if 'REFERENCES' in c['flags'] else '')) for c in t['columns'])
        cell=E.SubElement(root,'mxCell',id=t['name'],value=text,style=f'rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacing=12;fontFamily=Helvetica;fontSize=12;fillColor={colors[group]};strokeColor=#496177;',vertex='1',parent='1'); E.SubElement(cell,'mxGeometry',x=str(x),y=str(y),width='420',height=str(h),attrib={'as':'geometry'})
    # Relaciones dentro de cada página; referencias externas quedan identificadas por nombre en una nota.
    for t in ts:
        outside=[]
        for c in t['columns']:
            ref=re.search(r'REFERENCES (\w+)\(',c['flags'])
            if not ref: continue
            par=ref[1]
            if par in placements and par!=t['name']:
                edge=E.SubElement(root,'mxCell',id=t['name']+'_'+c['name'],value=c['name'],style='edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=ERone;startArrow=ERmany;fontSize=10;strokeColor=#637991;',edge='1',source=t['name'],target=par,parent='1'); E.SubElement(edge,'mxGeometry',relative='1',attrib={'as':'geometry'})
            else: outside.append(c['name']+' → '+par)
        if outside:
            x,y,h=placements[t['name']]; n=E.SubElement(root,'mxCell',id=t['name']+'_refs',value=html.escape('Referencias: '+ '; '.join(outside)),style='text;html=1;whiteSpace=wrap;align=left;fontSize=10;fontColor=#52647a;',vertex='1',parent='1'); E.SubElement(n,'mxGeometry',x=str(x),y=str(y+h+6),width='420',height='64',attrib={'as':'geometry'})
E.indent(mx)
(P/'MODELO_V3.drawio').write_text(E.tostring(mx,encoding='unicode'))

# Resumen conceptual visual: cada banda expresa una relación de negocio explícita.
lanes=[
 ('Acceso global',[('USUARIO','Identidad única'),('ADMINISTRADOR','MFA · alcance global')],['1 : 0..1']),
 ('Propiedad',[('USUARIO','Dueño principal'),('CUENTA CLIENTE','Cupo de predios'),('PREDIO','Contexto de datos')],['1 : 0..1','1 : 0..N']),
 ('Colaboración',[('USUARIO','Trabajador / veterinario'),('MEMBRESÍA','Rol · vigencia'),('PREDIO','Acceso autorizado')],['1 : 0..N','0..N : 1']),
 ('Historia animal',[('ANIMAL','DIIO único'),('PERMANENCIA','Intervalo sin solapamiento'),('PREDIO','Historia de ubicación')],['1 : 0..N','0..N : 1']),
 ('Monitoreo',[('ANIMAL','Asignación histórica'),('COLLAR','Uno activo por animal'),('LECTURA','Captura y calidad'),('RECEPCIÓN','Gateway · RSSI / SNR')],['N : M histórica','1 : 0..N','1 : 0..N']),
 ('Pastoreo',[('SECTOR','Uso del terreno'),('GEOCERCA','Geometría versionada'),('ASIGNACIÓN','Intervalo de pastoreo'),('ANIMAL','Una zona activa')],['1 : 0..N','1 : 0..N','0..N : 1']),
 ('Cambios',[('SOLICITUD','Pendiente ≠ efectiva'),('DECISIÓN','Revisión o directa'),('APLICACIÓN','Transacción única')],['1 : 0..1','1 : 0..1']),
 ('Salud',[('PERMANENCIA','Animal y predio'),('EVENTO SANITARIO','Corrección sin borrado'),('TRATAMIENTO','Dosis y resguardo')],['1 : 0..N','1 : 0..N'])]
W,H=1480,1410
s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">','<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9" fill="none" stroke="#718299" stroke-width="1.4"/></marker></defs>',f'<rect width="{W}" height="{H}" fill="#f5f8fb"/>','<text x="46" y="56" font-family="sans-serif" font-size="30" font-weight="700" fill="#142b40">GeoCattle · Modelo conceptual V3</text>','<text x="46" y="88" font-family="sans-serif" font-size="16" fill="#52677c">Cuatro perfiles · acceso por predio · cambios trazables · resumen de relaciones principales</text>']
for i,(label,nodes,links) in enumerate(lanes):
    y=125+i*145
    s += [f'<rect x="30" y="{y}" width="1420" height="130" rx="16" fill="white" stroke="#dce5ee"/>',f'<text x="50" y="{y+27}" font-family="sans-serif" font-size="15" font-weight="700" fill="#496278">{label}</text>']
    for j,(title,sub) in enumerate(nodes):
        x=210+j*305
        s += [f'<rect x="{x}" y="{y+38}" width="236" height="72" rx="10" fill="{list(colors.values())[i%len(colors)]}" stroke="#bbcbd7"/>',f'<text x="{x+15}" y="{y+66}" font-family="sans-serif" font-size="16" font-weight="700" fill="#18354b">{html.escape(title)}</text>',f'<text x="{x+15}" y="{y+91}" font-family="sans-serif" font-size="12" fill="#435a70">{html.escape(sub)}</text>']
        if j<len(links):
            s += [f'<path d="M{x+236} {y+76} H{x+305}" stroke="#718299" fill="none" marker-end="url(#arrow)"/>',f'<text x="{x+270}" y="{y+51}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#435a70">{html.escape(links[j])}</text>']
s += ['<text x="46" y="1325" font-family="sans-serif" font-size="15" fill="#29465d">Trabajador: aprobación por defecto; confianza por acción. Veterinario: cambios directos en fichas.</text>','<text x="46" y="1355" font-family="sans-serif" font-size="14" fill="#52677c">Una decisión rechazada no tiene aplicación. La aprobación no sustituye MFA. Diagrama completo en archivo Mermaid.</text>','<text x="46" y="1384" font-family="sans-serif" font-size="13" fill="#52677c">Propuesta de diseño · 20 octubre 2026 · No modifica la base actual</text>','</svg>']
svg='\n'.join(s); (P/'MODELO_CONCEPTUAL_V3.svg').write_text(svg)
body=['<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GeoCattle · Modelos V3</title><style>body{font:16px system-ui;background:#f5f8fb;color:#18354b;margin:0}main{max-width:1440px;margin:auto;padding:28px}h1{margin-bottom:8px}nav{display:flex;gap:20px;flex-wrap:wrap;padding:14px 0}a{color:#176b72}svg{width:100%;height:auto}details{margin:10px 0;background:white;border:1px solid #dce5ee;border-radius:8px;padding:12px}summary{cursor:pointer;font-weight:650}table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:8px;border-bottom:1px solid #e7edf2;overflow-wrap:anywhere}section{margin:34px 0}code{font-size:13px}.badge{padding:5px 10px;background:#e0f2ed;border-radius:8px}p{line-height:1.6}.scroll{overflow:auto}</style><main>', '<h1>GeoCattle · Especificación V3</h1><p>Administrador global, dueño multipredio, trabajador con aprobación y veterinario con cambios directos.</p><p><span class="badge">Propuesta · 48 entidades · 29 casos · 44 RF · 22 RNF</span></p><nav><a href="README.md">Documentación</a><a href="MODELO_FISICO_V3.sql">SQL físico</a><a href="MODELO_V3.drawio">Diagrama editable</a><a href="#diccionario">Explorar entidades</a></nav>',svg,'<section id="diccionario"><h2>Entidades por dominio</h2><p>El SQL incluye las claves compuestas y restricciones completas. Este visor no requiere conexión a Internet.</p>']
for g in dict.fromkeys(t['group'] for t in T):
    body.append('<h3>'+html.escape(g)+'</h3>')
    for t in [t for t in T if t['group']==g]:
        body.append('<details><summary>'+t['name']+'</summary><p>'+html.escape(t['description'])+'</p><div class="scroll"><table><tr><th>Atributo</th><th>Tipo</th><th>Restricciones</th></tr>')
        for c in t['columns']: body.append('<tr><td><code>'+c['name']+'</code></td><td>'+html.escape(c['type'])+'</td><td>'+html.escape(c['flags'] or 'Opcional')+'</td></tr>')
        body.append('</table></div></details>')
body.append('</section><p>Base actual sin cambios. El SQL se validó en un contenedor temporal independiente; consultar el reporte de validación.</p></main></html>')
(P/'RESUMEN_VISUAL.html').write_text('\n'.join(body))
print('Generados SVG conceptual, visor HTML local y Draw.io por dominio.')
