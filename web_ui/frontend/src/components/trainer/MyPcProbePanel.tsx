import React, { useCallback, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  ScanLine,
  XCircle,
} from 'lucide-react';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { probeMyPc, type MyPcProbeResult } from '../../services/api';
import { useTranslation } from '@/i18n';

interface MyPcProbePanelProps {
  host: string;
  user: string;
  password: string;
  remoteDirBase: string;
  pythonPath: string;
  onApplyPythonPath: (path: string) => void;
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  ok: <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />,
  warn: <AlertTriangle className="w-4 h-4 text-yellow-400 shrink-0" />,
  fail: <XCircle className="w-4 h-4 text-red-400 shrink-0" />,
  info: <Info className="w-4 h-4 text-cyan-400 shrink-0" />,
};

export const MyPcProbePanel: React.FC<MyPcProbePanelProps> = ({
  host,
  user,
  password,
  remoteDirBase,
  pythonPath,
  onApplyPythonPath,
}) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<MyPcProbeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runProbe = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await probeMyPc({
        host,
        user,
        password,
        remote_dir_base: remoteDirBase,
        python_path: pythonPath,
      });
      setResult(data);
    } catch (e) {
      setError(t('trainer.myPcProbeFailed', {
        message: e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setLoading(false);
    }
  }, [host, user, password, remoteDirBase, pythonPath, t]);

  const canApplyPython =
    !!result?.python_path && result.python_path !== pythonPath;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <SectionCardTitle
            icon={<ScanLine className="w-5 h-5" />}
            title={t('trainer.myPcProbe')}
            subtitle={t('trainer.myPcProbeSubtitle')}
          />
          <p className="text-xs text-zinc-500 mt-1">{t('trainer.myPcProbeHint')}</p>
        </div>
        <button
          onClick={runProbe}
          disabled={loading || !host || !user}
          className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors inline-flex items-center gap-1.5 ${
            loading || !host || !user
              ? 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
              : 'bg-cyan-600 hover:bg-cyan-700 text-white'
          }`}
        >
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <ScanLine className="w-4 h-4" />
          )}
          {loading ? t('trainer.myPcProbeRunning') : t('trainer.myPcProbeRun')}
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-950/50 border border-red-900 rounded p-3">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            {result.ok ? (
              <CheckCircle2 className="w-5 h-5 text-green-400" />
            ) : (
              <XCircle className="w-5 h-5 text-red-400" />
            )}
            <span className={result.ok ? 'text-green-400' : 'text-red-400'}>
              {result.ok ? t('trainer.myPcProbeReady') : t('trainer.myPcProbeNotReady')}
            </span>
          </div>

          {canApplyPython && (
            <div className="flex items-center justify-between gap-2 bg-zinc-950 rounded px-3 py-2">
              <span className="text-xs text-zinc-400 break-all">
                {t('trainer.myPcProbeDetectedPython', { path: result.python_path })}
              </span>
              <button
                onClick={() => onApplyPythonPath(result.python_path)}
                className="px-2 py-1 rounded text-xs font-medium bg-zinc-800 hover:bg-zinc-700 text-zinc-200 shrink-0"
              >
                {t('trainer.myPcProbeApplyPython')}
              </button>
            </div>
          )}

          <ul className="space-y-2">
            {result.checks.map((check) => (
              <li key={check.name} className="flex items-start gap-2 text-sm">
                {STATUS_ICON[check.status] ?? STATUS_ICON.info}
                <div className="min-w-0">
                  <div className="text-zinc-200">{check.message}</div>
                  {check.hint && (
                    <div className="text-xs text-zinc-500 mt-0.5">{check.hint}</div>
                  )}
                </div>
              </li>
            ))}
          </ul>

          {result.suggestions.length > 0 && (
            <div className="border-t border-zinc-800 pt-3">
              <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
                {t('trainer.myPcProbeSuggestions')}
              </div>
              <ul className="space-y-1">
                {result.suggestions.map((s, idx) => (
                  <li key={idx} className="text-sm text-zinc-300 flex items-start gap-2">
                    <span className="text-cyan-400">•</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
