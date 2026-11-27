import { useRef, useState, type ReactNode } from 'react';
import { ChevronDown, Download } from 'lucide-react';
import { downloadFile, message } from './api';
import { ErrorNotice } from './ui';

type ExportFormat = 'xlsx' | 'csv';
type ExportPath = (format: ExportFormat) => string;

export function ReportDownloads({ path, disabled, label = 'Descargar', group, additional, children }: {
  path: ExportPath;
  disabled: boolean;
  label?: string;
  group?: string;
  additional?: { label: string; path: ExportPath };
  children?: ReactNode;
}) {
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState('');
  const summary = useRef<HTMLElement>(null);
  const fileGroups = [{ label: group, path }, ...(additional ? [additional] : [])];

  async function download(format: ExportFormat, exportPath: ExportPath, key: string) {
    if (disabled || downloading) return;
    setDownloading(key);
    setError('');
    try {
      const url = exportPath(format);
      const downloadUrl = format === 'csv' ? `${url}${url.includes('?') ? '&' : '?'}delimiter=semicolon` : url;
      await downloadFile(downloadUrl, `geocattle-reporte.${format}`);
    } catch (error) {
      setError(message(error));
    } finally {
      setDownloading(null);
    }
  }

  const trigger = <><Download size={16} aria-hidden="true" />{label}<ChevronDown size={14} aria-hidden="true" /></>;
  if (disabled && !children && !error && !downloading) return <button type="button" className="button secondary small" disabled>{trigger}</button>;

  return <details className="report-download-menu" onKeyDown={event => {
    if (event.key !== 'Escape' || !event.currentTarget.open) return;
    event.preventDefault();
    event.currentTarget.open = false;
    summary.current?.focus();
  }}>
    <summary ref={summary} className="button secondary small">{trigger}</summary>
    <div className="report-download-options" aria-busy={downloading !== null}>
      {fileGroups.map(({ label: groupLabel, path: exportPath }) => <div className="report-downloads" key={groupLabel ?? ''}>
        {groupLabel && <strong>{groupLabel}</strong>}
        {(['xlsx', 'csv'] as const).map(format => {
          const name = format === 'xlsx' ? 'Excel' : 'CSV';
          const key = `${groupLabel ?? ''}:${format}`;
          return <button type="button" className="button secondary small" key={format} disabled={disabled}
            aria-disabled={downloading !== null} aria-label={`${name}${groupLabel ? ` · ${groupLabel}` : ''}`}
            title={format === 'csv' ? 'Punto y coma como separador y coma decimal' : undefined}
            onClick={() => download(format, exportPath, key)}>{downloading === key ? `Preparando ${name}…` : name}</button>;
        })}
      </div>)}
      {children && <div className="report-downloads">{children}</div>}
    </div>
    <ErrorNotice error={error} />
  </details>;
}
