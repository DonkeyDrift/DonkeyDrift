import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Sparkles,
  Bot,
  Brain,
  Moon,
  Cloud,
  Search,
  Puzzle,
  Plus,
  Trash2,
  ExternalLink,
  Loader2,
  ChevronDown,
  ChevronRight,
  KeyRound,
  LogIn,
  type LucideIcon,
} from 'lucide-react';
import { Card, CardContent, CardHeader } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { Button } from './ui/Button';
import { useTranslation } from '@/i18n';
import {
  listAiConfigProviders,
  setActiveAiProvider,
  saveAiConfigAccount,
  deleteAiConfigAccount,
  createCustomAiProvider,
  deleteCustomAiProvider,
  startAiOAuthDeviceCode,
  pollAiOAuthDeviceCode,
  testAiConfigConnection,
  type AiConfigProvider,
  type AiConfigAccount,
} from '../services/api';

/**
 * AI 配置（Issue #403）：Car Connector 第三块面板。
 * 集中配置多供应商 AI 模型（预设 + 自定义），支持 API Key / Codex ChatGPT OAuth，
 * 一键切换「当前使用中」供应商，多账号管理。凭据只显示掩码、仅本地保存。
 */
const PROVIDER_ICONS: Record<string, LucideIcon> = {
  sparkles: Sparkles,
  bot: Bot,
  brain: Brain,
  moon: Moon,
  cloud: Cloud,
  search: Search,
  puzzle: Puzzle,
};

function ProviderIcon({ icon }: { icon: string }) {
  const Icon = PROVIDER_ICONS[icon] ?? Puzzle;
  return <Icon className="h-4 w-4 shrink-0 text-cyan-400" />;
}

interface AccountFormState {
  name: string;
  apiKey: string;
  baseUrl: string;
  models: string;
}

const EMPTY_ACCOUNT_FORM: AccountFormState = { name: '', apiKey: '', baseUrl: '', models: '' };

function AccountForm({ providerId, onSaved }: { providerId: string; onSaved: () => void }) {
  const { t } = useTranslation();
  const [form, setForm] = useState<AccountFormState>(EMPTY_ACCOUNT_FORM);
  const [saving, setSaving] = useState(false);

  const submit = useCallback(async () => {
    setSaving(true);
    try {
      await saveAiConfigAccount(providerId, {
        name: form.name.trim() || undefined,
        api_key: form.apiKey,
        base_url: form.baseUrl.trim() || undefined,
        models: form.models
          .split(',')
          .map((m) => m.trim())
          .filter(Boolean),
      });
      setForm(EMPTY_ACCOUNT_FORM);
      onSaved();
    } catch {
      // 保存失败时保留输入，静默跳过
    } finally {
      setSaving(false);
    }
  }, [form, providerId, onSaved]);

  return (
    <div className="mt-2 space-y-2 rounded-md border border-zinc-800 bg-zinc-900/60 p-3">
      <input
        className="h-8 w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        placeholder={t('aiConfig.nameLabel')}
        value={form.name}
        onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
        aria-label={t('aiConfig.nameLabel')}
      />
      <input
        className="h-8 w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        placeholder={t('aiConfig.apiKeyPlaceholder')}
        value={form.apiKey}
        onChange={(e) => setForm((f) => ({ ...f, apiKey: e.target.value }))}
        aria-label={t('aiConfig.apiKeyLabel')}
      />
      <input
        className="h-8 w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        placeholder={t('aiConfig.baseUrlLabel')}
        value={form.baseUrl}
        onChange={(e) => setForm((f) => ({ ...f, baseUrl: e.target.value }))}
        aria-label={t('aiConfig.baseUrlLabel')}
      />
      <input
        className="h-8 w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        placeholder={t('aiConfig.modelsLabel')}
        value={form.models}
        onChange={(e) => setForm((f) => ({ ...f, models: e.target.value }))}
        aria-label={t('aiConfig.modelsLabel')}
      />
      <Button onClick={() => void submit()} disabled={saving} variant="secondary" size="sm" data-testid={`ai-add-account-${providerId}`}>
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        {saving ? t('aiConfig.saving') : t('aiConfig.addAccount')}
      </Button>
    </div>
  );
}

