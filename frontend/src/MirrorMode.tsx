import { createContext, useContext, useEffect, useState } from 'react';
import { Info, Radio, WifiOff } from 'lucide-react';
import { date, formatApiDetail, useData } from './api';
import { Pagination } from './PagesAnimals';
import { Badge, Empty, ErrorNotice, Loading, PageTitle, Panel } from './ui';
import type { List, User } from './types';
import type { MirrorInfo, MirrorSubmission } from './v3types';
import { canWrite, fieldOnlyMessage, freshnessText, mirrorPollInterval, submissionLabels, type WriteFeature } from './mirror';

export const MirrorContext = createContext<{ info?: MirrorInfo; role?: User['role'] }>({});

export function useMirrorInfo(userId?: string) {
  return useData<MirrorInfo>(userId ? '/mirror/info' : null, mirrorPollInterval, userId);
}

export function useMirror() {
  const { info, role } = useContext(MirrorContext);
  return { replica: info?.mode === 'replica', canWrite: (feature: WriteFeature) => canWrite(info?.mode, role, feature) };
}

export function MirrorBanner({ info }: { info: MirrorInfo }) {
  const [now, setNow] = useState(Date.now);
  const online = info.mode === 'replica' && info.field_online && !!info.heartbeat_at;
  useEffect(() => {
    if (!online) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [online]);
  if (info.mode !== 'replica') return null;
  const Icon = online ? Radio : WifiOff;
  return <div className={`mirror-banner${online ? '' : ' mirror-banner-offline'}`}>
    <Icon size={17} aria-hidden="true" /><span>{freshnessText(info, now)}</span>
  </div>;
}

export function FieldOnlyNotice({ message = fieldOnlyMessage }: { message?: string }) {
  return <div className="notice"><Info size={17} aria-hidden="true" /><span>{message}</span></div>;
}

const submissionKinds: Record<MirrorSubmission['kind'], string> = {
  admin_order: 'Orden de administración', remote_change: 'Solicitud de cambio', draft_revision: 'Borrador',
  support_request: 'Solicitud de soporte',
};

export function MirrorSubmissions({ user, onOpenDrafts }: { user: User; onOpenDrafts: (farmId: string) => void }) {
  const [offset, setOffset] = useState(0);
  const limit = 25;
  const submissions = useData<List<MirrorSubmission>>(`/mirror/submissions?limit=${limit}&offset=${offset}`, mirrorPollInterval, user.id);
  return <>
    <PageTitle title="Mis envíos" description="Consulta el estado de tus solicitudes y órdenes al PC del campo." />
    <Panel>
      <ErrorNotice error={submissions.error} retry={submissions.reload} />
      {submissions.loading && !submissions.data ? <Loading /> : submissions.data?.items.length ? <div className="v3-changes">
        {submissions.data.items.map(item => {
          const reason = item.result?.reason || formatApiDetail(item.result?.detail);
          const farmId = item.farm_id;
          const farm = user.farms?.find(farm => farm.id === farmId);
          const canOpenDrafts = farmId && (user.farm_id === farmId || farm);
          return <article key={item.outbox_id}>
            <div className="v3-change-header mirror-item-heading">
              <div><strong>{submissionKinds[item.kind]}</strong><small>{date(item.created_at)}{farm && ` · ${farm.name}`}</small></div>
              <Badge status={item.status === 'applied' ? 'normal' : ['failed', 'rejected'].includes(item.status) ? 'critical' : 'warning'}>
                {submissionLabels[item.status]}
              </Badge>
            </div>
            {reason && <p className="form-intro">{reason}</p>}
            {item.status === 'conflict' && canOpenDrafts && <button className="text-button" onClick={() => onOpenDrafts(farmId)}>Ver mis borradores</button>}
          </article>;
        })}
      </div> : !submissions.error && <Empty title="Todavía no tienes envíos" />}
      {submissions.data && (offset > 0 || submissions.data.total > limit) &&
        <Pagination offset={offset} limit={limit} count={submissions.data.items.length} total={submissions.data.total} onChange={setOffset} />}
    </Panel>
  </>;
}
