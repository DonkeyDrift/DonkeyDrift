import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, CircleDot, Loader2, Octagon, Video } from 'lucide-react';
import { Card, CardContent, CardHeader } from '../ui/Card';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { api, API_URL } from '../../services/api';
import { useTranslation } from '@/i18n';

/** 漂移会话状态快照（GET /api/drift/state）。 */
interface DriftState {
  state: 'idle' | 'calibrate' | 'record' | 'auto_observe' | 'auto_engaged';
  calibration_ready: boolean;
  /** 后端相机线程是否在跑（引擎模块级单例，页面刷新后仍在运行）。 */
  camera_running: boolean;
  beta_deg: number | null;
  pose: { x: number; y: number; heading_deg: number } | null;
  telemetry_count: number;
  camera_fps: number;
  frames_written: number;
  events: Array<{ kind: string; detail: Record<string, unknown>; t_s: number }>;
  config: Record<string, number>;
}

/** 状态轮询间隔（10Hz）。 */
export const DRIFT_STATE_POLL_MS = 100;
/** 轮询请求超时：防止后端慢时请求悬挂堆积。 */
export const DRIFT_API_TIMEOUT_MS = 3000;
/** 连续失败多少次后亮离线徽标（容忍单次抖动）。 */
export const DRIFT_OFFLINE_THRESHOLD = 3;
/** aiortc 非 trickle：等 ICE gathering 完成的最长时间，超时用现有 SDP 继续。 */
export const DRIFT_WEBRTC_ICE_GATHER_TIMEOUT_MS = 2000;
/** 协商后等待首轨（ontrack）的最长时间，超时回退 MJPEG。 */
export const DRIFT_WEBRTC_TRACK_TIMEOUT_MS = 5000;

const CAMERA_CONFIG_STORAGE_KEY = 'donkeydrifter_drift_camera_config';

type SavedCameraConfig = Partial<{
  cameraIndex: string;
  tagId: string;
  headingOffset: string;
  calibFile: string;
  exposure: string;
}>;

/** 相机接入表单持久化读取（localStorage 不可用时返回空）。 */
const readSavedCameraConfig = (): SavedCameraConfig => {
  try {
    return JSON.parse(window.localStorage.getItem(CAMERA_CONFIG_STORAGE_KEY) ?? '{}');
  } catch {
    return {};
  }
};

/** 可编辑参数（提交 POST /api/drift/config）。 */
const EDITABLE_PARAMS: Array<{ key: string; labelKey: string; step: number }> = [
  { key: 'beta_target_deg', labelKey: 'drive.driftParamBetaTarget', step: 1 },
  { key: 'k_beta', labelKey: 'drive.driftParamKBeta', step: 0.5 },
  { key: 'k_yaw', labelKey: 'drive.driftParamKYaw', step: 0.001 },
  { key: 'pulse_freq_hz', labelKey: 'drive.driftParamPulseFreq', step: 0.5 },
  { key: 'pulse_duty', labelKey: 'drive.driftParamPulseDuty', step: 0.05 },
  { key: 'pulse_amplitude', labelKey: 'drive.driftParamPulseAmplitude', step: 0.05 },
  { key: 'pulse_base', labelKey: 'drive.driftParamPulseBase', step: 0.05 },
  { key: 'max_steering_delta_per_tick', labelKey: 'drive.driftParamMaxSteeringDelta', step: 0.01 },
];

/** 参数物理域 clamp：[下限, 上限]。占空比/幅值 [0,1]，基础油门 [-1,1]，PID 增益 ≥0。 */
const PARAM_CLAMP: Record<string, [number, number]> = {
  k_beta: [0, Number.POSITIVE_INFINITY],
  k_yaw: [0, Number.POSITIVE_INFINITY],
  pulse_duty: [0, 1],
  pulse_amplitude: [0, 1],
  pulse_base: [-1, 1],
};

