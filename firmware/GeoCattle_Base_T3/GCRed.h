#pragma once
// GeoCattle: prototipo de red para una base T3 y hasta dos gateways B2B.
// RadioLib 7.8.1 / ArduinoJson 7.x. Memoria RAM, sin garantia tras reinicio.
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <ArduinoJson.h>
#include <esp_system.h>
#include <ctype.h>
#include <math.h>
#include "GCTransport.h"

static_assert((GC_ROOT_T3 && GC_NODE_ID == 0) ||
              (!GC_ROOT_T3 && (GC_NODE_ID == 1 || GC_NODE_ID == 2)), "ID/rol incorrecto");
#if GC_ROOT_T3
SX1276 radio = new Module(18, 26, 23, RADIOLIB_NC, SPI,
                         SPISettings(2000000, MSBFIRST, SPI_MODE0));
#else
SX1262 radio = new Module(41, 39, 42, 40, SPI,
                         SPISettings(2000000, MSBFIRST, SPI_MODE0));
#endif
constexpr uint8_t NODE = GC_NODE_ID;
constexpr uint32_t ROOT_LEASE = 20000, NEIGHBOR_LEASE = 12000;
constexpr uint32_t MAX_DELAY = 1800000;  // 30 minutos; caducidad declarada.
constexpr size_t QUEUE_SIZE = 64, CACHE_SIZE = 128, MAX_RECORDS = 4;
constexpr size_t RECORD_HEADER = 13;
constexpr uint8_t NO_PARENT = 255;
struct Key { char collar[17] = {}; char session[17] = {}; uint32_t q = 0; };
struct Record {
  Key key; uint8_t raw[255] = {}; uint16_t len = 0;
  uint32_t digest = 0, age = 0, marked = 0;
  uint8_t origin = 0, path = 0, hops = 0;
  int16_t rssi10 = 0, snr10 = 0;
};
#if GC_ROOT_T3
#include "GCCloud.h"
#endif
struct Cached { Key key; uint32_t digest=0; uint16_t len=0; bool used=false; };
struct Neighbor {
  bool valid=false; uint32_t root=0, sequence=0, heard=0;
  uint8_t rank=255, path=0; float rssi=-200;
};
Record queueRecords[QUEUE_SIZE]; size_t queueHead=0, queueCount=0;
Cached seen[CACHE_SIZE]; size_t nextSeen=0;
Neighbor neighbors[3]; uint32_t blockedUntil[3]={};
gc::Reassembly assembly;
uint8_t rxFrame[gc::MAX_RF], txFrame[gc::MAX_RF];
uint32_t bootId=0, rootBoot=0, rootSequence=0, rootReference=0;
bool haveRoot=false;
uint8_t parent=NO_PARENT, myRank=255, routePath=0;
uint32_t lastBeacon=0, lastState=0, nextTransmit=0, lastRxAttempt=0;
volatile bool rxReady=false, irqEnabled=false; bool listening=false;
uint32_t received=0, accepted=0, duplicates=0, drops=0, txErrors=0, nextBatch=0;
struct Pending {
  bool active=false, waiting=false; uint8_t target=255, part=0, parts=0, records=0;
  uint8_t data[gc::MAX_BATCH] = {}; uint16_t len=0;
  uint32_t number=0, checksum=0, prepared=0, sent=0, deadline=0;
  uint8_t rounds=0;
} pending;
struct UsbPending { bool active=false; uint8_t records=0; uint32_t number=0,sent=0; } usbPending;
#if GC_ROOT_T3
char usbCommand[gccloud::COMMAND_SIZE]={}; size_t usbCommandSize=0; bool usbCommandOverflow=false;
Cached cloudSeen[CACHE_SIZE]; size_t nextCloudSeen=0;
#endif


