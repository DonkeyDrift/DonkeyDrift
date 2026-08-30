import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, CircleDot, Loader2, Octagon, Video } from 'lucide-react';
import { Card, CardContent, CardHeader } from '../ui/Card';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { api } from '../../services/api';
import { useTranslation } from '@/i18n';

/** 漂移会话状态快照（GET /api/drift/state）。 */
interface DriftState {
  state: 'idle' | 'calibrate' | 'record' | 'auto_observe' | 'auto_engaged';
  calibration_ready: boolean;
  beta_deg: number | null;
  pose: { x: number; y: number; heading_deg: number } | null;
  telemetry_count: number;
  frames_written: number;
  events: Array<{ kind: string; detail: Record<string, unknown>; t_s: number }>;
  config: Record<string, number>;
}

const STATE_LABEL: Record<DriftState['state'], string> = {
  idle: '空闲',
  calibrate: '标定中',
  record: '录制中',
  auto_observe: '自动·观察（人 RC 起漂）',
  auto_engaged: '自动·已接管',
};

/** 可编辑参数（提交 POST /api/drift/config）。 */
const EDITABLE_PARAMS: Array<{ key: string; label: string; step: number }> = [
  { key: 'beta_target_deg', label: '目标侧滑角 β* (°)', step: 1 },
  { key: 'k_beta', label: 'β 环增益', step: 0.5 },
  { key: 'k_yaw', label: '横摆环增益', step: 0.001 },
  { key: 'pulse_freq_hz', label: '点动频率 f (Hz)', step: 0.5 },
  { key: 'pulse_duty', label: '占空比 D', step: 0.05 },
  { key: 'pulse_amplitude', label: '脉冲幅值 A', step: 0.05 },
  { key: 'pulse_base', label: '基础油门 T_base', step: 0.05 },
  { key: 'max_steering_delta_per_tick', label: '转向变化率限幅', step: 0.01 },
];

/**
 * 「第三视角漂移」卡片（RFC docs/Rfc/overhead-drift-control.md）：
 * 俯拍相机接入 → 标定就绪 → 录制（人 RC 漂移）/ 自动（RC 起漂后接管）。
 * 卡片只读状态与下发会话控制；控制指令由后端引擎经 drive 通路下发。
 */
