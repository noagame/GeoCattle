import { useState, type ReactNode } from 'react';
import { Download } from 'lucide-react';
import { downloadFile, message } from './api';
import { ErrorNotice } from './ui';

type ExportFormat = 'xlsx' | 'csv';

export function ReportDownloads({ path, disabled, children }: {
  path: (format: ExportFormat) => string;
  disabled: boolean;
  children?: ReactNode;
}) {
  const [downloading, setDownloading] = useState<ExportFormat | null>(null);
  const [error, setError] = useState('');

  async function download(format: ExportFormat) {
    setDownloading(format);
    setError('');
    try {
      const url = path(format);
      const downloadUrl = format === 'csv' ? `${url}${url.includes('?') ? '&' : '?'}delimiter=semicolon` : url;
      await downloadFile(downloadUrl, `geocattle-reporte.${format}`);
    } catch (error) {
      setError(message(error));
    } finally {
      setDownloading(null);
    }
  }

  return <div>
    <div className="report-downloads" aria-busy={downloading !== null}>
      <button type="button" className="button primary small" onClick={() => download('xlsx')} disabled={disabled || downloading !== null}>
        <Download size={16} />{downloading === 'xlsx' ? 'Preparando Excel…' : 'Descargar Excel'}
      </button>
      <button type="button" className="button secondary small" title="Punto y coma como separador y coma decimal"
        onClick={() => download('csv')} disabled={disabled || downloading !== null}>
        <Download size={16} />{downloading === 'csv' ? 'Preparando CSV…' : 'Descargar CSV'}
      </button>
      {children}
    </div>
    <ErrorNotice error={error} />
  </div>;
}
