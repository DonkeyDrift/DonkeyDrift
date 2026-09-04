import React, { useState } from 'react';
import { Check, Cloud, Copy, Eye, EyeOff, Loader2 } from 'lucide-react';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { useStore } from '../../store/useStore';
import { getMyPcClientInfo, getMyPcKnownHosts } from '../../services/api';
import { useTranslation } from '@/i18n';

interface RemoteConfigFormProps {
  titleKey?: string;
  hintKey?: string;
  icon?: React.ReactNode;
  subtitleKey?: string;
  /** Compact mode: only show host / user / password / keyPath (used for "Lan Host"). */
  compact?: boolean;
  host: string;
  onHostChange: (v: string) => void;
  user: string;
  onUserChange: (v: string) => void;
  password: string;
  onPasswordChange: (v: string) => void;
  remoteDirBase: string;
  onRemoteDirBaseChange: (v: string) => void;
  modelName: string;
  onModelNameChange: (v: string) => void;
  pythonPath: string;
  onPythonPathChange: (v: string) => void;
  /** SSH 私钥路径（可选，留空用密码认证） */
  keyPath?: string;
  onKeyPathChange?: (v: string) => void;
}

const SSH_ENABLE_CMD = 'sudo systemsetup -setremotelogin on';

export const RemoteConfigForm: React.FC<RemoteConfigFormProps> = ({
  titleKey = 'trainer.cloudTraining',
  hintKey,
  icon = <Cloud className="w-5 h-5" />,
  subtitleKey,
  compact = false,
  host,
  onHostChange,
  user,
  onUserChange,
  password,
  onPasswordChange,
  remoteDirBase,
  onRemoteDirBaseChange,
  modelName,
  onModelNameChange,
  pythonPath,
  onPythonPathChange,
  keyPath = '',
  onKeyPathChange,
}) => {
  const { t } = useTranslation();
  const { configPath } = useStore();
  const [allLoading, setAllLoading] = useState(false);
  const [allHint, setAllHint] = useState<{ text: string; className: string } | null>(null);
  const [allHint2, setAllHint2] = useState<{ text: string; className: string } | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showSshGuide, setShowSshGuide] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleAutoFillAll = async () => {
    setAllLoading(true);
    setAllHint(null);
    setAllHint2(null);
    setShowSshGuide(false);
    try {
      const info = await getMyPcClientInfo(password || undefined);
      if (info.is_loopback || !info.ip) {
        setAllHint({ text: t('trainer.autoFillLoopback'), className: 'text-amber-400' });
        return;
      }
      onHostChange(info.ip);
      // IP 填入后固定给一行绿色反馈
      setAllHint({ text: t('trainer.autoFillApplied', { value: info.ip }), className: 'text-green-400' });
      try {
        const known = await getMyPcKnownHosts();
        const match = known.find((k) => k.host === info.ip) || known.find((k) => k.reachable);
        if (match) {
          onUserChange(match.user);
          // 安全约束：历史记录不存密码，密码永远由用户手填
          if (match.python_path) onPythonPathChange(match.python_path);
          setAllHint2({ text: t('trainer.autoFillFromHistory'), className: 'text-green-400' });
          return;
        }
      } catch {
        // Known-hosts lookup failed; fall through to the client-info result.
      }
      if (info.verified && info.username) {
        onUserChange(info.username);
        setAllHint2({ text: t('trainer.autoFillVerified', { value: info.username }), className: 'text-green-400' });
      } else if (!password) {
        // 未填密码时无法 SSH 验证用户名，只提示一行：需要先填密码
        setAllHint2({ text: t('trainer.autoFillNeedPassword'), className: 'text-amber-400' });
      } else if (info.ssh === 'unreachable') {
        setAllHint2({ text: t('trainer.autoFillNoSsh'), className: 'text-amber-400' });
        setShowSshGuide(true);
      } else if (info.ssh === 'auth_failed') {
        setAllHint2({ text: t('trainer.autoFillAuthFailed'), className: 'text-red-400' });
      } else {
        setAllHint2({ text: t('trainer.autoFillNoUser'), className: 'text-amber-400' });
      }
    } catch {
      setAllHint({ text: t('trainer.autoFillFailed'), className: 'text-red-400' });
    } finally {
      setAllLoading(false);
    }
  };

  const handleCopySshCmd = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(SSH_ENABLE_CMD);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = SSH_ENABLE_CMD;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Copy failed; leave the command visible for manual selection.
    }
  };

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <SectionCardTitle
          icon={icon}
          title={t(titleKey)}
          subtitle={subtitleKey ? t(subtitleKey) : undefined}
        />
        {compact && (
          <button
            type="button"
            onClick={handleAutoFillAll}
            disabled={allLoading}
            className="px-3 py-1.5 rounded-md text-sm font-medium bg-cyan-600 hover:bg-cyan-700 text-white disabled:opacity-50 inline-flex items-center gap-1.5 shrink-0"
          >
            {allLoading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {t('trainer.autoFill')}
          </button>
        )}
      </div>
      {allHint && <p className={`text-xs ${allHint.className}`}>{allHint.text}</p>}
      {allHint2 && <p className={`text-xs ${allHint2.className}`}>{allHint2.text}</p>}
      {hintKey && <p className="text-xs text-zinc-500">{t(hintKey)}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">{t('trainer.host')}</label>
          <input
            type="text"
            value={host}
            onChange={(e) => onHostChange(e.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            placeholder={t('trainer.hostPlaceholder')}
            className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:outline-none focus:border-cyan-600"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">{t('trainer.user')}</label>
          <input
            type="text"
            value={user}
            onChange={(e) => onUserChange(e.target.value)}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            placeholder={t('trainer.userPlaceholder')}
            className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:outline-none focus:border-cyan-600"
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">{t('trainer.password')}</label>
        <div className="relative">
          <input
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => onPasswordChange(e.target.value)}
            autoComplete="new-password"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            data-1p-ignore="true"
            data-lpignore="true"
            data-form-type="other"
            placeholder={t('trainer.passwordPlaceholder')}
            className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 pr-9 text-sm text-zinc-200 placeholder:text-zinc-700 focus:outline-none focus:border-cyan-600"
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            aria-label={t(showPassword ? 'trainer.hidePassword' : 'trainer.showPassword')}
            title={t(showPassword ? 'trainer.hidePassword' : 'trainer.showPassword')}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
        {showSshGuide && (
          <>
            <p className="text-xs text-zinc-500">{t('trainer.enableSshGuide')}</p>
            <div className="flex items-center gap-2 bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5">
              <code className="flex-1 text-xs text-amber-300 font-mono select-all">{SSH_ENABLE_CMD}</code>
              <button
                type="button"
                onClick={handleCopySshCmd}
                className="text-xs text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1"
              >
                {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                {copied ? t('trainer.copied') : t('trainer.copyCommand')}
              </button>
            </div>
          </>
        )}
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">{t('trainer.keyPath')}</label>
        <input
          type="text"
          value={keyPath}
          placeholder="~/.ssh/id_rsa"
          onChange={(e) => onKeyPathChange?.(e.target.value)}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-700 focus:outline-none focus:border-cyan-600"
        />
      </div>

      {!compact && (
        <>
          <div className="space-y-1">
            <label className="text-xs text-zinc-500">{t('trainer.remoteDirBase')}</label>
            <input
              type="text"
              value={remoteDirBase}
              onChange={(e) => onRemoteDirBaseChange(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-zinc-500">{t('trainer.modelName')}</label>
            <input
              type="text"
              value={modelName}
              onChange={(e) => onModelNameChange(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-zinc-500">{t('trainer.pythonPath')}</label>
            <input
              type="text"
              value={pythonPath}
              onChange={(e) => onPythonPathChange(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
            />
          </div>
        </>
      )}

      <div className="text-xs text-zinc-600">{t('trainer.workingDir', { path: configPath })}</div>
    </div>
  );
};
