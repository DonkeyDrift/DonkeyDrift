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
  type MyPcProbeResult,
} from '../../services/api';
import { useTranslation } from '@/i18n';

interface MyPcProbePanelProps {
  // 一键配置仍需连接凭据（探测状态由父组件受控传入，见下方四个 props）
  host: string;
  user: string;
  password: string;
  pythonPath: string;
  remoteDirBase: string;
  /** SSH 私钥路径（可选，与表单 keyPath 一致；留空时后端回退默认密钥/密码认证） */
  keyPath?: string;
  onApplyPythonPath: (path: string) => void;
  // 受控探测状态：父组件（TrainerPage）持有 useMyPcProbe，
  // 「开始训练」前的环境门禁与本面板共用同一份结果
  result: MyPcProbeResult | null;
  loading: boolean;
  error: string | null;
  onRunProbe: () => void;
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  ok: <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />,
  warn: <AlertTriangle className="w-4 h-4 text-yellow-400 shrink-0" />,
  fail: <XCircle className="w-4 h-4 text-red-400 shrink-0" />,
  info: <Info className="w-4 h-4 text-cyan-400 shrink-0" />,
};

const defaultInstallPath = (base: string, directory: string) =>
  `${base.replace(/[\\/]+$/, '')}/${directory}`;