function CodexOAuthFlow({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [device, setDevice] = useState<{ device_code: string; user_code: string; verification_uri: string; interval: number } | null>(null);
  const [status, setStatus] = useState<'idle' | 'waiting' | 'success' | 'error' | 'expired'>('idle');
  const [message, setMessage] = useState('');
  const [starting, setStarting] = useState(false);
  const timerRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (timerRef.current != null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const start = useCallback(async () => {
    setStarting(true);
    setMessage('');
    try {
      const result = await startAiOAuthDeviceCode('codex');
      setDevice({
        device_code: result.device_code,
        user_code: result.user_code,
        verification_uri: result.verification_uri,
        interval: result.interval,
      });
      setStatus('waiting');
      const interval = Math.max(2000, (result.interval || 5) * 1000);
      timerRef.current = window.setInterval(() => void poll(result.device_code, result.user_code), interval);
    } catch {
      setStatus('error');
      setMessage(t('aiConfig.oauthError', { detail: '' }));
    } finally {
      setStarting(false);
    }
  }, [t]);

  const poll = useCallback(async (deviceCode: string, userCode: string) => {
    try {
      const result = await pollAiOAuthDeviceCode(deviceCode, userCode);
      if (result.status === 'success') {
        stopPolling();
        setStatus('success');
        onDone();
      } else if (result.status === 'expired') {
        stopPolling();
        setStatus('expired');
        setMessage(t('aiConfig.oauthExpired'));
      } else if (result.status === 'error') {
        stopPolling();
        setStatus('error');
        setMessage(t('aiConfig.oauthError', { detail: result.detail ?? '' }));
      }
      // pending：继续等待
    } catch {
      // 轮询失败保持现状
    }
  }, [stopPolling, onDone, t]);

  const cancel = useCallback(() => {
    stopPolling();
    setDevice(null);
    setStatus('idle');
  }, [stopPolling]);

  if (status === 'idle') {
    return (
      <Button onClick={() => void start()} disabled={starting} variant="secondary" size="sm" data-testid="ai-codex-oauth-start">
        {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
        {t('aiConfig.oauthLogin')}
      </Button>
    );
  }

  return (
    <div className="mt-2 space-y-2 rounded-md border border-zinc-800 bg-zinc-900/60 p-3">
      {device && status === 'waiting' && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400">{t('aiConfig.oauthCodeLabel')}:</span>
            <code className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-sm text-cyan-200" data-testid="ai-codex-user-code">{device.user_code}</code>
          </div>
          <a
            className="inline-flex items-center gap-1 text-sm text-cyan-200 hover:text-cyan-400"
            href={device.verification_uri}
            target="_blank"
            rel="noreferrer"
          >
            {t('aiConfig.oauthOpenLink')} <ExternalLink className="h-3.5 w-3.5" />
          </a>
          <p className="flex items-center gap-2 text-xs text-zinc-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t('aiConfig.oauthPending')}
          </p>
        </>
      )}
      {status === 'success' && <p className="text-sm text-emerald-400">{t('aiConfig.oauthSuccess')}</p>}
      {(status === 'error' || status === 'expired') && <p className="text-sm text-red-400">{message}</p>}
      {status !== 'success' && (
        <Button onClick={cancel} variant="ghost" size="sm">{t('aiConfig.oauthCancel')}</Button>
      )}
    </div>
  );
}

export const AiSettingsPanel: React.FC = () => {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<AiConfigProvider[]>([]);
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [customName, setCustomName] = useState('');
  const [customBaseUrl, setCustomBaseUrl] = useState('');
  const [customModels, setCustomModels] = useState('');
  const [testMsg, setTestMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await listAiConfigProviders();
      setProviders(data.providers);
      setActiveProvider(data.active_provider);
    } catch {
      // 读取失败保留现有展示
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggleExpand = useCallback((id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const handleSetActive = useCallback(async (providerId: string) => {
    try {
      await setActiveAiProvider(providerId);
      await refresh();
    } catch {
      // 切换失败静默
    }
  }, [refresh]);

  const handleDeleteAccount = useCallback(async (providerId: string, accountId: string) => {
    try {
      await deleteAiConfigAccount(providerId, accountId);
      await refresh();
    } catch {
      // 删除失败静默
    }
  }, [refresh]);

  const handleAddCustom = useCallback(async () => {
    if (!customName.trim() || !customBaseUrl.trim()) return;
    try {
      await createCustomAiProvider({
        name: customName.trim(),
        base_url: customBaseUrl.trim(),
        models: customModels.split(',').map((m) => m.trim()).filter(Boolean),
      });
      setCustomName('');
      setCustomBaseUrl('');
      setCustomModels('');
      await refresh();
    } catch {
      // 添加失败静默
    }
  }, [customName, customBaseUrl, customModels, refresh]);

  const handleDeleteCustom = useCallback(async (providerId: string) => {
    try {
      await deleteCustomAiProvider(providerId);
      await refresh();
    } catch {
      // 删除失败静默
    }
  }, [refresh]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setTestMsg(null);
    try {
      const result = await testAiConfigConnection();
      setTestMsg({ ok: result.ok, text: result.ok ? t('aiConfig.testOk', { latency: result.latency_ms ?? 0 }) : t('aiConfig.testFail', { message: result.message }) });
    } catch {
      setTestMsg({ ok: false, text: t('aiConfig.testFail', { message: '' }) });
    } finally {
      setTesting(false);
    }
  }, [t]);

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle
          icon={<Sparkles className="h-5 w-5" />}
          title={t('aiConfig.title')}
          subtitle={t('aiConfig.subtitle')}
        >
          <Button onClick={() => void handleTest()} disabled={testing || !activeProvider} variant="secondary" size="sm" className="ml-3" data-testid="ai-test">
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
            {testing ? t('aiConfig.testing') : t('aiConfig.test')}
          </Button>
          {testMsg && (
            <span className={`ml-2 text-xs ${testMsg.ok ? 'text-emerald-400' : 'text-red-400'}`} data-testid="ai-test-result">{testMsg.text}</span>
          )}
        </SectionCardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {providers.map((provider) => (
          <ProviderBlock
            key={provider.id}
            provider={provider}
            active={provider.id === activeProvider}
            expanded={!!expanded[provider.id]}
            onToggle={() => toggleExpand(provider.id)}
            onSetActive={() => handleSetActive(provider.id)}
            onDeleteAccount={(accountId) => handleDeleteAccount(provider.id, accountId)}
            onDeleteCustom={provider.custom ? () => handleDeleteCustom(provider.id) : undefined}
            onSaved={refresh}
          />
        ))}
        <div className="rounded-md border border-dashed border-zinc-800 p-3">
          <p className="mb-2 text-xs text-zinc-400">{t('aiConfig.customAddTitle')}</p>
          <div className="flex flex-wrap gap-2">
            <input
              className="h-8 min-w-[140px] flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              placeholder={t('aiConfig.customNameLabel')}
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              aria-label={t('aiConfig.customNameLabel')}
            />
            <input
              className="h-8 min-w-[200px] flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              placeholder={t('aiConfig.customBaseUrlLabel')}
              value={customBaseUrl}
              onChange={(e) => setCustomBaseUrl(e.target.value)}
              aria-label={t('aiConfig.customBaseUrlLabel')}
            />
            <input
              className="h-8 min-w-[180px] flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              placeholder={t('aiConfig.customModelsLabel')}
              value={customModels}
              onChange={(e) => setCustomModels(e.target.value)}
              aria-label={t('aiConfig.customModelsLabel')}
            />
            <Button onClick={() => void handleAddCustom()} disabled={!customName.trim() || !customBaseUrl.trim()} variant="secondary" size="sm">
              <Plus className="h-4 w-4" />
              {t('aiConfig.customAdd')}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

interface ProviderBlockProps {
  provider: AiConfigProvider;
  active: boolean;
  expanded: boolean;
  onToggle: () => void;
  onSetActive: () => void;
  onDeleteAccount: (accountId: string) => void;
  onDeleteCustom?: () => void;
  onSaved: () => void;
}

function ProviderBlock({ provider, active, expanded, onToggle, onSetActive, onDeleteAccount, onDeleteCustom, onSaved }: ProviderBlockProps) {
  const { t } = useTranslation();
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40" data-testid={`ai-provider-${provider.id}`}>
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          onClick={onToggle}
          aria-expanded={expanded}
          data-testid={`ai-toggle-${provider.id}`}
        >
          {expanded ? <ChevronDown className="h-4 w-4 shrink-0 text-zinc-400" /> : <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" />}
          <ProviderIcon icon={provider.icon} />
          <span className="truncate text-sm font-medium text-zinc-100" data-testid={`ai-name-${provider.id}`}>{provider.name}</span>
          {active && (
            <span className="rounded-full bg-cyan-600/20 px-2 py-0.5 text-xs text-cyan-200" data-testid={`ai-active-${provider.id}`}>{t('aiConfig.currentBadge')}</span>
          )}
        </button>
        {!active && (
          <Button onClick={onSetActive} variant="secondary" size="sm" data-testid={`ai-set-active-${provider.id}`}>
            {t('aiConfig.setActive')}
          </Button>
        )}
      </div>

      {expanded && (
        <div className="space-y-2 border-t border-zinc-800 px-3 py-2">
          <p className="text-xs text-zinc-500">
            {t('aiConfig.baseUrlLabel')}: <span className="font-mono">{provider.base_url || '-'}</span>
          </p>
          {provider.accounts.length === 0 && (
            <p className="text-xs text-zinc-600">{t('aiConfig.notConfigured')}</p>
          )}
          {provider.accounts.map((account) => (
            <AccountRow key={account.id} account={account} onDelete={() => onDeleteAccount(account.id)} />
          ))}
          <AccountForm providerId={provider.id} onSaved={onSaved} />
          {provider.oauth && <CodexOAuthFlow onDone={onSaved} />}
          {onDeleteCustom && (
            <Button onClick={onDeleteCustom} variant="danger" size="sm">
              <Trash2 className="h-4 w-4" />
              {t('aiConfig.delete')}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function AccountRow({ account, onDelete }: { account: AiConfigAccount; onDelete: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md bg-zinc-900/60 px-2 py-1.5">
      <span className="text-sm text-zinc-200">{account.name}</span>
      {account.has_api_key && (
        <code className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300" data-testid={`ai-key-${account.id}`}>{account.api_key_masked}</code>
      )}
      {account.oauth_connected && <span className="text-xs text-emerald-400">{t('aiConfig.configured')}</span>}
      {!account.has_api_key && !account.oauth_connected && <span className="text-xs text-zinc-600">{t('aiConfig.notConfigured')}</span>}
      <Button onClick={onDelete} variant="ghost" size="sm" className="ml-auto text-zinc-500 hover:text-red-400" aria-label={t('aiConfig.delete')}>
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
}

