import type { CattleEvent } from './types';
import { age, date } from './api';
import { CattleMap } from './Map';
import { Detail } from './ui';

export function EventLocation({ event }: { event: CattleEvent }) {
  if (event.type !== 'communication_timeout') return null;
  const location=event.last_known_position, point=location?.telemetry;
  const valid=point?.gnss_valid && point.latitude!=null && point.longitude!=null && Number.isFinite(point.latitude) && Number.isFinite(point.longitude);
  return <section className="event-location"><h3 className="section-heading">Ubicación al detectar la pérdida de comunicación</h3>
    <p className="notice notice-warning">Última ubicación conocida; no representa la ubicación actual.</p>
    {valid && location ? <><dl className="details-grid"><Detail label="Animal / DIIO" value={`${event.animal_name || 'Sin nombre'} · ${event.diio || 'Sin DIIO'}`}/><Detail label="Collar" value={`${location.hardware_id} · ${event.device_name || event.device_id}`}/><Detail label="Coordenadas WGS84" value={`${point.latitude!.toFixed(6)}, ${point.longitude!.toFixed(6)}`}/><Detail label="Posición capturada" value={date(point.observed_at)}/><Detail label="Lectura recibida" value={date(point.received_at)}/><Detail label="Antigüedad al detectar la alerta" value={age(location.age_at_detection_seconds)}/></dl>
      <CattleMap height="small" collars={[{ hardware_id:location.hardware_id,latitude:point.latitude!,longitude:point.longitude!,observed_at:point.observed_at,stale:true }]} />
      <p className="sensor-caption">Referencia histórica conservada: {point.id}. Solo incluye lecturas de la asociación collar-animal vigente al detectar el evento.</p>
    </> : <p className="form-intro">Sin posición GPS válida recibida antes de la detección para esta asociación de collar y animal.</p>}
  </section>;
}
