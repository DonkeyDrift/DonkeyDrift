import { useCallback, useState } from 'react';
import { probeMyPc, type MyPcProbeResult } from '../services/api';
import { useTranslation } from '@/i18n';

export interface MyPcProbeArgs {
  host: string;
  user: string;
  password: string;
  remoteDirBase: string;
  pythonPath: string;
  /** SSH 私钥路径（可选，与表单 keyPath 一致；留空时后端回退默认密钥/密码认证） */
  keyPath?: string;
}

export function useMyPcProbe() {
  const { t } = useTranslation();
  const [result, setResult] = useState<MyPcProbeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runProbe = useCallback(
    async (args: MyPcProbeArgs): Promise<MyPcProbeResult | null> => {
      setLoading(true);
      setError(null);
      setResult(null);
      try {
        const data = await probeMyPc({
          host: args.host,
          user: args.user,
          password: args.password,
          remote_dir_base: args.remoteDirBase,
          python_path: args.pythonPath,
          key_path: args.keyPath || undefined,
        });
        setResult(data);
        return data;
      } catch (e) {
        setError(
          t('trainer.myPcProbeFailed', {
            message: e instanceof Error ? e.message : String(e),
          })
        );
        return null;
      } finally {
        setLoading(false);
      }
    },
    [t]
  );

  return { result, loading, error, runProbe };
}