/** 启动表单数值字段（非法时标红）。 */
type CameraField = 'cameraIndex' | 'tagId' | 'headingOffset' | 'exposure';

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
  const [offline, setOffline] = useState(false);

  // 相机接入表单持久化：启动成功后存 localStorage，下次进页惰性回填
  const [cameraIndex, setCameraIndex] = useState(() => readSavedCameraConfig().cameraIndex ?? '0');
  const [tagId, setTagId] = useState(() => readSavedCameraConfig().tagId ?? '0');
  const [headingOffset, setHeadingOffset] = useState(() => readSavedCameraConfig().headingOffset ?? '0');
  const [calibFile, setCalibFile] = useState(() => readSavedCameraConfig().calibFile ?? 'field_homography.npz');
  const [exposure, setExposure] = useState(() => readSavedCameraConfig().exposure ?? '');
  const [invalidFields, setInvalidFields] = useState<CameraField[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [paramDraft, setParamDraft] = useState<Record<string, string>>({});
  const [webrtcFailed, setWebrtcFailed] = useState(false);
  const failCountRef = useRef(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await api.get<DriftState>('/drift/state', { timeout: DRIFT_API_TIMEOUT_MS });
      setState(res.data);
      // 相机运行状态以后端为准：相机线程是引擎单例，页面刷新后仍在跑
      if (typeof res.data.camera_running === 'boolean') {
        setCameraOn(res.data.camera_running);
      }
      failCountRef.current = 0;
      setOffline(false);
    } catch {
      // 连续失败达阈值才亮离线徽标，避免单次抖动误报
      failCountRef.current += 1;
      if (failCountRef.current >= DRIFT_OFFLINE_THRESHOLD) setOffline(true);
    }
  }, []);

  // 串行轮询：上一次请求 settle 后才排下一次，后端慢也不堆积
  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    const loop = async () => {
      await refresh();
      if (cancelled) return;
      timer = window.setTimeout(() => {
        void loop();
      }, DRIFT_STATE_POLL_MS);
    };
    void loop();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [refresh]);

  // WebRTC 60fps 预览：相机开启即协商；失败自动回退 MJPEG 流。
  // drift 后端是 aiortc（无 trickle ICE 端点）：必须等 ICE gathering 完成、
  // 候选全部并入 SDP 后再 POST localDescription，否则协商必败。
  useEffect(() => {
    if (!cameraOn) {
      pcRef.current?.close();
      pcRef.current = null;
      return;
    }
    let cancelled = false;
    let trackTimer: number | null = null;
    setWebrtcFailed(false);
    const fail = () => {
      if (cancelled) return;
      if (trackTimer !== null) {
        window.clearTimeout(trackTimer);
        trackTimer = null;
      }
      pcRef.current?.close();
      pcRef.current = null;
      setWebrtcFailed(true);
    };
    (async () => {
      try {
        const pc = new RTCPeerConnection();
        pcRef.current = pc;
        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.ontrack = (e) => {
          if (trackTimer !== null) {
            window.clearTimeout(trackTimer);
            trackTimer = null;
          }
          if (videoRef.current) videoRef.current.srcObject = e.streams[0];
        };
        pc.onconnectionstatechange = () => {
          if (pc.connectionState === 'failed' || pc.connectionState === 'closed') fail();
        };
        // 首轨超时：协商后迟迟无 ontrack 视为失败，回退 MJPEG
        trackTimer = window.setTimeout(fail, DRIFT_WEBRTC_TRACK_TIMEOUT_MS);
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        if (pc.iceGatheringState !== 'complete') {
          await new Promise<void>((resolve) => {
            const timer = window.setTimeout(() => {
              pc.onicegatheringstatechange = null;
              resolve(); // 兜底：gathering 事件缺失时也继续，用现有 SDP
            }, DRIFT_WEBRTC_ICE_GATHER_TIMEOUT_MS);
            pc.onicegatheringstatechange = () => {
              if (pc.iceGatheringState === 'complete') {
                window.clearTimeout(timer);
                pc.onicegatheringstatechange = null;
                resolve();
              }
            };
          });
        }
        if (cancelled) return;
        const local = pc.localDescription;
        const res = await api.post('/drift/webrtc/offer', {
          sdp: local?.sdp ?? offer.sdp,
          type: local?.type ?? offer.type,
        });
        if (cancelled) return;
        await pc.setRemoteDescription(res.data);
      } catch {
        fail();
      }
    })();
    return () => {
      cancelled = true;
      if (trackTimer !== null) window.clearTimeout(trackTimer);
      pcRef.current?.close();
      pcRef.current = null;
    };
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

  const startCamera = () => {
    const parsed: Record<CameraField, number | undefined> = {
      cameraIndex: Number(cameraIndex),
      tagId: Number(tagId),
      headingOffset: Number(headingOffset),
      exposure: exposure.trim() === '' ? undefined : Number(exposure),
    };
    const invalid = (Object.keys(parsed) as CameraField[]).filter((key) => {
      const v = parsed[key];
      // exposure 留空（undefined）合法表示自动；其余字段必须是有限数值
      return key === 'exposure' ? v !== undefined && !Number.isFinite(v) : !Number.isFinite(v);
    });
    setInvalidFields(invalid);
    if (invalid.length > 0) {
      setFormError(t('drive.driftInvalidNumber'));
      return;
    }
    setFormError(null);
    run(async () => {
      await api.post('/drift/camera/start', {
        camera_index: parsed.cameraIndex,
        tag_id: parsed.tagId,
        calibration_file: calibFile,
        heading_offset_deg: parsed.headingOffset,
        exposure: parsed.exposure,
      });
      setCameraOn(true);
      try {
        window.localStorage.setItem(
          CAMERA_CONFIG_STORAGE_KEY,
          JSON.stringify({ cameraIndex, tagId, headingOffset, calibFile, exposure }),
        );
      } catch {
        /* localStorage 不可用时静默跳过持久化 */
      }
    });
  };

  const stopCamera = () => run(async () => {
    await api.post('/drift/camera/stop');
    setCameraOn(false);
  });

  const startSession = (mode: 'calibrate' | 'record' | 'auto') =>
    run(() => api.post('/drift/session/start', { mode }).then(() => undefined));

  const stopSession = () => run(() => api.post('/drift/session/stop').then(() => undefined));

  const saveParams = () => run(async () => {
    const updates: Record<string, number> = {};
    const submitted: string[] = [];
    for (const [key, value] of Object.entries(paramDraft)) {
      const v = parseFloat(value);
      if (!Number.isFinite(v)) continue; // 非法值拒绝发送
      const clamp = PARAM_CLAMP[key];
      updates[key] = clamp ? Math.min(clamp[1], Math.max(clamp[0], v)) : v;
      submitted.push(key);
    }
    if (submitted.length > 0) {
      await api.post('/drift/config', updates);
    }
    // 只清已提交的 key：POST 进行中又敲的草稿保留
    setParamDraft((draft) => {
      const next = { ...draft };
      for (const key of submitted) delete next[key];
      return next;
    });
  });

  const fieldClass = (field: CameraField) =>
    invalidFields.includes(field) ? 'border-red-500' : undefined;

  const s = state?.state ?? 'idle';
  const active = s !== 'idle';
  const calibrationReady = state?.calibration_ready ?? false;

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle icon={<CircleDot className="h-4 w-4" />} title={t('drive.driftTitle')} />
      </CardHeader>
      <CardContent className="space-y-3">
        {/* 相机接入 */}
        <div className="grid grid-cols-[1fr_1fr_1fr_1fr_2fr_auto] gap-2 items-end">
          <div>
            <label className="block text-xs text-zinc-400 mb-1">{t('drive.driftCameraIndex')}</label>
            <Input value={cameraIndex} onChange={(e) => setCameraIndex(e.target.value)} disabled={cameraOn} className={fieldClass('cameraIndex')} />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">{t('drive.driftTagId')}</label>
            <Input value={tagId} onChange={(e) => setTagId(e.target.value)} disabled={cameraOn} className={fieldClass('tagId')} />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">{t('drive.driftHeadingOffset')}</label>
            <Input value={headingOffset} onChange={(e) => setHeadingOffset(e.target.value)} disabled={cameraOn} className={fieldClass('headingOffset')} />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">{t('drive.driftExposure')}</label>
            <Input value={exposure} placeholder={t('drive.driftExposurePlaceholder')} onChange={(e) => setExposure(e.target.value)} disabled={cameraOn} className={fieldClass('exposure')} />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">{t('drive.driftCalibFile')}</label>
            <Input value={calibFile} onChange={(e) => setCalibFile(e.target.value)} disabled={cameraOn} />
          </div>
          {cameraOn ? (
            <Button variant="secondary" onClick={stopCamera} disabled={busy}>
              <Octagon className="h-4 w-4" /> {t('drive.driftStopCamera')}
            </Button>
          ) : (
            <Button onClick={startCamera} disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />} {t('drive.driftStartCamera')}
            </Button>
          )}
        </div>
        {formError && <div className="text-xs text-red-400">{formError}</div>}

        {/* 俯拍预览：WebRTC 60fps 优先，失败回退 MJPEG */}
        {cameraOn && !webrtcFailed && (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="w-full rounded border border-zinc-700 bg-zinc-900 object-contain max-h-64"
          />
        )}
        {cameraOn && webrtcFailed && (
          <img
            src={`${API_URL}/drift/frame.mjpg`}
            alt={t('drive.driftPreviewAlt')}
            className="w-full rounded border border-zinc-700 bg-zinc-900 object-contain max-h-64"
          />
        )}

        {/* 实时状态 */}
        <div className="grid grid-cols-6 gap-2 text-center text-sm">
          <div>
            <div className="text-xs text-zinc-400">{t('drive.driftStateLabel')}</div>
            <div className="font-medium">{t(`drive.driftState.${s}`)}</div>
          </div>
          <div>
            <div className="text-xs text-zinc-400">β (°)</div>
            <div className="font-medium">{state?.beta_deg?.toFixed(1) ?? '—'}</div>
          </div>
          <div>
            <div className="text-xs text-zinc-400">{t('drive.driftPose')}</div>
            <div className="font-medium">
              {state?.pose ? `${state.pose.x.toFixed(2)},${state.pose.y.toFixed(2)}` : '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-zinc-400">{t('drive.driftHeading')}</div>
            <div className="font-medium">
              {state?.pose ? ((((state.pose.heading_deg % 360) + 360) % 360).toFixed(1)) : '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-zinc-400">{t('drive.driftCameraFps')}</div>
            <div className="font-medium">{cameraOn ? (state?.camera_fps ?? 0).toFixed(0) : '—'}</div>
          </div>
          <div>
            <div className="text-xs text-zinc-400">{t('drive.driftTelemetryFrames')}</div>
            <div className="font-medium">{state?.telemetry_count ?? 0} / {state?.frames_written ?? 0}</div>
          </div>
        </div>

        {/* 模式控制：录制/自动要求标定就绪（否则后端必 409） */}
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => startSession('calibrate')} disabled={busy || active || !cameraOn}>
            <CircleDot className="h-4 w-4" /> {t('drive.driftCalibrate')}
          </Button>
          <Button variant="secondary" onClick={() => startSession('record')} disabled={busy || active || !cameraOn || !calibrationReady}>
            <Video className="h-4 w-4" /> {t('drive.driftRecord')}
          </Button>
          <Button onClick={() => startSession('auto')} disabled={busy || active || !cameraOn || !calibrationReady}>
            <CircleDot className="h-4 w-4" /> {t('drive.driftAuto')}
          </Button>
          <Button variant="danger" onClick={stopSession} disabled={busy || !active}>
            <Octagon className="h-4 w-4" /> {t('drive.driftStopSession')}
          </Button>
        </div>

        {/* 参数面板 */}
        <div>
          <button className="text-xs text-zinc-400 underline" onClick={() => setParamsOpen(!paramsOpen)}>
            {paramsOpen ? t('drive.driftParamsCollapse') : t('drive.driftParamsExpand')}
          </button>
          {paramsOpen && state && (
            <div className="mt-2 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                {EDITABLE_PARAMS.map(({ key, labelKey, step }) => (
                  <div key={key}>
                    <label className="block text-xs text-zinc-400 mb-1">{t(labelKey)}</label>
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
                {t('drive.driftSaveParams')}
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
        {offline && <div className="text-xs text-red-400">{t('drive.driftOffline')}</div>}
        {state && !state.calibration_ready && (
          <div className="text-xs text-amber-400">{t('drive.driftCalibrationNotReady')}</div>
        )}
      </CardContent>
    </Card>
  );
};