uint8_t bits(uint8_t value) { uint8_t n=0; for(;value;value>>=1) n+=value&1; return n; }
bool due(uint32_t now,uint32_t deadline) { return int32_t(now-deadline)>=0; }
uint32_t recordAge(const Record& r,uint32_t now) {
  uint32_t elapsed=now-r.marked;
  return elapsed>MAX_DELAY || r.age>MAX_DELAY-elapsed ? MAX_DELAY+1 : r.age+elapsed;
}
Record& at(size_t offset) { return queueRecords[(queueHead+offset)%QUEUE_SIZE]; }
void popRecords(size_t count) { queueHead=(queueHead+count)%QUEUE_SIZE; queueCount-=count; }
void purgeExpired(uint32_t now) {
  size_t kept=0, originalCount=queueCount;
  for(size_t i=0;i<originalCount;i++) {
    if(recordAge(at(i),now)>MAX_DELAY) { ++drops; continue; }
    if(kept!=i) at(kept)=at(i);
    ++kept;
  }
  queueCount=kept;
}
bool sameKey(const Key& a,const Key& b) {
  return a.q==b.q && strcmp(a.collar,b.collar)==0 && strcmp(a.session,b.session)==0;
}
// 0=nuevo; 1=aceptado anteriormente; -1=identidad con contenido distinto.
int cached(const Record& r) {
  // Una lectura todavia bajo custodia no depende de la cache circular.
  for(size_t i=0;i<queueCount;i++) {
    const auto& queued=at(i);
    if(sameKey(queued.key,r.key)) return queued.len==r.len && queued.digest==r.digest ? 1 : -1;
  }
  for(auto& c:seen) if(c.used && sameKey(c.key,r.key))
    return c.len==r.len && c.digest==r.digest ? 1 : -1;
  return 0;
}
void remember(const Record& r) {
  auto& c=seen[nextSeen]; c.key=r.key; c.digest=r.digest; c.len=r.len; c.used=true;
  nextSeen=(nextSeen+1)%CACHE_SIZE;
}
void enqueue(const Record& r) { at(queueCount)=r; ++queueCount; remember(r); ++accepted; }

