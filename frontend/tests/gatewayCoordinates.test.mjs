import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/gatewayCoordinates.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {gatewayPoint,hasGatewayPosition}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
test('gateway fields preserve latitude/longitude and accept zero and WGS84 limits',()=>{
  assert.deepEqual(gatewayPoint('-38.745','-72.645'),[-38.745,-72.645]);
  assert.deepEqual(gatewayPoint('0','0'),[0,0]);
  assert.deepEqual(gatewayPoint('-90','180'),[-90,180]);
  assert.equal(hasGatewayPosition({latitude:0,longitude:0}),true);
});
test('blank, partial, non-finite and out of range coordinates cannot become a marker',()=>{
  for(const pair of [['','0'],['0',''],[' ',' '],['NaN','0'],['Infinity','0'],['91','0'],['0','181']])assert.equal(gatewayPoint(...pair),null);
  for(const gateway of [{},{latitude:null,longitude:0},{latitude:0,longitude:undefined},{latitude:Infinity,longitude:0},{latitude:-91,longitude:0},{latitude:0,longitude:-181}])assert.equal(hasGatewayPosition(gateway),false);
});
test('map movement and field editing serialize the same single location',()=>{
  const dragged=[-39.123456789,-73.987654321];
  assert.deepEqual(gatewayPoint(String(dragged[0]),String(dragged[1])),dragged);
  assert.deepEqual(gatewayPoint('-39.12',String(dragged[1])),[-39.12,dragged[1]]);
});
