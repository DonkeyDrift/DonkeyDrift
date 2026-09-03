import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Info,
  Loader2,
  ScanLine,
  XCircle,
} from 'lucide-react';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import {
  createLogStream,
  getJobStatus,
  installMyPc,
  probeMyPc,
  type MyPcProbeResult,
} from '../../services/api';
import { useTranslation } from '@/i18n';

interface MyPcProbePanelProps {
  host: string;
  user: string;
  password: string;
  remoteDirBase: string;
  pythonPath: string;
  /** SSH 私钥路径（可选，与表单 keyPath 一致；留空时后端回退默认密钥/密码认证） */
  keyPath?: string;
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
  keyPath,
  onApplyPythonPath,
}) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<MyPcProbeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 一键安装训练依赖（pip install "donkeydrifter[pc]"）状态
  const [installing, setInstalling] = useState(false);
  const [installLogs, setInstallLogs] = useState<string[]>([]);
  const [installStatus, setInstallStatus] = useState<'idle' | 'completed' | 'failed'>('idle');
  const [installError, setInstallError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // 卸载时关闭安装日志 SSE 连接
  useEffect(() => () => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

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
        key_path: keyPath || undefined,
      });
      setResult(data);
    } catch (e) {
      setError(t('trainer.myPcProbeFailed', {
        message: e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setLoading(false);
    }
  }, [host, user, password, remoteDirBase, pythonPath, keyPath, t]);

  const canApplyPython =
    !!result?.python_path && result.python_path !== pythonPath;

  // 探测到的 python 路径优先（探测已验证可用），否则回退到表单填写值
  const effectivePython = result?.python_path || pythonPath;
  // 探测完成且拿到 python 路径即可安装：缺 donkeycar 时提示安装，
  // 环境已就绪时也允许用户主动重装/升级依赖；安装中/结束后保持区块可见
  const showInstallSection =
    installing || installStatus !== 'idle' || (!!effectivePython && !loading);
  const missingDonkeycar = !!result?.checks.some(
    (c) => c.name === 'donkeycar' && c.status === 'fail',
  );

  const startInstall = useCallback(async () => {
    if (!effectivePython) return;
    esRef.current?.close();
    esRef.current = null;
    setInstalling(true);
    setInstallLogs([]);
    setInstallStatus('idle');
    setInstallError(null);
    try {
      const { job_id } = await installMyPc({
        host,
        user,
        password,
        python_path: effectivePython,
        key_path: keyPath || undefined,
      });
      const es = createLogStream(job_id);
      esRef.current = es;
      es.onmessage = (ev: MessageEvent<string>) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'log' && msg.line) {
            setInstallLogs((logs) => [...logs.slice(-49), String(msg.line)]);
          } else if (msg.type === 'status') {
            if (msg.status === 'completed') {
              setInstallStatus('completed');
              setInstalling(false);
              es.close();
            } else if (msg.status === 'failed' || msg.status === 'stopped') {
              setInstallStatus('failed');
              setInstalling(false);
              es.close();
            }
          }
        } catch {
          // 忽略无法解析的心跳/异常帧
        }
      };
      es.onerror = () => {
        // 连接中断时退回一次状态查询，避免卡在"安装中"
        es.close();
        if (esRef.current === es) {
          esRef.current = null;
        }
        getJobStatus(job_id)
          .then((status) => {
            if (status.status === 'completed') {
              setInstallStatus('completed');
            } else if (status.status === 'failed' || status.status === 'stopped') {
              setInstallStatus('failed');
              if (status.error) {
                setInstallError(t('trainer.myPcInstallFailed', { message: status.error }));
              }
            } else {
              return; // 任务仍在跑，仅丢失日志流
            }
            setInstalling(false);
          })
          .catch(() => {/* 状态查询也失败时保持现状 */ });
      };
    } catch (e) {
      setInstallError(t('trainer.myPcInstallFailed', {
        message: e instanceof Error ? e.message : String(e),
      }));
      setInstallStatus('failed');
      setInstalling(false);
    }
  }, [host, user, password, effectivePython, keyPath, t]);

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

          {showInstallSection && (
            <div className="border-t border-zinc-800 pt-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm text-zinc-300">
                  {missingDonkeycar
                    ? t('trainer.myPcInstallRerunProbe')
                    : t('trainer.myPcInstall')}
                </span>
                {!installing && (
                  <button
                    onClick={startInstall}
                    data-testid="mypc-install-button"
                    className="px-3 py-1.5 rounded-md text-sm font-medium transition-colors inline-flex items-center gap-1.5 bg-cyan-600 hover:bg-cyan-700 text-white shrink-0"
                  >
                    <Download className="w-4 h-4" />
                    {t('trainer.myPcInstall')}
                  </button>
                )}
              </div>

              {installing && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm text-cyan-400" data-testid="mypc-install-running">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t('trainer.myPcInstallRunning')}
                  </div>
                  {installLogs.length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-1">
                        {t('trainer.myPcInstallLogTitle')}
                      </div>
                      <pre className="text-xs text-zinc-400 bg-zinc-950 border border-zinc-800 rounded p-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-all" data-testid="mypc-install-log">
                        {installLogs.join('\n')}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {!installing && installStatus === 'completed' && (
                <div className="flex items-center gap-2 text-sm text-green-400" data-testid="mypc-install-done">
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                  {t('trainer.myPcInstallDone')}
                </div>
              )}

              {!installing && installStatus === 'failed' && (
                <div className="text-sm text-red-400 bg-red-950/50 border border-red-900 rounded p-3" data-testid="mypc-install-error">
                  {installError || t('trainer.myPcInstallFailed', { message: '' })}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