export const DriftCard: React.FC = () => {
  const { t } = useTranslation();
  const [state, setState] = useState<DriftState | null>(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cameraIndex, setCameraIndex] = useState('0');
  const [tagId, setTagId] = useState('0');
  const [calibFile, setCalibFile] = useState('field_homography.npz');
  const [paramsOpen, setParamsOpen] = useState(false);
  const [paramDraft, setParamDraft] = useState<Record<string, string>>({});
  const [previewStamp, setPreviewStamp] = useState(0);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await api.get<DriftState>('/drift/state');
      setState(res.data);
    } catch {
      /* 后端未就绪时静默重试 */
    }
  }, []);

  useEffect(() => {
    refresh();
    pollRef.current = window.setInterval(refresh, 2000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [refresh]);

  useEffect(() => {
    if (!cameraOn) return;
    const id = window.setInterval(() => setPreviewStamp(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [cameraOn]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? String(e));
    } finally {
      setBusy(false);
    }
  };

  const startCamera = () => run(async () => {
    await api.post('/drift/camera/start', {
      camera_index: Number(cameraIndex),
      tag_id: Number(tagId),
      calibration_file: calibFile,
    });
    setCameraOn(true);
  });

  const stopCamera = () => run(async () => {
    await api.post('/drift/camera/stop');
    setCameraOn(false);
  });

  const startSession = (mode: 'record' | 'auto') =>
    run(() => api.post('/drift/session/start', { mode }).then(() => undefined));

  const stopSession = () => run(() => api.post('/drift/session/stop').then(() => undefined));

  const saveParams = () => run(async () => {
    const updates: Record<string, number> = {};
    for (const [key, value] of Object.entries(paramDraft)) {
      const v = parseFloat(value);
      if (Number.isFinite(v)) updates[key] = v;
    }
    if (Object.keys(updates).length > 0) {
      await api.post('/drift/config', updates);
    }
    setParamDraft({});
  });

  const s = state?.state ?? 'idle';
  const active = s !== 'idle';

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle icon={<CircleDot className="h-4 w-4" />} title={t('drive.driftTitle')} />
      </CardHeader>
      <CardContent className="space-y-3">
        {/* 相机接入 */}
        <div className="grid grid-cols-[1fr_1fr_2fr_auto] gap-2 items-end">
          <div>
            <label className="block text-xs text-zinc-400 mb-1">相机 index</label>
            <Input value={cameraIndex} onChange={(e) => setCameraIndex(e.target.value)} disabled={cameraOn} />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">AprilTag ID</label>
            <Input value={tagId} onChange={(e) => setTagId(e.target.value)} disabled={cameraOn} />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">单应性标定文件</label>
            <Input value={calibFile} onChange={(e) => setCalibFile(e.target.value)} disabled={cameraOn} />
          </div>
          {cameraOn ? (
            <Button variant="secondary" onClick={stopCamera} disabled={busy}>
              <Octagon className="h-4 w-4" /> 关相机
            </Button>
          ) : (
            <Button onClick={startCamera} disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />} 启动相机
            </Button>
          )}
        </div>

        {/* 俯拍预览 */}
        {cameraOn && (
          <img
            src={`/api/drift/frame.jpg?_=${previewStamp}`}
            alt="俯拍预览"
            className="w-full rounded border border-zinc-700 bg-zinc-900 object-contain max-h-64"
          />
        )}

        {/* 实时状态 */}
        <div className="grid grid-cols-4 gap-2 text-center text-sm">
          <div>
            <div className="text-xs text-zinc-400">状态</div>
            <div className="font-medium">{STATE_LABEL[s]}</div>
          </div>
          <div>
            <div className="text-xs text-zinc-400">β (°)</div>
            <div className="font-medium">{state?.beta_deg?.toFixed(1) ?? '—'}</div>
          </div>
          <div>
            <div className="text-xs text-zinc-400">位姿 (x,y)</div>
            <div className="font-medium">
              {state?.pose ? `${state.pose.x.toFixed(2)},${state.pose.y.toFixed(2)}` : '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-zinc-400">遥测/已录帧</div>
            <div className="font-medium">{state?.telemetry_count ?? 0} / {state?.frames_written ?? 0}</div>
          </div>
        </div>

        {/* 模式控制 */}
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => startSession('record')} disabled={busy || active || !cameraOn}>
            <Video className="h-4 w-4" /> 录制（人 RC 漂移）
          </Button>
          <Button onClick={() => startSession('auto')} disabled={busy || active || !cameraOn}>
            <CircleDot className="h-4 w-4" /> 自动漂移
          </Button>
          <Button variant="danger" onClick={stopSession} disabled={busy || !active}>
            <Octagon className="h-4 w-4" /> 停止 / 交还人工
          </Button>
        </div>

        {/* 参数面板 */}
        <div>
          <button className="text-xs text-zinc-400 underline" onClick={() => setParamsOpen(!paramsOpen)}>
            {paramsOpen ? '收起' : '展开'}控制器参数
          </button>
          {paramsOpen && state && (
            <div className="mt-2 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                {EDITABLE_PARAMS.map(({ key, label, step }) => (
                  <div key={key}>
                    <label className="block text-xs text-zinc-400 mb-1">{label}</label>
                    <Input
                      type="number"
                      step={step}
                      value={paramDraft[key] ?? String(state.config[key] ?? '')}
                      onChange={(e) => setParamDraft({ ...paramDraft, [key]: e.target.value })}
                    />
                  </div>
                ))}
              </div>
              <Button size="sm" onClick={saveParams} disabled={busy || Object.keys(paramDraft).length === 0}>
                保存参数
              </Button>
            </div>
          )}
        </div>

        {/* 事件尾巴 */}
        {state && state.events.length > 0 && (
          <div className="text-xs text-zinc-500 max-h-20 overflow-y-auto">
            {state.events.slice(-5).map((e, i) => (
              <div key={i}>
                [{new Date(e.t_s * 1000).toLocaleTimeString()}] {e.kind}
                {typeof e.detail?.reason === 'string' ? `：${e.detail.reason}` : ''}
              </div>
            ))}
          </div>
        )}

        {error && <div className="text-xs text-red-400">{error}</div>}
        {!state?.calibration_ready && (
          <div className="text-xs text-amber-400">标定文件未就绪：先运行 scripts/calibrate_field_homography.py</div>
        )}
      </CardContent>
    </Card>
  );
};