bool parseIdentity(Record& r) {
  if(!r.len || r.len>255) return false;
  JsonDocument d;
  if(deserializeJson(d,static_cast<const uint8_t*>(r.raw),r.len)) return false;
  if(!d.is<JsonObject>() || !d["v"].is<int>() || d["v"].as<int>()!=5 ||
     !d["id"].is<const char*>() || !d["s"].is<const char*>() ||
     !d["q"].is<uint32_t>() || !d["u"].is<uint32_t>() || !d["p"].is<uint32_t>() ||
     !d["g"].is<JsonArray>() || d["g"].size()!=5 ||
     !d["a"].is<JsonArray>() || d["a"].size()!=3 ||
     !d["m"].is<JsonArray>() || d["m"].size()!=2 ||
     !d["b"].is<JsonArray>() || d["b"].size()!=5 ||
     !d["f"].is<int>() || !d["e"].is<int>() || !d.containsKey("t")) return false;
  uint32_t period=d["p"]; if(period<30000 || period>45000) return false;
  const char* id=d["id"]; const char* session=d["s"];
  size_t size=strlen(id); if(size<1 || size>16 || strlen(session)!=16) return false;
  for(size_t i=0;i<size;i++) {
    unsigned char c=id[i]; if(!isalnum(c) && c!='_' && c!='-') return false;
  }
  for(size_t i=0;i<16;i++) if(!isxdigit(static_cast<unsigned char>(session[i]))) return false;
  strlcpy(r.key.collar,id,sizeof(r.key.collar));
  strlcpy(r.key.session,session,sizeof(r.key.session)); r.key.q=d["q"];
  r.digest=gc::crc32(r.raw,r.len); return true;
}
void IRAM_ATTR onReceive() { if(irqEnabled) rxReady=true; }
void receiveAgain() {
  irqEnabled=false; rxReady=false; lastRxAttempt=millis();
  irqEnabled=true; int16_t result=radio.startReceive(); listening=result==RADIOLIB_ERR_NONE;
  if(!listening) { irqEnabled=false; ++txErrors; }
}
bool sendFrame(const gc::Header& h,const uint8_t* data,size_t len) {
  if(len+gc::HEADER_SIZE>gc::MAX_RF || !gc::encodeHeader(h,txFrame,sizeof(txFrame))) return false;
  if(len) memcpy(txFrame+gc::HEADER_SIZE,data,len);
  irqEnabled=false; rxReady=false; listening=false;
  int16_t result=radio.transmit(txFrame,gc::HEADER_SIZE+len);
  receiveAgain(); if(result!=RADIOLIB_ERR_NONE) ++txErrors;
  return result==RADIOLIB_ERR_NONE;
}
void resetRoutes(uint32_t epoch,uint32_t seq,uint32_t age,uint32_t now) {
  for(auto& n:neighbors) n.valid=false;
  haveRoot=true; rootBoot=epoch; rootSequence=seq; rootReference=now-age;
  parent=NO_PARENT; myRank=255; routePath=0;
}
void selectRoute(uint32_t now) {
#if !GC_ROOT_T3
  for(auto& until:blockedUntil) if(until && due(now,until)) until=0;
  uint8_t best=NO_PARENT;
  if(haveRoot && now-rootReference<ROOT_LEASE) {
    for(uint8_t i=0;i<3;i++) {
      const auto& n=neighbors[i];
      if(i==NODE || (blockedUntil[i] && !due(now,blockedUntil[i])) || !n.valid || n.root!=rootBoot || now-n.heard>=NEIGHBOR_LEASE ||
         n.rank>=2 || (n.path&(1U<<NODE)) || int32_t(rootSequence-n.sequence)>2) continue;
      if(best==NO_PARENT || n.rank<neighbors[best].rank ||
         (n.rank==neighbors[best].rank && n.rssi>neighbors[best].rssi+6)) best=i;
    }
    // Mantener padre si la alternativa de igual rango mejora menos de 6 dB.
    if(parent!=NO_PARENT && best!=NO_PARENT && parent!=best) {
      const auto& p=neighbors[parent];
      if((!blockedUntil[parent] || due(now,blockedUntil[parent])) && p.valid && p.root==rootBoot && now-p.heard<NEIGHBOR_LEASE &&
         int32_t(rootSequence-p.sequence)<=2 && !(p.path&(1U<<NODE)) &&
         p.rank==neighbors[best].rank && neighbors[best].rssi<=p.rssi+6) best=parent;
    }
  }
  parent=best;
  myRank=best==NO_PARENT?255:neighbors[best].rank+1;
  routePath=best==NO_PARENT?0:uint8_t(neighbors[best].path|(1U<<NODE));
#endif
}
void handleBeacon(const gc::Header& h,const uint8_t* data,size_t len,float rssi,uint32_t now) {
#if !GC_ROOT_T3
  if(h.src==NODE || len!=14 || h.total!=14 || h.parts!=1 || h.index ||
     gc::crc32(data,len)!=h.checksum) return;
  uint32_t epoch=gc::read32(data), seq=gc::read32(data+4), age=gc::read32(data+8);
  uint8_t rank=data[12], path=data[13];
  if(!epoch || age>=ROOT_LEASE || rank>=2 || (path&~6U) || (path&(1U<<NODE)) ||
     bits(path)!=rank || (h.src==0 ? (rank!=0 || path!=0 || h.boot!=epoch) :
                           (!(path&(1U<<h.src)) || rank==0))) return;
  if(!haveRoot || epoch!=rootBoot) {
    if(h.src!=0 && haveRoot && now-rootReference<ROOT_LEASE) return;
    resetRoutes(epoch,seq,age,now);
  } else {
    int32_t change=int32_t(seq-rootSequence);
    if(change<0) return;
    if(change>0) { rootSequence=seq; rootReference=now-age; }
    else if(age>now-rootReference) rootReference=now-age; // No rejuvenecer beacon repetido.
  }
  auto& n=neighbors[h.src]; n.valid=true; n.root=epoch; n.sequence=seq;
  n.heard=now; n.rank=rank; n.path=path; n.rssi=rssi;
  selectRoute(now);
#endif
}
void sendBeacon(uint32_t now) {
#if GC_ROOT_T3
  ++rootSequence; rootReference=now;
#else
  if(parent==NO_PARENT || !haveRoot || now-rootReference>=ROOT_LEASE) return;
#endif
  uint8_t data[14]; gc::write32(data,rootBoot); gc::write32(data+4,rootSequence);
  gc::write32(data+8,now-rootReference); data[12]=myRank; data[13]=routePath;
  gc::Header h{}; h.kind=gc::Beacon; h.src=NODE; h.dst=255; h.boot=bootId;
  h.number=rootSequence; h.parts=1; h.total=sizeof(data); h.checksum=gc::crc32(data,sizeof(data));
  sendFrame(h,data,sizeof(data));
}
void sendAck(const gc::Header& dataHeader,uint8_t status) {
  gc::Header h{}; h.kind=gc::Ack; h.src=NODE; h.dst=dataHeader.src;
  h.boot=dataHeader.boot; h.number=dataHeader.number; h.checksum=dataHeader.checksum; h.index=status;
  sendFrame(h,nullptr,0);
}
// Validar lote completo y reservar espacio ANTES de aceptar su custodia.
uint8_t acceptBatch(const uint8_t* bytes,size_t len,uint32_t elapsed,uint32_t now) {
  if(!len || bytes[0]<1 || bytes[0]>MAX_RECORDS || elapsed>MAX_DELAY) return 3;
  Record records[MAX_RECORDS]; bool fresh[MAX_RECORDS]={};
  uint8_t count=bytes[0], needed=0; size_t pos=1;
  for(uint8_t i=0;i<count;i++) {
    if(pos+RECORD_HEADER>len) return 3;
    auto& r=records[i]; r.len=gc::read16(bytes+pos); r.age=gc::read32(bytes+pos+2);
    r.origin=bytes[pos+6]; r.path=bytes[pos+7]; r.hops=bytes[pos+8];
    r.rssi10=int16_t(gc::read16(bytes+pos+9)); r.snr10=int16_t(gc::read16(bytes+pos+11));
    pos+=RECORD_HEADER;
    if(!r.len || r.len>255 || pos+r.len>len || r.age>MAX_DELAY-elapsed ||
       r.origin<1 || r.origin>2 || (r.path&~6U) || !(r.path&(1U<<r.origin)) ||
       r.hops!=bits(r.path) || r.hops<1 || r.hops>2 ||
       r.rssi10< -2000 || r.rssi10>200 || r.snr10< -1000 || r.snr10>1000) return 3;
#if !GC_ROOT_T3
    if((r.path&(1U<<NODE)) || r.hops>=2) return 2; // Antes de deduplicar o confirmar.
#endif
    memcpy(r.raw,bytes+pos,r.len); pos+=r.len;
    if(!parseIdentity(r)) return 3;
    r.age+=elapsed; r.marked=now;
#if !GC_ROOT_T3
    r.path|=1U<<NODE; ++r.hops;
#endif
    int state=cached(r); if(state<0) return 3;
    fresh[i]=state==0;
    for(uint8_t j=0;j<i;j++) if(sameKey(r.key,records[j].key)) {
      if(r.len!=records[j].len || r.digest!=records[j].digest) return 3;
      fresh[i]=false;
    }
    if(fresh[i]) ++needed;
  }
  if(pos!=len) return 3;
#if GC_ROOT_T3
  // The cloud copy does not wait for USB capacity or a PC ACK. The existing
  // LoRa ACK and USB queue still preserve the local custody contract.
  for(uint8_t i=0;i<count;i++) {
    if(!fresh[i] || !gccloud::enabled) continue;
    const auto& record=records[i];
    bool alreadyQueued=false;
    for(const auto& entry : cloudSeen)
      if(entry.used && sameKey(entry.key,record.key)) { alreadyQueued=true; break; }
    if(!alreadyQueued && gccloud::offer(record)) {
      cloudSeen[nextCloudSeen]={record.key,record.digest,record.len,true};
      nextCloudSeen=(nextCloudSeen+1)%CACHE_SIZE;
    }
  }
#endif
  if(needed>QUEUE_SIZE-queueCount) return 1;
  for(uint8_t i=0;i<count;i++) { if(fresh[i]) enqueue(records[i]); else ++duplicates; }
  return 0;
}
void receiveRaw(const uint8_t* data,size_t len,float rssi,float snr,uint32_t now) {
  Record r; if(len>255 || !len || !isfinite(rssi) || !isfinite(snr)) { ++drops; return; }
  r.len=len; memcpy(r.raw,data,len); if(!parseIdentity(r)) { ++drops; return; }
  int state=cached(r); if(state>0) { ++duplicates; return; }
  if(state<0 || queueCount==QUEUE_SIZE) { ++drops; return; }
  r.marked=now; r.origin=NODE; r.rssi10=int16_t(lroundf(rssi*10)); r.snr10=int16_t(lroundf(snr*10));
#if !GC_ROOT_T3
  r.path=1U<<NODE; r.hops=1;
#endif
  enqueue(r);
}
void handleFrame() {
  irqEnabled=false; rxReady=false; listening=false;
  int16_t result=radio.standby();
  if(result!=RADIOLIB_ERR_NONE) { ++drops; receiveAgain(); return; }
  size_t len=radio.getPacketLength();
  if(!len || len>sizeof(rxFrame)) { ++drops; receiveAgain(); return; }
  result=radio.readData(rxFrame,len);
  float rssi=radio.getRSSI(), snr=radio.getSNR();
  receiveAgain();
  if(result!=RADIOLIB_ERR_NONE) { ++drops; return; }
  ++received; uint32_t now=millis();
  if(rxFrame[0]=='{') { receiveRaw(rxFrame,len,rssi,snr,now); return; }
  gc::Header h{}; if(!gc::decodeHeader(rxFrame,len,h) || h.src==NODE) return;
  const uint8_t* data=rxFrame+gc::HEADER_SIZE; size_t size=len-gc::HEADER_SIZE;
  if(h.kind==gc::Beacon) { handleBeacon(h,data,size,rssi,now); return; }
  if(h.dst!=NODE) return;
  if(h.kind==gc::Ack) {
    if(size!=0) return;
    if(!pending.active || h.src!=pending.target || h.boot!=bootId ||
       h.number!=pending.number || h.checksum!=pending.checksum) return;
    if(h.index==0) { popRecords(pending.records); pending.active=false; }
    else {
      if(h.index==2 && h.src<3) { neighbors[h.src].valid=false; blockedUntil[h.src]=now+10000; selectRoute(now); }
      pending.active=false; nextTransmit=now+3000+esp_random()%3000;
    }
    return;
  }
  if(h.kind!=gc::Data) return;
  auto assembled=assembly.ingest(h,data,size,now);
  if(assembled==gc::ReassemblyResult::Invalid) { ++drops; return; }
  if(assembled!=gc::ReassemblyResult::Complete) return;
  uint8_t status=acceptBatch(assembly.completedData(),assembly.completedSize(),assembly.completedElapsed(),now);
  assembly.clearCompleted();
  // ACK significa lote validado y aceptado en RAM, no commit de PostgreSQL.
  delay(5+esp_random()%20); sendAck(h,status);
}
void makeBatch(uint32_t now) {
  if(!queueCount || parent==NO_PARENT || !due(now,nextTransmit)) return;
  // No devolver a un gateway una lectura cuyo camino ya lo contiene.
  // Mover solo lecturas encaminables al frente, manteniendo las otras en cola.
  size_t selected=0;
  for(size_t i=0;i<queueCount && selected<MAX_RECORDS;i++) {
    const auto& candidate=at(i);
    if(parent!=0 && ((candidate.path&(1U<<parent)) || candidate.hops>=2)) continue;
    Record chosen=candidate;
    for(size_t j=i;j>selected;j--) at(j)=at(j-1);
    at(selected)=chosen; ++selected;
  }
  if(!selected || (selected<MAX_RECORDS && now-at(0).marked<2000)) return;
  pending=Pending{}; pending.active=true; pending.target=parent;
  pending.number=++nextBatch; pending.prepared=now; pending.len=1;
  for(size_t i=0;i<selected;i++) {
    const auto& r=at(i); size_t required=RECORD_HEADER+r.len;
    if(pending.len+required>gc::MAX_BATCH) break;
    uint8_t* out=pending.data+pending.len;
    gc::write16(out,r.len); gc::write32(out+2,recordAge(r,now));
    out[6]=r.origin; out[7]=r.path; out[8]=r.hops;
    gc::write16(out+9,uint16_t(r.rssi10)); gc::write16(out+11,uint16_t(r.snr10));
    memcpy(out+RECORD_HEADER,r.raw,r.len); pending.len+=required; ++pending.records;
  }
  pending.data[0]=pending.records; pending.parts=gc::partCount(pending.len);
  pending.checksum=gc::crc32(pending.data,pending.len); pending.deadline=now+50+esp_random()%250;
}
void sendPending(uint32_t now) {
  if(!pending.active) return;
  if(recordAge(at(0),now)>MAX_DELAY) { pending.active=false; return; }
  if(pending.waiting) {
    if(!due(now,pending.deadline)) return;
    if(++pending.rounds>=3 || parent!=pending.target || parent==NO_PARENT) {
      if(pending.rounds>=3 && pending.target<3) {
        blockedUntil[pending.target]=now+30000; selectRoute(now);
      }
      pending.active=false; nextTransmit=now+3000+esp_random()%5000; return;
    }
    pending.part=0; pending.waiting=false; pending.deadline=now+300+esp_random()%700; return;
  }
  if(!due(now,pending.deadline)) return;
  gc::Header h{}; h.kind=gc::Data; h.src=NODE; h.dst=pending.target;
  h.boot=bootId; h.number=pending.number; h.index=pending.part; h.parts=pending.parts;
  h.total=pending.len; h.checksum=pending.checksum; h.elapsed_ms=now-pending.prepared;
  size_t size=gc::expectedDataPartLen(h.total,h.index);
  sendFrame(h,pending.data+size_t(h.index)*gc::CHUNK,size);
  if(++pending.part==pending.parts) { pending.waiting=true; pending.deadline=millis()+1800+esp_random()%1200; }
  else pending.deadline=millis()+40+esp_random()%100;
}
void readUsbAck() {
#if GC_ROOT_T3
  while(Serial.available()) {
    char c=char(Serial.read()); if(c=='\r') continue;
    if(c=='\n') {
      if(!usbCommandOverflow) {
        usbCommand[usbCommandSize]=0;
        char expected[64];
        snprintf(expected,sizeof(expected),"#GCACK,%08lX-%lu",(unsigned long)bootId,(unsigned long)usbPending.number);
        if(usbPending.active && strcmp(expected,usbCommand)==0) {
          popRecords(usbPending.records); usbPending.active=false;
        } else gccloud::submit(usbCommand);
      }
      usbCommandSize=0; usbCommandOverflow=false;
    } else if(usbCommandSize+1<sizeof(usbCommand) && !usbCommandOverflow) usbCommand[usbCommandSize++]=c;
    else usbCommandOverflow=true;
  }
  gccloud::printReply();
#endif
}
void flushUsb(uint32_t now) {
#if GC_ROOT_T3
  if(!queueCount || !Serial) return;
  if(!usbPending.active) {
    if(queueCount<MAX_RECORDS && now-at(0).marked<2000) return;
    usbPending.active=true; usbPending.records=min(queueCount,MAX_RECORDS);
    usbPending.number=++nextBatch; usbPending.sent=now-5000;
  }
  if(now-usbPending.sent<5000) return;
  usbPending.sent=now;
  Serial.printf("{\"gc_bus\":1,\"receiver\":\"BASE01\",\"batch\":\"%08lX-%lu\",\"readings\":[",
                (unsigned long)bootId,(unsigned long)usbPending.number);
  for(size_t i=0;i<usbPending.records;i++) {
    const auto& r=at(i); if(i) Serial.print(',');
    Serial.print("{\"packet\":"); Serial.write(r.raw,r.len);
    Serial.printf(",\"radio\":{\"rssi_dbm\":%.1f,\"snr_db\":%.1f},\"transport\":{\"delay_ms\":%lu,\"origin_gateway\":%u,\"hops\":%u,\"path\":%u}}",
                  r.rssi10/10.0,r.snr10/10.0,(unsigned long)recordAge(r,millis()),r.origin,r.hops,r.path);
  }
  Serial.println("]}");
  // Se retiran solo al leer #GCACK tras archivo SQLite duradero en el PC.
#endif
}
void critical(int16_t result,const char* text) {
  if(result==RADIOLIB_ERR_NONE) return;
  while(true) { Serial.printf("# ERROR %s: %d\n",text,result); delay(3000); }
}
void setup() {
  Serial.begin(115200); delay(600);
  bootId=esp_random(); if(!bootId) bootId=1;
#if GC_ROOT_T3
  SPI.begin(5,19,27,18);
#else
  SPI.begin(7,8,9,41); pinMode(38,OUTPUT); digitalWrite(38,LOW);
  radio.setRfSwitchPins(38,RADIOLIB_NC); radio.tcxoVoltage=1.8;
#endif
  ConfigLoRa_t config; config.frequency=915.5; config.bandwidth=125;
  config.spreadingFactor=7; config.codingRate=5; config.syncWord=0x12;
  config.power=10; config.preambleLength=8;
  critical(radio.begin(config),"iniciar radio");
#if GC_ROOT_T3
  critical(radio.setCRC(true),"CRC");
  haveRoot=true; rootBoot=bootId; rootReference=millis(); myRank=0;
#else
  critical(radio.setDio2AsRfSwitch(true),"RF switch"); critical(radio.setCRC(2),"CRC");
#endif
  critical(radio.explicitHeader(),"cabecera explicita"); critical(radio.invertIQ(false),"IQ");
  radio.setPacketReceivedAction(onReceive); receiveAgain();
#if GC_ROOT_T3
  gccloud::begin(bootId);
  enableLoopWDT();
#endif
  lastBeacon=millis()-5000+esp_random()%800;
  Serial.printf("# GEOCATTLE RED nodo=%u boot=%08lX cola=%u RAM; 915.5 MHz\n",NODE,(unsigned long)bootId,unsigned(QUEUE_SIZE));
}
void loop() {
  uint32_t now=millis();
  if(!listening && now-lastRxAttempt>=1000) receiveAgain();
  if(listening && rxReady) handleFrame();
  now=millis(); selectRoute(now);
#if GC_ROOT_T3
  readUsbAck();
  if(usbPending.active) {
    for(size_t i=0;i<usbPending.records;i++) if(recordAge(at(i),now)>MAX_DELAY) {
      usbPending.active=false; break;
    }
  }
#endif
  if(!pending.active && !usbPending.active) purgeExpired(now);
#if GC_ROOT_T3
  flushUsb(now);
#else
  if(!pending.active) makeBatch(now);
  sendPending(now);
#endif
  now=millis();
  if(!pending.active && now-lastBeacon>=5000+(uint32_t(NODE)*211)) {
    lastBeacon=now; sendBeacon(now);
  }
  if(now-lastState>=10000) {
    lastState=now;
    Serial.printf("# nodo=%u padre=%u saltos=%u cola=%u RX=%lu aceptadas=%lu duplicadas=%lu descartadas=%lu erroresTX=%lu\n",
      NODE,parent,myRank,unsigned(queueCount),(unsigned long)received,(unsigned long)accepted,
      (unsigned long)duplicates,(unsigned long)drops,(unsigned long)txErrors);
  }
  delay(1);
}
