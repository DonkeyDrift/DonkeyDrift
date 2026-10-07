import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Cpu, X, Loader2, CheckCircle2, XCircle, AlertTriangle, ScrollText,
} from 'lucide-react';
import {
  startAimoConvert,
  stopTrain,
  getAimoKeyStatus,
  getJobStatus,
  listTrainerTubs,
  createLogStream,
  getApiErrorMessage,
  type AimoKeyStatus,
  type TrainerTub,
} from '../../services/api';
import { useStore } from '../../store/useStore';
import { useTranslation } from '@/i18n';

export const NPU_SUPPORTED_EXTS = ['.onnx', '.tflite', '.pb', '.pt', '.pth'];

export function isNpuConvertible(name: string, type: 'file' | 'dir'): boolean {
  const lower = name.toLowerCase();
  if (type === 'dir') return lower.endsWith('.savedmodel');
  return NPU_SUPPORTED_EXTS.some((ext) => lower.endsWith(ext));
}

interface NpuConvertModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 打开时预填的源模型路径（模型列表行内入口传入） */
  initialModelPath?: string;
  /** 转换成功后回调（模型列表刷新） */
  onCompleted?: () => void;
}

interface ConvertJobState {
  jobId: string;
  status: 'running' | 'completed' | 'failed' | 'stopped';
  logs: string[];
  percent: number;
  resultPath: string | null;
  errorMessage: string | null;
}

const inputClass =
  'mt-1 block w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-cyan-600';

