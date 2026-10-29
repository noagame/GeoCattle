import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/geofenceDraft.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const { draftReducer, vertex, position, polygonFromVertices, importVertices }=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const square=()=>[vertex(0,0),vertex(0,1),vertex(1,1),vertex(1,0)];
test('mixed additions, stable identity, edit, delete and undo roundtrip',()=>{
  let state={vertices:[],selected:null,history:[]};
  for(const v of square())state=draftReducer(state,{type:'replace',vertices:[...state.vertices,v]});
  const original=state.vertices, id=original[1].id;
  state=draftReducer(state,{type:'select',id});
  state=draftReducer(state,{type:'edit',id,latitude:'.1',longitude:'1'});
  assert.equal(state.vertices[1].id,id);assert.equal(position(state.vertices[1])[0],.1);
  assert.deepEqual(state.vertices[0],original[0]);
  state=draftReducer(state,{type:'undo'});assert.deepEqual(state.vertices,original);
  state=draftReducer(state,{type:'replace',vertices:state.vertices.filter(v=>v.id!==id)});
  assert.equal(state.vertices.length,3);assert.equal(state.selected,null);
  assert.throws(()=>polygonFromVertices(state.vertices));
  state=draftReducer(state,{type:'undo'});assert.deepEqual(state.vertices,original);
  const polygon=polygonFromVertices(original);assert.deepEqual(polygonFromVertices(importVertices(polygon)),polygon);
});
test('a complete drag is one undo operation and preserves other vertices',()=>{
  const vertices=square();let state={vertices,selected:vertices[0].id,history:[]};
  state=draftReducer(state,{type:'checkpoint'});
  for(const lat of ['.01','.02','.03'])state=draftReducer(state,{type:'edit',id:vertices[0].id,latitude:lat,longitude:'0',record:false});
  assert.equal(state.history.length,1);assert.deepEqual(state.vertices.slice(1),vertices.slice(1));
  assert.deepEqual(draftReducer(state,{type:'undo'}).vertices,vertices);
});
test('empty, out of range, repeated, crossing and zero-area points rejected',()=>{
  assert.equal(position({...vertex(0,0),latitude:''}),null);
  assert.equal(position(vertex(91,0)),null);assert.equal(position(vertex(0,181)),null);
  assert.throws(()=>polygonFromVertices([...square(),vertex(0,0)]));
  assert.throws(()=>polygonFromVertices([vertex(0,0),vertex(1,1),vertex(1,0),vertex(0,1)]));
  assert.throws(()=>polygonFromVertices([vertex(0,0),vertex(1,0),vertex(2,0),vertex(3,0)]));
});
test('import uses longitude/latitude and rejects open rings, holes and invalid data',()=>{
  const geometry={type:'Polygon',coordinates:[[[-72,-39],[-71,-39],[-71,-38],[-72,-38],[-72,-39]]]};
  assert.deepEqual(position(importVertices(geometry)[0]),[-39,-72]);
  assert.throws(()=>importVertices({...geometry,coordinates:[geometry.coordinates[0].slice(0,-1)]}));
  assert.throws(()=>importVertices({...geometry,coordinates:[...geometry.coordinates,...geometry.coordinates]}));
  assert.throws(()=>importVertices({type:'Polygon',coordinates:[[['bad',1]]]}));
});