export const MyPcProbePanel: React.FC<MyPcProbePanelProps> = ({
  host,
  user,
  password,
  pythonPath,
  remoteDirBase,
  keyPath,
  onApplyPythonPath,
  result,
  loading,
  error,
  onRunProbe,
}) => {
  const { t } = useTranslation();

  const [repoPath, setRepoPath] = useState(
    () => defaultInstallPath(remoteDirBase, 'DonkeyDrift'),
  );
  const [gymPath, setGymPath] = useState(
    () => defaultInstallPath(remoteDirBase, 'GymDonkeyCar'),
  );
  const [pathError, setPathError] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installLogs, setInstallLogs] = useState<string[]>([]);
  const [installStatus, setInstallStatus] = useState<'idle' | 'completed' | 'failed'>('idle');
  const [installError, setInstallError] = useState<string | null>(null);
  // SSE 断线后状态查询暂时失败时置位：仅提示重连，不视为任务失败
  const [reconnecting, setReconnecting] = useState(false);
  const installingRef = useRef(false);
  const mountedRef = useRef(true);
  const jobGenerationRef = useRef(0);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previousDefaultsRef = useRef({
    repo: defaultInstallPath(remoteDirBase, 'DonkeyDrift'),
    gym: defaultInstallPath(remoteDirBase, 'GymDonkeyCar'),
  });
  const repoInputRef = useRef<HTMLInputElement | null>(null);
  const gymInputRef = useRef<HTMLInputElement | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const previous = previousDefaultsRef.current;
    const next = {
      repo: defaultInstallPath(remoteDirBase, 'DonkeyDrift'),
      gym: defaultInstallPath(remoteDirBase, 'GymDonkeyCar'),
    };
    setRepoPath((current) => current === previous.repo ? next.repo : current);
    setGymPath((current) => current === previous.gym ? next.gym : current);
    previousDefaultsRef.current = next;
  }, [remoteDirBase]);

  // 卸载时使旧任务失效，并关闭安装日志 SSE 与状态轮询
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      installingRef.current = false;
      jobGenerationRef.current += 1;
      if (pollTimeoutRef.current !== null) {
        clearTimeout(pollTimeoutRef.current);
        pollTimeoutRef.current = null;
      }
      esRef.current?.close();
      esRef.current = null;
    };
  }, []);

  const canApplyPython =
    !!result?.python_path && result.python_path !== pythonPath;

  // 探测到的 python 路径优先（探测已验证可用），否则回退到表单填写值
  const effectivePython = result?.python_path || pythonPath;
  const sshReady = !!result?.checks.some((c) => c.name === 'ssh' && c.status === 'ok');
  const supportedPlatform = result?.platform === 'macos' || result?.platform === 'windows';
  const canInstall = !!result && sshReady && supportedPlatform && !loading;
  const showInstallSection = installing || installStatus !== 'idle' || canInstall;
  const missingDonkeycar = !!result?.checks.some(
    (c) => c.name === 'donkeycar' && c.status === 'fail',
  );

  const startInstall = useCallback(async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (installingRef.current || !canInstall) return;

    const trimmedRepoPath = repoPath.trim();
    const trimmedGymPath = gymPath.trim();
    if (!trimmedRepoPath || !trimmedGymPath) {
      setPathError(true);
      (trimmedRepoPath ? gymInputRef : repoInputRef).current?.focus();
      return;
    }

    const generation = ++jobGenerationRef.current;
    const isCurrent = () => mountedRef.current && jobGenerationRef.current === generation;
    let polling = false;
    const clearStatusPolling = () => {
      polling = false;
      if (pollTimeoutRef.current !== null) {
        clearTimeout(pollTimeoutRef.current);
        pollTimeoutRef.current = null;
      }
    };
    const finishInstall = (status: 'completed' | 'failed', message?: string) => {
      if (!isCurrent()) return;
      clearStatusPolling();
      installingRef.current = false;
      setInstallStatus(status);
      setReconnecting(false);
      setInstallError(message
        ? t('trainer.myPcInstallFailed', { message })
        : null);
      setInstalling(false);
    };

    clearStatusPolling();
    setPathError(false);
    installingRef.current = true;
    esRef.current?.close();
    esRef.current = null;
    setInstalling(true);
    setInstallLogs([]);
    setInstallStatus('idle');
    setInstallError(null);
    setReconnecting(false);
    try {
      const { job_id } = await installMyPc({
        host,
        user,
        password,
        repo_path: trimmedRepoPath,
        gym_path: trimmedGymPath,
        python_path: effectivePython || undefined,
        key_path: keyPath || undefined,
      });
      if (!isCurrent()) return;

      const es = createLogStream(job_id);
      if (!isCurrent()) {
        es.close();
        return;
      }
      esRef.current = es;
      es.onmessage = (ev: MessageEvent<string>) => {
        if (!isCurrent()) {
          es.close();
          return;
        }
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'log' && msg.line) {
            setInstallLogs((logs) => [...logs.slice(-49), String(msg.line)]);
          } else if (msg.type === 'status') {
            if (msg.status === 'completed') {
              es.close();
              finishInstall('completed');
            } else if (msg.status === 'failed' || msg.status === 'stopped') {
              es.close();
              finishInstall('failed', msg.error || undefined);
            }
          }
        } catch {
          // 忽略无法解析的心跳/异常帧
        }
      };
      es.onerror = () => {
        if (!isCurrent()) {
          es.close();
          return;
        }
        es.close();
        if (esRef.current === es) {
          esRef.current = null;
        }
        if (!installingRef.current || polling) return;

        // 连接中断后轮询任务状态；同一任务最多一个查询循环
        polling = true;
        const scheduleNextPoll = (fn: () => void) => {
          const timeout = setTimeout(() => {
            if (pollTimeoutRef.current === timeout) {
              pollTimeoutRef.current = null;
            }
            fn();
          }, 1000);
          pollTimeoutRef.current = timeout;
        };
        const pollStatus = async () => {
          if (!isCurrent() || !polling) return;
          try {
            const status = await getJobStatus(job_id);
            if (!isCurrent() || !polling) return;
            setReconnecting(false);
            if (status.status === 'completed') {
              finishInstall('completed');
            } else if (status.status === 'failed' || status.status === 'stopped') {
              finishInstall('failed', status.error || undefined);
            } else {
              scheduleNextPoll(() => {
                void pollStatus();
              });
            }
          } catch {
            if (!isCurrent() || !polling) return;
            // 单次查询失败不代表远程任务失败：保留状态未知提示并继续间隔查询
            setReconnecting(true);
            scheduleNextPoll(() => {
              void pollStatus();
            });
          }
        };
        void pollStatus();
      };
    } catch (e) {
      if (!isCurrent()) return;
      finishInstall('failed', e instanceof Error ? e.message : String(e));
    }
  }, [canInstall, repoPath, gymPath, host, user, password, effectivePython, keyPath, t]);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <SectionCardTitle
          icon={<ScanLine className="w-5 h-5" />}
          title={t('trainer.myPcProbe')}
        />
        <button
          onClick={onRunProbe}
          disabled={loading}
          className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors inline-flex items-center gap-1.5 ${
            loading
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
        <div
          role="alert"
          aria-live="assertive"
          className="text-sm text-red-400 bg-red-950/50 border border-red-900 rounded p-3"
        >
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

          {!supportedPlatform && result.platform !== 'unknown' && (
            <div className="text-sm text-yellow-400" role="status">
              {t('trainer.myPcInstallUnsupported')}
            </div>
          )}

        </div>
      )}

      {showInstallSection && (
        <div className="border-t border-zinc-800 pt-3 space-y-2">
          <form onSubmit={startInstall} className="space-y-3">
            <div className="space-y-2">
              <div>
                <label htmlFor="mypc-repo-path" className="block text-xs text-zinc-400 mb-1">
                  {t('trainer.myPcInstallRepoPath')}
                </label>
                <input
                  ref={repoInputRef}
                  id="mypc-repo-path"
                  name="repo_path"
                  type="text"
                  value={repoPath}
                  onChange={(event) => {
                    setRepoPath(event.target.value);
                    setPathError(false);
                  }}
                  onInvalid={() => setPathError(true)}
                  required
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  disabled={installing}
                  aria-invalid={pathError && !repoPath.trim() ? true : undefined}
                  aria-describedby={pathError ? 'mypc-install-path-error' : undefined}
                  className="w-full px-2 py-1.5 rounded bg-zinc-950 border border-zinc-700 text-sm text-zinc-200 disabled:opacity-60"
                />
              </div>
              <div>
                <label htmlFor="mypc-gym-path" className="block text-xs text-zinc-400 mb-1">
                  {t('trainer.myPcInstallGymPath')}
                </label>
                <input
                  ref={gymInputRef}
                  id="mypc-gym-path"
                  name="gym_path"
                  type="text"
                  value={gymPath}
                  onChange={(event) => {
                    setGymPath(event.target.value);
                    setPathError(false);
                  }}
                  onInvalid={() => setPathError(true)}
                  required
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  disabled={installing}
                  aria-invalid={pathError && !gymPath.trim() ? true : undefined}
                  aria-describedby={pathError ? 'mypc-install-path-error' : undefined}
                  className="w-full px-2 py-1.5 rounded bg-zinc-950 border border-zinc-700 text-sm text-zinc-200 disabled:opacity-60"
                />
              </div>
            </div>

            {pathError && (
              <div
                id="mypc-install-path-error"
                role="alert"
                aria-live="assertive"
                className="text-sm text-red-400"
              >
                {t('trainer.myPcInstallPathRequired')}
              </div>
            )}

            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-zinc-300">
                {missingDonkeycar
                  ? t('trainer.myPcInstallRerunProbe')
                  : t('trainer.myPcInstall')}
              </span>
              <button
                type="submit"
                disabled={installing || !canInstall}
                data-testid="mypc-install-button"
                className="px-3 py-1.5 rounded-md text-sm font-medium transition-colors inline-flex items-center gap-1.5 bg-cyan-600 hover:bg-cyan-700 text-white shrink-0 disabled:bg-zinc-800 disabled:text-zinc-500 disabled:cursor-not-allowed"
              >
                <Download className="w-4 h-4" />
                {t('trainer.myPcInstall')}
              </button>
            </div>
          </form>

          {installing && (
            <div
              role="status"
              aria-live="polite"
              className="flex items-center gap-2 text-sm text-cyan-400"
              data-testid="mypc-install-running"
            >
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('trainer.myPcInstallRunning')}
            </div>
          )}

          {installing && reconnecting && (
            <div
              role="status"
              aria-live="polite"
              className="flex items-center gap-2 text-sm text-yellow-400"
              data-testid="mypc-install-reconnecting"
            >
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {t('trainer.myPcInstallReconnecting')}
            </div>
          )}

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

          {!installing && installStatus === 'completed' && (
            <div
              role="status"
              aria-live="polite"
              className="flex items-center gap-2 text-sm text-green-400"
              data-testid="mypc-install-done"
            >
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              {t('trainer.myPcInstallDone')}
            </div>
          )}

          {!installing && installStatus === 'failed' && (
            <div
              role="alert"
              aria-live="assertive"
              className="text-sm text-red-400 bg-red-950/50 border border-red-900 rounded p-3"
              data-testid="mypc-install-error"
            >
              {installError || t('trainer.myPcInstallFailed', { message: '' })}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