export const NpuConvertModal: React.FC<NpuConvertModalProps> = ({
  isOpen,
  onClose,
  initialModelPath,
  onCompleted,
}) => {
  const { t } = useTranslation();
  const { configPath } = useStore();

  const [modelPath, setModelPath] = useState('');
  const [outDir, setOutDir] = useState('./models');
  const [precision, setPrecision] = useState<'INT8' | 'INT16' | 'FP16'>('INT8');
  const [calibTub, setCalibTub] = useState('');
  const [calibDataset, setCalibDataset] = useState('imagenet');
  const [calibMax, setCalibMax] = useState(100);
  const [mixSynth, setMixSynth] = useState(30);
  const [timeoutS, setTimeoutS] = useState(3600);

  const [tubs, setTubs] = useState<TrainerTub[]>([]);
  const [keyStatus, setKeyStatus] = useState<AimoKeyStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [job, setJob] = useState<ConvertJobState | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const logScrollRef = useRef<HTMLDivElement>(null);

  const closeLogStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  // 每次打开重置表单并拉取前置条件（key 状态 + 校准 tub 列表）
  useEffect(() => {
    if (!isOpen) return;
    setModelPath(initialModelPath ?? '');
    setOutDir('./models');
    setPrecision('INT8');
    setCalibTub('');
    setCalibDataset('imagenet');
    setCalibMax(100);
    setMixSynth(30);
    setTimeoutS(3600);
    setStartError(null);
    setJob(null);
    getAimoKeyStatus().then(setKeyStatus).catch(() => setKeyStatus(null));
    listTrainerTubs(configPath || undefined)
      .then((data) => setTubs(data.tubs || []))
      .catch(() => setTubs([]));
  }, [isOpen, initialModelPath, configPath]);

  // 关闭/卸载时断开 SSE（转换任务本身在后端继续跑，不受影响）
  useEffect(() => {
    if (!isOpen) closeLogStream();
    return closeLogStream;
  }, [isOpen, closeLogStream]);

  // 日志自动滚到底部
  useEffect(() => {
    if (logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [job?.logs.length]);

  const handleSubmit = useCallback(async () => {
    if (!modelPath.trim() || submitting) return;
    setSubmitting(true);
    setStartError(null);
    try {
      const res = await startAimoConvert({
        model_path: modelPath.trim(),
        out_dir: outDir.trim() || './models',
        working_dir: configPath || undefined,
        precision,
        calib_tubs: calibTub || null,
        calib_max: calibMax,
        calib_mix_synth: calibTub ? mixSynth : 0,
        calib_dataset: calibDataset,
        timeout_s: timeoutS,
      });
      const es = createLogStream(res.job_id);
      eventSourceRef.current = es;
      setJob({ jobId: res.job_id, status: 'running', logs: [], percent: 0, resultPath: null, errorMessage: null });
      es.onmessage = async (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'log') {
            const line = String(msg.line ?? '');
            setJob((prev) => (prev ? { ...prev, logs: [...prev.logs, line] } : prev));
          } else if (msg.type === 'progress') {
            const percent = Number(msg.data?.globalPercent ?? 0);
            setJob((prev) => (prev ? { ...prev, percent } : prev));
          } else if (msg.type === 'error') {
            const line = String(msg.message ?? 'Unknown error');
            setJob((prev) => (prev ? { ...prev, logs: [...prev.logs, line] } : prev));
          } else if (msg.type === 'status' && ['completed', 'failed', 'stopped'].includes(msg.status)) {
            // SSE 终态消息不携带产物路径，补一次 REST 查询取 result_path
            let resultPath: string | null = null;
            try {
              const st = await getJobStatus(res.job_id);
              resultPath = st.result_path ?? null;
            } catch {
              // 拿不到就只显示终态
            }
            setJob((prev) => (prev ? {
              ...prev,
              status: msg.status,
              errorMessage: msg.error ?? null,
              resultPath,
            } : prev));
            closeLogStream();
            if (msg.status === 'completed' && onCompleted) onCompleted();
          }
        } catch {
          // 非 JSON 心跳等消息，忽略
        }
      };
      es.onerror = () => {
        // SSE 断开（后端重启等）；保留已收到的日志，状态不再更新
        closeLogStream();
      };
    } catch (error) {
      setStartError(getApiErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }, [modelPath, submitting, outDir, configPath, precision, calibTub, calibDataset, calibMax, mixSynth, timeoutS, closeLogStream, onCompleted]);

  const handleStop = useCallback(async () => {
    if (!job || job.status !== 'running') return;
    try {
      await stopTrain(job.jobId);
    } catch {
      // 状态以 SSE 终态消息为准
    }
  }, [job]);

  if (!isOpen) return null;

  const running = job?.status === 'running';
  const keyOk = (keyStatus?.sdk ?? true) && (keyStatus?.key ?? false);

  const keyStatusLine = !keyStatus
    ? null
    : keyStatus.sdk
    ? keyStatus.key
      ? keyStatus.keySource === 'file'
        ? t('trainer.npuConvertKeyOkFile')
        : t('trainer.npuConvertKeyOkEnv')
      : t('trainer.npuConvertKeyMissing')
    : t('trainer.npuConvertSdkMissing');

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
      data-testid="npu-convert-dialog"
    >
      <div
        className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-[480px] max-h-[90vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-semibold text-zinc-200 flex items-center gap-2">
            <Cpu className="w-4 h-4 text-cyan-400" />
            {t('trainer.npuConvertTitle')}
          </h4>
          <button
            onClick={onClose}
            aria-label={t('trainer.close')}
            title={t('trainer.close')}
            className="p-1 text-zinc-500 hover:text-zinc-200 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {running && (
          <p className="mb-3 text-[11px] text-zinc-500">{t('trainer.npuConvertCloseHint')}</p>
        )}

        {/* 前置条件：SDK / API Key */}
        {keyStatus && !keyOk && (
          <div
            className="mb-3 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300 space-y-1"
            data-testid="npu-key-warning"
          >
            <div className="flex items-center gap-1.5 font-medium">
              <AlertTriangle className="w-3.5 h-3.5" />
              {keyStatusLine}
            </div>
            {!keyStatus.sdk && <p>{t('trainer.npuConvertSdkHint')}</p>}
            {!keyStatus.key && <p>{t('trainer.npuConvertKeyHint')}</p>}
          </div>
        )}

        {!job ? (
          <div className="space-y-3">
            <label className="block">
              <span className="text-xs text-zinc-400">{t('trainer.npuConvertModelPath')}</span>
              <input
                type="text"
                value={modelPath}
                onChange={(e) => setModelPath(e.target.value)}
                placeholder="./models/pilot.tflite"
                className={inputClass}
                data-testid="npu-model-path"
              />
            </label>
            <label className="block">
              <span className="text-xs text-zinc-400">{t('trainer.npuConvertOutDir')}</span>
              <input
                type="text"
                value={outDir}
                onChange={(e) => setOutDir(e.target.value)}
                className={inputClass}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.npuConvertPrecision')}</span>
                <select
                  value={precision}
                  onChange={(e) => setPrecision(e.target.value as typeof precision)}
                  className={inputClass}
                >
                  <option value="INT8">INT8</option>
                  <option value="INT16">INT16</option>
                  <option value="FP16">FP16</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.npuConvertTimeout')}</span>
                <input
                  type="number"
                  min={60}
                  step={60}
                  value={timeoutS}
                  onChange={(e) => setTimeoutS(Number(e.target.value) || 3600)}
                  className={inputClass}
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.npuConvertCalibTub')}</span>
                <select
                  value={calibTub}
                  onChange={(e) => setCalibTub(e.target.value)}
                  className={inputClass}
                  data-testid="npu-calib-tub"
                >
                  <option value="">{t('trainer.npuConvertCalibNone')}</option>
                  {tubs.map((tub) => (
                    <option key={tub.absolute_path} value={tub.absolute_path}>
                      {tub.relative_path}
                    </option>
                  ))}
                </select>
              </label>
              {calibTub ? (
                <label className="block">
                  <span className="text-xs text-zinc-400">{t('trainer.npuConvertMixSynth')}</span>
                  <input
                    type="number"
                    min={0}
                    max={Math.max(0, calibMax - 1)}
                    value={mixSynth}
                    onChange={(e) => setMixSynth(Number(e.target.value) || 0)}
                    className={inputClass}
                  />
                  <span className="mt-1 block text-[10px] text-zinc-600">{t('trainer.npuConvertMixSynthHint')}</span>
                </label>
              ) : (
                <label className="block">
                  <span className="text-xs text-zinc-400">{t('trainer.npuConvertCalibDataset')}</span>
                  <select
                    value={calibDataset}
                    onChange={(e) => setCalibDataset(e.target.value)}
                    className={inputClass}
                  >
                    <option value="imagenet">ImageNet</option>
                    <option value="coco">COCO</option>
                    <option value="face">Face</option>
                    <option value="normal">Normal</option>
                  </select>
                </label>
              )}
            </div>
            {calibTub && (
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.npuConvertCalibMax')}</span>
                <input
                  type="number"
                  min={1}
                  max={1000}
                  value={calibMax}
                  onChange={(e) => setCalibMax(Number(e.target.value) || 100)}
                  className={inputClass}
                />
              </label>
            )}

            {startError && (
              <p className="text-xs text-red-400" data-testid="npu-start-error">{startError}</p>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={onClose}
                className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
              >
                {t('trainer.cancel')}
              </button>
              <button
                onClick={handleSubmit}
                disabled={!modelPath.trim() || submitting}
                className="px-3 py-1.5 text-xs bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 rounded transition-colors disabled:text-zinc-600 disabled:bg-zinc-800 inline-flex items-center gap-1.5"
                data-testid="npu-convert-start"
              >
                {submitting && <Loader2 className="w-3 h-3 animate-spin" />}
                {submitting ? t('trainer.npuConvertStarting') : t('trainer.npuConvertStart')}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3" data-testid="npu-convert-progress">
            {/* 阶段进度 */}
            <div>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-zinc-400">
                  {running && <Loader2 className="w-3 h-3 inline animate-spin mr-1" />}
                  {job.status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 inline text-emerald-400 mr-1" />}
                  {job.status === 'failed' && <XCircle className="w-3.5 h-3.5 inline text-red-400 mr-1" />}
                  {job.status === 'stopped' && <XCircle className="w-3.5 h-3.5 inline text-zinc-400 mr-1" />}
                  {job.status === 'running'
                    ? t('trainer.npuConvertRunning')
                    : job.status === 'completed'
                    ? t('trainer.npuConvertDone')
                    : job.status === 'stopped'
                    ? t('trainer.statusStopped')
                    : t('trainer.npuConvertFailed')}
                </span>
                <span className="text-zinc-600">{Math.round(job.percent)}%</span>
              </div>
              <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    job.status === 'failed'
                      ? 'bg-red-500'
                      : job.status === 'completed'
                      ? 'bg-emerald-500'
                      : 'bg-cyan-500'
                  }`}
                  style={{ width: `${Math.min(100, Math.max(2, job.percent))}%` }}
                />
              </div>
            </div>

            {job.status === 'completed' && job.resultPath && (
              <p className="text-xs text-emerald-400 break-all" data-testid="npu-result-path">
                {t('trainer.npuConvertResult', { path: job.resultPath })}
              </p>
            )}
            {job.status === 'failed' && (
              <p className="text-xs text-red-400 break-all">
                {job.errorMessage || t('trainer.npuConvertFailed')}
              </p>
            )}

            {/* 日志 */}
            <div className="border border-zinc-800 rounded overflow-hidden">
              <div className="px-2 py-1.5 bg-zinc-950/60 flex items-center gap-1.5 text-xs text-zinc-400 border-b border-zinc-800">
                <ScrollText className="w-3.5 h-3.5" />
                {t('trainer.npuConvertLogTitle')}
              </div>
              <div
                ref={logScrollRef}
                className="h-44 overflow-y-auto p-2 font-mono text-[10px] leading-relaxed space-y-0.5 bg-zinc-950"
                data-testid="npu-convert-log"
              >
                {job.logs.length === 0 && (
                  <div className="text-zinc-600 italic">{t('trainer.logEmpty')}</div>
                )}
                {job.logs.map((line, idx) => (
                  <div key={idx} className="text-zinc-300 break-all whitespace-pre-wrap">
                    {line}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex justify-end gap-2">
              {running ? (
                <button
                  onClick={handleStop}
                  className="px-3 py-1.5 text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded transition-colors"
                  data-testid="npu-convert-stop"
                >
                  {t('trainer.npuConvertStop')}
                </button>
              ) : (
                <button
                  onClick={onClose}
                  className="px-3 py-1.5 text-xs bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 rounded transition-colors"
                >
                  {t('trainer.close')}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
